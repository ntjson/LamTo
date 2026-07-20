"""Operator workspace: triage, cases, work orders, proposals."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.capabilities import (
    LEDGER_PUBLISH,
    PROPOSAL_APPROVE,
    PROPOSAL_CREATE,
    REPORT_TRIAGE,
    WORK_ASSIGN,
)
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
from lamto.finance.approvals import build_approval_evidence_typed_data
from lamto.finance.proposals import (
    ZERO_HASH,
    build_proposal_evidence_payload,
    create_proposal,
    submit_proposal_version,
)
from lamto.maintenance.models import IssueReport, MaintenanceCase, WorkOrder
from lamto.web.forms.staff import (
    ConfirmTriageForm,
    CreateProposalForm,
    CreateWorkOrderForm,
    PreparePublicationForm,
    ProposalDecisionForm,
    SignProposalForm,
)
from lamto.web.staff import require_staff_capability, resolve_active_membership, staff_context
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
    work_order = proposal.work_order
    acceptance = getattr(work_order, "acceptance", None)
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
def case_list(request):
    membership, memberships = require_staff_capability(request, REPORT_TRIAGE)
    building_id = membership.organization.building_id
    # Active cases filter by urgency (same ?status= chip pattern as work list).
    from lamto.maintenance.ai import URGENCIES

    status = request.GET.get("status") or ""
    urgency_groups = {"routine": ("LOW", "MEDIUM"), "urgent": ("HIGH", "EMERGENCY")}
    valid_status = status in URGENCIES
    active_group = status if status in urgency_groups else next(
        (group for group, values in urgency_groups.items() if status in values), ""
    )
    from django.db.models import Count

    report_list = prepare_record_list(
        request,
        IssueReport.objects.filter(
            unit__building_id=building_id, status=IssueReport.Status.OPEN
        ),
        search_fields=("text", "location_path_snapshot"),
        sorts=(("", "Newest first", ("-created_at",)),),
        page_param="rpage",
    )
    cases_qs = (
        MaintenanceCase.objects.filter(building_id=building_id, active=True)
        .select_related("location")
        .annotate(work_count=Count("work_orders"))
    )
    if status in urgency_groups:
        cases_qs = cases_qs.filter(urgency__in=urgency_groups[status])
    elif valid_status:
        cases_qs = cases_qs.filter(urgency=status)
    case_list = prepare_record_list(
        request,
        cases_qs,
        search_fields=("category", "department", "location__name"),
        sorts=(
            ("", "Newest first", ("-created_at",)),
            ("deadline", "Deadline soonest", ("deadline_at",)),
        ),
    )
    urgency_labels = {
        "LOW": "Low",
        "MEDIUM": "Medium",
        "HIGH": "High",
        "EMERGENCY": "Emergency",
    }
    from lamto.web.views.staff_common import deadline_tone

    report_items = [
        {
            "url": f"/s/reports/{r.pk}/",
            "title": r.text,
            "status": r.get_status_display(),
            "deadline": None,
            "deadline_tone": "neutral",
            "next_action": "Confirm triage",
        }
        for r in report_list["page"].object_list
    ]
    case_items = [
        {
            "url": f"/s/cases/{c.pk}/",
            "title": f"Case #{c.pk} · {c.category} · {c.location.name}",
            "status": urgency_labels.get(c.urgency, c.urgency.title()),
            "deadline": c.deadline_at,
            "deadline_tone": deadline_tone(c.deadline_at),
            "next_action": (
                "Create work order" if c.work_count == 0 else "Follow work in progress"
            ),
        }
        for c in case_list["page"].object_list
    ]
    filters = [
        {"label": label, "value": value, "active": value == active_group}
        for value, label in (("routine", "Routine"), ("urgent", "Urgent"))
    ]
    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            list_mode=True,
            report_items=report_items,
            report_list=report_list,
            case_items=case_items,
            case_list=case_list,
            search_label="Search reports and cases",
            filters=filters,
            filters_active=valid_status or status in urgency_groups,
            filter_param="status",
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def report_detail(request, pk):
    """Staff triage surface for IssueReport pk only (not MaintenanceCase)."""
    membership, memberships = resolve_active_membership(request)
    building_id = membership.organization.building_id
    report = get_object_or_404(IssueReport, pk=pk, unit__building_id=building_id)

    link = report.case_reports.filter(case__active=True).select_related("case").first()
    if link is not None:
        return redirect("web:case-detail", pk=link.case_id)

    form = ConfirmTriageForm(request.POST or None, building_id=building_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm_triage":
            require_staff_capability(request, REPORT_TRIAGE)
            if form.is_valid():
                try:
                    case = form.save(report, request.user)
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        form.add_error(None, error)
                    else:
                        raise
                else:
                    record_audit(
                        request.user,
                        membership,
                        "workspace.triage.confirm",
                        "MaintenanceCase",
                        str(case.pk),
                        "accepted",
                    )
                    messages.success(
                        request,
                        "Triage confirmed. Create a work order to assign the repair.",
                    )
                    return redirect("web:case-detail", pk=case.pk)

    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            report=report,
            case=None,
            form=form,
            work_form=None,
            work_orders=[],
            list_mode=False,
            mode="report",
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def case_detail(request, pk):
    """MaintenanceCase pk only (not IssueReport)."""
    membership, memberships = resolve_active_membership(request)
    building_id = membership.organization.building_id
    case = get_object_or_404(MaintenanceCase, pk=pk, building_id=building_id)
    report = case.reports.order_by("pk").first()

    work_form = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_work_order":
            require_staff_capability(request, WORK_ASSIGN)
            work_form = CreateWorkOrderForm(request.POST, building_id=building_id)
            if work_form.is_valid():
                try:
                    wo = work_form.save(case, request.user)
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        work_form.add_error(None, error)
                    else:
                        raise
                else:
                    messages.success(
                        request,
                        f"Work order #{wo.pk} created. The assignee can now start work.",
                    )
                    return redirect("web:work-order-detail", pk=wo.pk)

    if work_form is None:
        work_form = CreateWorkOrderForm(building_id=building_id)

    work_orders = list(case.work_orders.order_by("-created_at"))

    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            report=report,
            case=case,
            form=None,
            work_form=work_form,
            work_orders=work_orders,
            list_mode=False,
            mode="case",
        ),
    )


@login_required
@require_GET
def proposal_list(request):
    membership, memberships = resolve_active_membership(request)
    caps = set(
        membership.capabilitygrant_set.values_list("code", flat=True)
    )
    if (
        PROPOSAL_CREATE not in caps
        and PROPOSAL_APPROVE not in caps
        and LEDGER_PUBLISH not in caps
    ):
        record_audit(
            request.user,
            membership,
            "workspace.proposal.list",
            "OrganizationMembership",
            str(membership.pk),
            "denied",
            {},
        )
        raise PermissionDenied("proposal access")

    building_id = membership.organization.building_id
    status = request.GET.get("status") or ""
    status_groups = {
        "preparing": (Proposal.Status.DRAFT, Proposal.Status.REJECTED),
        "review": (Proposal.Status.IN_REVIEW, Proposal.Status.EMERGENCY_EVIDENCE),
        "authorized": (Proposal.Status.NORMAL_AUTHORIZED,),
    }
    valid_status = status in Proposal.Status.values
    active_group = status if status in status_groups else next(
        (group for group, values in status_groups.items() if status in values), ""
    )
    proposals_qs = Proposal.objects.filter(work_order__case__building_id=building_id)
    if status in status_groups:
        proposals_qs = proposals_qs.filter(status__in=status_groups[status])
    elif valid_status:
        proposals_qs = proposals_qs.filter(status=status)
    list_meta = prepare_record_list(
        request,
        proposals_qs.select_related("current_version", "work_order__case"),
        search_fields=(
            "current_version__contractor_name",
            "work_order__case__category",
        ),
        sorts=(("", "Newest first", ("-created_at",)),),
    )
    next_actions = {
        Proposal.Status.DRAFT: "Complete and submit",
        Proposal.Status.IN_REVIEW: "Review and decide",
        Proposal.Status.NORMAL_AUTHORIZED: "Continue to acceptance and payment",
        Proposal.Status.EMERGENCY_EVIDENCE: "Review emergency evidence",
        Proposal.Status.REJECTED: "Correct and resubmit",
    }
    proposal_items = [
        {
            "url": f"/s/proposals/{p.pk}/",
            "title": f"Proposal #{p.pk} · {p.work_order.case.category}"
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
            can_publish=LEDGER_PUBLISH in caps,
            publish_only=LEDGER_PUBLISH in caps
            and PROPOSAL_CREATE not in caps
            and PROPOSAL_APPROVE not in caps,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def proposal_detail(request, pk):
    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    if (
        PROPOSAL_CREATE not in caps
        and PROPOSAL_APPROVE not in caps
        and LEDGER_PUBLISH not in caps
    ):
        raise PermissionDenied("proposal access")

    proposal = get_object_or_404(
        Proposal.objects.select_related(
            "current_version", "work_order__case", "creator_membership"
        ),
        pk=pk,
        work_order__case__building_id=membership.organization.building_id,
    )
    form = ProposalDecisionForm(request.POST or None)
    publish_form = PreparePublicationForm(request.POST or None)
    can_publish = LEDGER_PUBLISH in caps and _proposal_publishable(proposal)
    can_approve = PROPOSAL_APPROVE in caps
    version = proposal.current_version
    typed_data = None
    typed_data_options = None
    publish_typed_data = None
    publish_expected_signer = ""

    if request.method == "POST":
        action = request.POST.get("action") or "decide"
        # Signed financial / accountability actions require recent re-auth.
        if action in ("publish", "decide"):
            require_recent_auth(request)
        if action == "publish":
            if not can_publish:
                messages.error(
                    request,
                    "Publication is not ready to sign. Review the unmet checks on this "
                    "page, or wait if a publication snapshot is already awaiting confirmation.",
                )
            else:
                require_staff_capability(request, LEDGER_PUBLISH)
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
                                f"{membership.get_role_display()} · "
                                f"{membership.organization.name}"
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
        elif action == "decide" and can_approve:
            if form.is_valid():
                try:
                    form.save(version, membership)
                except (ValidationError, PermissionDenied) as error:
                    # Keep a visible flash — rebuilding the sign form below
                    # replaces the bound form and would hide field errors.
                    signed_action_failure(
                        request,
                        error,
                        action="The decision",
                        next_step="Check your decision and reason, then sign again.",
                    )
                else:
                    messages.success(
                        request,
                        "Decision recorded and added to the evidence chain. If approved, "
                        "the proposal moves to the next required approval; if rejected, "
                        "it returns to the creator for correction.",
                    )
                    return redirect("web:proposal-detail", pk=proposal.pk)
            else:
                # e.g. empty signature (MetaMask did not run / user left field blank)
                detail = "; ".join(
                    e for errs in form.errors.values() for e in errs
                ) or "Form invalid."
                messages.error(
                    request,
                    f"Decision not saved: {detail} "
                    "Your reason and decision are still here. Connect the registered wallet and submit again.",
                )

    # Embed EIP-712 typed data so wallet-signing.js + MetaMask can fill signature.
    if can_approve and version is not None:
        # Always mint a fresh event id on render so a failed attempt cannot
        # resubmit a stale signature against a new payload.
        decision = "APPROVE"
        reason = ""
        if request.method == "POST" and form is not None and form.is_bound:
            decision = (form.data.get("decision") or "APPROVE").upper()
            reason = form.data.get("reason") or ""
        elif request.method == "GET":
            decision = (request.GET.get("decision") or "APPROVE").upper()
        if decision not in ("APPROVE", "REJECT"):
            decision = "APPROVE"
        event_id = new_event_id()
        form = ProposalDecisionForm(
            initial={
                "event_id": event_id,
                "decision": decision,
                "reason": reason,
            }
        )
        try:
            options = {
                value: build_approval_evidence_typed_data(
                    version, membership, value, event_id
                )
                for value in ("APPROVE", "REJECT")
            }
            typed_data = json.dumps(options[decision])
            typed_data_options = json.dumps(options)
        except (ValidationError, PermissionDenied, ValueError):
            typed_data = None
            typed_data_options = None

    expected_signer = ""
    if can_approve:
        wallet = (
            SignerWallet.objects.filter(membership=membership, active=True)
            .order_by("pk")
            .first()
        )
        if wallet is not None:
            expected_signer = wallet.address

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
                    "This user is blocked from publishing (creator / board approver / "
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
            form=form if can_approve else None,
            can_approve=can_approve,
            publish_form=publish_form if can_publish else None,
            can_publish=can_publish,
            typed_data=typed_data,
            typed_data_options=typed_data_options,
            expected_signer=expected_signer,
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
    """Two-phase create-proposal from a spending work order (spec 4.3.1).

    action=prepare: upload quotation pair + create the DRAFT proposal, then
    render the signed form with the exact typed data. action=submit: freeze
    the immutable version via the domain service.
    """
    membership, memberships = require_staff_capability(request, PROPOSAL_CREATE)
    building_id = membership.organization.building_id
    work_order = get_object_or_404(
        WorkOrder.objects.select_related("case"),
        pk=pk,
        case__building_id=building_id,
    )
    if request.method == "POST":
        require_recent_auth(request)
    if not work_order.requires_spending:
        messages.error(request, "This work order does not require spending.")
        return redirect("web:work-order-detail", pk=work_order.pk)

    existing = (
        Proposal.objects.filter(work_order=work_order)
        .select_related("current_version")
        .first()
    )
    if existing is not None and existing.current_version_id is not None:
        messages.info(request, "A proposal has already been submitted for this work order.")
        return redirect("web:proposal-detail", pk=existing.pk)

    create_form = CreateProposalForm(request.POST or None, request.FILES or None)
    sign_form = None
    typed_data = None
    action = request.POST.get("action") if request.method == "POST" else None

    if action == "prepare" and create_form.is_valid():
        try:
            original, _redacted = upload_document_pair(
                work_order.case.building,
                Document.Kind.QUOTATION,
                request.user,
                create_form.cleaned_data["quotation_original"],
                create_form.cleaned_data["quotation_redacted"],
            )
            proposal = existing or create_proposal(work_order, membership)
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
                work_order__case__building_id=building_id,
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
                messages.success(request, "Proposal submitted for Board review.")
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
            work_order=work_order,
            create_form=create_form,
            sign_form=sign_form,
            typed_data=typed_data,
        ),
    )
