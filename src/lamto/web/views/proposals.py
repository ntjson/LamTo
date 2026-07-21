"""Management workspace: triage, cases, work orders, proposals."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.security import require_recent_auth
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import (
    PaymentVerification,
    Proposal,
    PublicationSnapshot,
    PublishedLedgerEntry,
)
from lamto.accounts.models import SignerWallet
from lamto.finance.proposals import (
    ZERO_HASH,
    build_proposal_evidence_payload,
    create_proposal,
    create_standalone_proposal,
    decide_proposal,
    publish_proposal_version,
    submit_proposal_version,
    spending_proposal_cases,
)
from lamto.maintenance.models import IssueReport, MaintenanceCase
from lamto.maintenance.cases import complete_proposal_work, publish_progress, start_case_work
from lamto.web.forms.staff import (
    ConfirmTriageForm,
    CreateProposalForm,
    PreparePublicationForm,
    SignProposalForm,
    StandaloneProposalForm,
)
from lamto.web.staff import require_management_context, staff_context
from lamto.web.views.staff_common import (
    accountability_chain_for,
    prepare_record_list,
    set_sign_confirmation,
    signed_action_failure,
)
from lamto.web.staff_signing import new_event_id, upload_document_pair


def _proposal_publishable(proposal) -> bool:
    """True when verified payment chain is ready and nothing is published yet."""
    if PublicationSnapshot.objects.filter(proposal=proposal).exists():
        return False
    if PublishedLedgerEntry.objects.filter(proposal=proposal).exists():
        return False
    acceptance = getattr(proposal.case, "acceptance", None)
    if acceptance is None:
        return False
    payment = getattr(acceptance, "payment", None)
    if payment is None:
        return False
    verification = getattr(payment, "verification", None)
    if verification is None:
        return False
    return verification.decision == PaymentVerification.Decision.VERIFIED


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
    publish_form = PreparePublicationForm(request.POST or None)
    can_publish = _proposal_publishable(proposal)
    version = proposal.current_version
    publish_typed_data = None
    publish_expected_signer = ""

    if request.method == "POST":
        action = request.POST.get("action") or "publish"
        if action in {"decide", "progress", "complete"}:
            require_recent_auth(request)
            try:
                if action == "decide":
                    proceed = request.POST.get("proceed") in {"1", "true", "on"}
                    with transaction.atomic():
                        decide_proposal(
                            proposal, request.user, proceed, request.POST.get("note", ""),
                        )
                        if proceed and proposal.case_id:
                            start_case_work(proposal.case, request.user)
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
        # Signed financial / accountability actions require recent re-auth.
        if action == "publish":
            require_recent_auth(request)
        if action == "publish":
            if not can_publish:
                messages.error(
                    request,
                    "Publication is not ready to sign. Review the unmet checks on this "
                    "page, or wait if a publication snapshot is already awaiting confirmation.",
                )
            else:
                require_management_context(request)
                if publish_form.is_valid():
                    try:
                        snapshot = publish_form.save(proposal, membership)
                    except (ValidationError, PermissionDenied) as error:
                        signed_action_failure(
                            request,
                            error,
                            action="The publication",
                            next_step="Check the publication details, then sign again.",
                        )
                    else:
                        event_ref = getattr(
                            getattr(snapshot, "outbox_event", None), "event_id", ""
                        ) or publish_form.cleaned_data.get("event_id", "")
                        short_ref = (
                            f"{event_ref[:10]}…"
                            if event_ref and len(event_ref) > 12
                            else event_ref or f"snapshot #{snapshot.pk}"
                        )
                        amount = (
                            proposal.current_version.amount_vnd
                            if proposal.current_version_id
                            else None
                        )
                        amount_display = (
                            f"{amount:,} VND" if amount is not None else "—"
                        )
                        contractor = (
                            proposal.current_version.contractor_name
                            if proposal.current_version_id
                            else "—"
                        )
                        set_sign_confirmation(
                            request,
                            action="Publish to resident ledger",
                            acting_as=(
                                f"{membership.building.name}"
                            ),
                            details=[
                                {
                                    "label": "Proposal",
                                    "value": f"#{proposal.pk}",
                                },
                                {"label": "Amount", "value": amount_display},
                                {"label": "Contractor", "value": contractor},
                                {
                                    "label": "Receipt anchor",
                                    "value": short_ref,
                                },
                            ],
                            consequence=(
                                "An append-only resident-ledger snapshot is prepared. "
                                "It is not yet a finalized public expense."
                            ),
                            what_next=(
                                "Independent confirmation must finish before residents "
                                "see this verified expense on the public ledger. "
                                "Publication stays amber until that confirmation lands."
                            ),
                            status_note=(
                                "Signed — awaiting independent confirmation"
                            ),
                        )
                        messages.success(
                            request,
                            f"Publication signed for proposal #{proposal.pk}. "
                            "Awaiting independent confirmation before residents see it.",
                        )
                        return redirect("web:proposal-detail", pk=proposal.pk)
                else:
                    detail = "; ".join(
                        e for errs in publish_form.errors.values() for e in errs
                    ) or "Form invalid."
                    messages.error(
                        request,
                        f"Publication not saved: {detail} "
                        "Your entries are still here. Connect the registered publisher wallet and try again.",
                    )
    if can_publish:
        from django.utils import timezone as dj_tz

        from lamto.evidence.services import utc_rfc3339
        from lamto.finance.publication import (
            allocate_publication_id,
            build_publication_sign_package,
        )

        pub_event_id = new_event_id()
        pub_id = allocate_publication_id()
        pub_ts = dj_tz.now()
        if publish_form is not None and publish_form.is_bound:
            if publish_form.data.get("event_id"):
                pub_event_id = publish_form.data.get("event_id").strip() or pub_event_id
            try:
                pub_id = int(publish_form.data.get("publication_id") or pub_id)
            except (TypeError, ValueError):
                pass
            raw_ts = (publish_form.data.get("publication_timestamp") or "").strip()
            if raw_ts:
                from django.utils.dateparse import parse_datetime

                parsed = parse_datetime(raw_ts)
                if parsed is not None:
                    if dj_tz.is_naive(parsed):
                        parsed = dj_tz.make_aware(parsed, dj_tz.utc)
                    pub_ts = parsed
        try:
            package = build_publication_sign_package(
                proposal,
                membership,
                event_id=pub_event_id,
                publication_id=pub_id,
                timestamp=pub_ts,
            )
            publish_typed_data = json.dumps(package["typed_data"])
            if package.get("forbidden_publisher"):
                messages.warning(
                    request,
                    "This user is blocked from publishing (creator / "
                    "payment recorder). Use pilot-eligible-publisher.",
                )
        except (ValidationError, PermissionDenied, ValueError) as error:
            publish_typed_data = None
            detail = (
                error.messages[0]
                if getattr(error, "messages", None)
                else "The publication package could not be prepared."
            )
            messages.error(
                request,
                f"Publication is not ready to sign. {detail} "
                "Resolve the issue above, then reload this page.",
            )
        publish_form = PreparePublicationForm(
            initial={
                "event_id": pub_event_id,
                "publication_id": pub_id,
                "publication_timestamp": utc_rfc3339(pub_ts),
                "reason": (publish_form.data.get("reason") if publish_form and publish_form.is_bound else "")
                or "Publish ledger pilot",
            }
        )
        wallet = (
            SignerWallet.objects.filter(membership=membership, active=True)
            .order_by("pk")
            .first()
        )
        if wallet is not None:
            publish_expected_signer = wallet.address

    publication_pending = False
    publication_snapshot = None
    try:
        publication_snapshot = proposal.publication_snapshot
    except PublicationSnapshot.DoesNotExist:
        publication_snapshot = None
    if publication_snapshot is not None and not PublishedLedgerEntry.objects.filter(
        proposal=proposal
    ).exists():
        publication_pending = True

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
            publish_typed_data=publish_typed_data,
            publish_expected_signer=publish_expected_signer,
            publication_pending=publication_pending,
            publication_snapshot=publication_snapshot,
            accountability_stages=accountability_chain_for(proposal),
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def proposal_create(request, pk):
    """Two-phase create-proposal from a spending case (spec 4.3.1).

    action=prepare: upload quotation pair + create the DRAFT proposal, then
    render the signed form with the exact typed data. action=submit: freeze
    the immutable version via the domain service.
    """
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
    sign_form = None
    typed_data = None
    action = request.POST.get("action") if request.method == "POST" else None

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
            action = None
        else:
            messages.success(request, "Proposal published.")
            return redirect("web:proposal-detail", pk=proposal.pk)

    if action == "prepare" and create_form.is_valid():
        try:
            original, _redacted = upload_document_pair(
                case.building,
                Document.Kind.QUOTATION,
                request.user,
                create_form.cleaned_data["quotation_original"],
                create_form.cleaned_data["quotation_redacted"],
            )
            proposal = existing or create_proposal(case, membership)
            amount = create_form.cleaned_data["amount_vnd"]
            contractor = create_form.cleaned_data["contractor_name"]
            payload = build_proposal_evidence_payload(proposal, amount, contractor, [original])
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                create_form.add_error(None, error)
            else:
                raise
        else:
            event_id = new_event_id()
            typed_data = json.dumps(
                build_evidence_typed_data(
                    event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), ZERO_HASH
                )
            )
            sign_form = SignProposalForm(
                initial={
                    "event_id": event_id,
                    "amount_vnd": amount,
                    "contractor_name": contractor,
                    "quotation_original_id": original.pk,
                    "proposal_id": proposal.pk,
                }
            )
    elif action == "submit":
        sign_form = SignProposalForm(request.POST)
        if sign_form.is_valid():
            proposal = get_object_or_404(
                Proposal,
                pk=sign_form.cleaned_data["proposal_id"],
                case__building_id=building_id,
            )
            original = get_object_or_404(
                DocumentVersion,
                pk=sign_form.cleaned_data["quotation_original_id"],
                document__building_id=building_id,
            )
            try:
                submit_proposal_version(
                    proposal,
                    sign_form.cleaned_data["amount_vnd"],
                    sign_form.cleaned_data["contractor_name"],
                    [original],
                    sign_form.cleaned_data["signature"],
                    sign_form.cleaned_data["event_id"],
                )
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    sign_form.add_error(None, error)
                else:
                    raise
            else:
                messages.success(request, "Proposal submitted for Management review.")
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
            sign_form=sign_form,
            typed_data=typed_data,
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
        case=None, create_form=form, sign_form=None, typed_data=None,
    ))
