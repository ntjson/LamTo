"""Management workspace: triage, cases, work orders, proposals."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.security import require_recent_auth
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion
from lamto.finance.models import (
    Proposal,
    PublishedLedgerEntry,
)
from lamto.finance.proposals import (
    ZERO_HASH,
    build_proposal_evidence_payload,
    create_proposal,
    create_standalone_proposal,
    decide_proposal,
    publish_proposal_version,
    spending_proposal_cases,
)
from lamto.maintenance.models import IssueReport, MaintenanceCase
from lamto.maintenance.cases import complete_proposal_work, publish_progress, start_case_work
from lamto.web.forms.staff import (
    ConfirmTriageForm,
    CreateProposalForm,
    StandaloneProposalForm,
)
from lamto.web.staff import require_management_context, staff_context
from lamto.web.views.staff_common import (
    accountability_chain_for,
    prepare_record_list,
)
from lamto.web.staff_documents import new_event_id, upload_document_pair


def _proposal_publishable(proposal) -> bool:
    """True when verified payment chain is ready and nothing is published yet."""
    if PublishedLedgerEntry.objects.filter(proposal=proposal).exists():
        return False
    settlement = getattr(proposal, "settlement", None)
    return settlement is not None and settlement.settled_at is not None


@login_required
@require_GET
def proposal_list(request):
    membership, memberships = require_management_context(request)
    building_id = membership.building_id
    status = request.GET.get("status") or ""
    status_groups = {
        "preparing": (Proposal.Status.DRAFT,),
        "review": (Proposal.Status.PUBLISHED,),
        "authorized": (Proposal.Status.IN_PROGRESS, Proposal.Status.COMPLETED),
    }
    valid_status = status in Proposal.Status.values
    active_group = status if status in status_groups else next(
        (group for group, values in status_groups.items() if status in values), ""
    )
    proposals_qs = Proposal.objects.filter(building_id=building_id)
    if status in status_groups:
        proposals_qs = proposals_qs.filter(status__in=status_groups[status])
    elif valid_status:
        proposals_qs = proposals_qs.filter(status=status)
    list_meta = prepare_record_list(
        request,
        proposals_qs.select_related("current_version", "case"),
        search_fields=(
            "current_version__contractor_name",
            "case__category",
        ),
        sorts=(("", "Newest first", ("-created_at",)),),
    )
    next_actions = {
        Proposal.Status.DRAFT: "Complete and submit",
        Proposal.Status.PUBLISHED: "Review and decide",
        Proposal.Status.IN_PROGRESS: "Publish progress or complete",
    }
    proposal_items = [
        {
            "url": f"/s/proposals/{p.pk}/",
            "title": f"Proposal #{p.pk} · {p.case.category if p.case_id else p.current_version.purpose if p.current_version else 'Standalone'}"
            + (
                f" · {p.current_version.contractor_name}"
                if p.current_version
                else ""
            ),
            "amount_vnd": p.current_version.amount_vnd if p.current_version else None,
            "status": p.get_status_display(),
            "deadline": None,
            "deadline_tone": "neutral",
            "next_action": next_actions.get(p.status, ""),
        }
        for p in list_meta["page"].object_list
    ]
    filters = [
        {"label": label, "value": value, "active": value == active_group}
        for value, label in (
            ("preparing", "Preparing"),
            ("review", "Review"),
            ("authorized", "Authorized"),
        )
    ]
    return render(
        request,
        "web/staff/proposal_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            finance_active="proposals",
            list_mode=True,
            proposal_items=proposal_items,
            list_meta=list_meta,
            search_label="Search proposals",
            search_placeholder="ID, contractor, or category…",
            filters=filters,
            filters_active=valid_status or status in status_groups,
            filter_param="status",
            can_publish=True,
            publish_only=False,
        ),
    )

@login_required
@require_http_methods(["GET", "POST"])
def proposal_detail(request, pk):
    membership, memberships = require_management_context(request)
    proposal = get_object_or_404(
        Proposal.objects.select_related(
            "current_version", "case", "creator_membership"
        ),
        pk=pk,
        building_id=membership.building_id,
    )
    publish_form = None
    can_publish = False
    version = proposal.current_version

    if request.method == "POST":
        action = request.POST.get("action") or "publish"
        if action in {"decide", "progress", "complete"}:
            require_recent_auth(request)
            try:
                if action == "decide":
                    proceed = request.POST.get("proceed") in {"1", "true", "on"}
                    with transaction.atomic():
                        if proceed and proposal.case_id:
                            start_case_work(proposal.case, request.user)
                        decide_proposal(
                            proposal, request.user, proceed, request.POST.get("note", ""),
                        )
                elif action == "progress":
                    publish_progress(
                        proposal=proposal, manager=request.user, cause=request.POST.get("cause", ""),
                        result=request.POST.get("result", ""),
                    )
                else:
                    complete_proposal_work(
                        proposal, request.user, request.POST.get("cause", ""),
                        request.POST.get("result", ""),
                    )
            except (ValidationError, PermissionDenied) as error:
                messages.error(request, str(error))
            else:
                messages.success(request, "Proposal updated.")
            return redirect("web:proposal-detail", pk=proposal.pk)

    publication_pending = False
    publication_snapshot = None

    return render(
        request,
        "web/staff/proposal_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            finance_active="proposals",
            list_mode=False,
            proposal=proposal,
            version=version,
            publish_form=publish_form if can_publish else None,
            can_publish=can_publish,
            publication_pending=publication_pending,
            publication_snapshot=publication_snapshot,
            accountability_stages=accountability_chain_for(proposal),
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def proposal_create(request, pk):
    membership, memberships = require_management_context(request)
    building_id = membership.building_id
    case = get_object_or_404(
        MaintenanceCase.objects.all(),
        pk=pk,
        building_id=building_id,
    )
    if request.method == "POST":
        require_recent_auth(request)
    if not spending_proposal_cases().filter(pk=case.pk).exists():
        messages.error(request, "This case is not eligible for a spending proposal.")
        return redirect("web:case-detail", pk=case.pk)
    existing = (
        Proposal.objects.filter(case=case)
        .select_related("current_version")
        .first()
    )
    if existing is not None and existing.current_version_id is not None:
        messages.info(request, "A proposal has already been submitted for this case.")
        return redirect("web:proposal-detail", pk=existing.pk)

    create_form = CreateProposalForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and create_form.is_valid():
        try:
            original, _redacted = upload_document_pair(
                case.building, Document.Kind.QUOTATION, request.user,
                create_form.cleaned_data["quotation_original"],
                create_form.cleaned_data["quotation_redacted"],
            )
            proposal = existing or create_proposal(case, membership)
            publish_proposal_version(
                proposal, membership, amount_vnd=create_form.cleaned_data["amount_vnd"],
                contractor_name=create_form.cleaned_data["contractor_name"],
                fund_code=create_form.cleaned_data.get("fund_code") or "GENERAL",
                purpose=create_form.cleaned_data.get("purpose") or case.category,
                proposed_action=create_form.cleaned_data.get("proposed_action") or "Perform proposed maintenance",
                expected_schedule=create_form.cleaned_data.get("expected_schedule") or "To be scheduled",
                quotation_versions=[original], event_id=new_event_id(),
            )
        except (ValidationError, PermissionDenied) as error:
            create_form.add_error(None, error)
        else:
            messages.success(request, "Proposal published.")
            return redirect("web:proposal-detail", pk=proposal.pk)

    return render(
        request,
        "web/staff/proposal_create.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            finance_active="proposals",
            case=case,
            create_form=create_form,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def standalone_proposal_create(request):
    membership, memberships = require_management_context(request)
    form = StandaloneProposalForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        require_recent_auth(request)
        if form.is_valid():
            try:
                original, _ = upload_document_pair(
                    membership.building, Document.Kind.QUOTATION, request.user,
                    form.cleaned_data["quotation_original"], form.cleaned_data["quotation_redacted"],
                )
                proposal = create_standalone_proposal(membership.building, membership)
                publish_proposal_version(
                    proposal, membership, amount_vnd=form.cleaned_data["amount_vnd"],
                    contractor_name=form.cleaned_data["contractor_name"],
                    fund_code=form.cleaned_data["fund_code"], purpose=form.cleaned_data["purpose"],
                    proposed_action=form.cleaned_data["proposed_action"],
                    expected_schedule=form.cleaned_data["expected_schedule"],
                    quotation_versions=[original], event_id=new_event_id(),
                )
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Proposal published.")
                return redirect("web:proposal-detail", pk=proposal.pk)
    return render(request, "web/staff/proposal_create.html", staff_context(
        request, membership, memberships, nav_active="finance", finance_active="proposals",
        case=None, create_form=form,
    ))
