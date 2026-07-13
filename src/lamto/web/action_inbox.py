"""Capability-scoped action inbox queries.

The inbox is authoritative for staff work; email is a secondary channel.
Never combines capabilities across memberships — callers pass a single membership.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from lamto.accounts.capabilities import (
    AUDIT_EXPORT,
    CORRECTION_APPROVE,
    CORRECTION_CREATE,
    EMERGENCY_AUTHORIZE,
    LEDGER_PUBLISH,
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    PROPOSAL_APPROVE,
    PROPOSAL_CREATE,
    REPORT_TRIAGE,
    WORK_ACCEPT,
    WORK_ASSIGN,
)
from lamto.accounts.models import CapabilityGrant, Organization, OrganizationMembership
from lamto.documents.models import QuarantinedUpload
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import (
    AcceptanceRecord,
    ApprovalDecision,
    Correction,
    CorrectionDecision,
    EmergencyAuthorization,
    EmergencyRatification,
    PaymentEvidence,
    PaymentVerification,
    Proposal,
    PublicationSnapshot,
    PublishedLedgerEntry,
    VerificationObservation,
)
from lamto.maintenance.models import (
    IssueReport,
    MaintenanceCase,
    TriageJob,
    WorkOrder,
)


@dataclass(frozen=True)
class ActionItem:
    kind: str
    title: str
    summary: str
    target_type: str
    target_id: int
    url: str
    priority: int = 50


def _has(membership, code: str) -> bool:
    if membership is None or not membership.active:
        return False
    return CapabilityGrant.objects.filter(membership=membership, code=code).exists()


def _building_id(membership) -> int:
    return membership.organization.building_id


def action_items_for(membership: OrganizationMembership) -> list[ActionItem]:
    """Return action items for a single active membership (never combined)."""
    if membership is None or not membership.active:
        return []
    membership = (
        OrganizationMembership.objects.select_related("organization", "user")
        .filter(pk=membership.pk, active=True)
        .first()
    )
    if membership is None:
        return []

    items: list[ActionItem] = []
    building_id = _building_id(membership)
    now = timezone.now()

    if _has(membership, REPORT_TRIAGE):
        items.extend(_manual_triage_items(building_id))
        items.extend(_deadline_risk_items(building_id))
        items.extend(_quarantined_upload_items(building_id, membership))

    if _has(membership, WORK_ASSIGN):
        items.extend(_deadline_risk_items(building_id))

    if membership.role == OrganizationMembership.Role.MAINTENANCE:
        items.extend(_assigned_work_items(membership.user_id, building_id))

    if _has(membership, PROPOSAL_CREATE):
        items.extend(_proposal_create_candidates(building_id))

    if _has(membership, PROPOSAL_APPROVE):
        items.extend(_proposal_approval_items(membership, building_id))

    if _has(membership, EMERGENCY_AUTHORIZE):
        items.extend(_emergency_items(building_id, membership))

    if membership.organization.kind == Organization.Kind.RESIDENT_REP and _has(
        membership, PROPOSAL_APPROVE
    ):
        items.extend(_emergency_ratification_items(building_id))

    if _has(membership, WORK_ACCEPT):
        items.extend(_work_acceptance_items(building_id))

    if _has(membership, PAYMENT_RECORD):
        items.extend(_payment_record_items(building_id))

    if _has(membership, PAYMENT_VERIFY):
        items.extend(_payment_verify_items(building_id))

    if _has(membership, LEDGER_PUBLISH):
        items.extend(_pending_publication_items(building_id))

    if _has(membership, CORRECTION_APPROVE) or _has(membership, CORRECTION_CREATE):
        items.extend(_correction_review_items(membership, building_id))

    if _has(membership, AUDIT_EXPORT) or membership.role == OrganizationMembership.Role.AUDITOR:
        items.extend(_integrity_mismatch_items(building_id))
        items.extend(_failed_outbox_items(building_id))

    # Board also sees integrity mismatch and failed outbox for ops awareness.
    if membership.organization.kind == Organization.Kind.BOARD:
        items.extend(_integrity_mismatch_items(building_id))
        items.extend(_failed_outbox_items(building_id))

    # Deduplicate by (kind, target_type, target_id)
    seen = set()
    unique: list[ActionItem] = []
    for item in sorted(items, key=lambda i: (i.priority, i.title, i.target_id)):
        key = (item.kind, item.target_type, item.target_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _manual_triage_items(building_id: int) -> list[ActionItem]:
    items = []
    qs = (
        IssueReport.objects.filter(
            unit__building_id=building_id,
            status=IssueReport.Status.OPEN,
        )
        .filter(
            Q(triage_job__status=TriageJob.Status.NEEDS_MANUAL)
            | Q(triage_job__status=TriageJob.Status.SUCCEEDED, triage_decision__isnull=True)
            | Q(triage_job__isnull=True)
        )
        .exclude(case_reports__case__active=True)
        .distinct()
        .order_by("created_at")[:50]
    )
    for report in qs:
        items.append(
            ActionItem(
                kind="manual_triage",
                title="Manual triage",
                summary=report.text[:120],
                target_type="IssueReport",
                target_id=report.pk,
                url=reverse("web:case-detail", kwargs={"pk": report.pk}),
                priority=10,
            )
        )
    return items


def _deadline_risk_items(building_id: int) -> list[ActionItem]:
    items = []
    horizon = timezone.now() + timedelta(hours=24)
    cases = MaintenanceCase.objects.filter(
        building_id=building_id,
        active=True,
        deadline_at__lte=horizon,
    ).order_by("deadline_at")[:30]
    for case in cases:
        items.append(
            ActionItem(
                kind="deadline_risk",
                title="Deadline risk",
                summary=f"Case #{case.pk} · {case.category} due {case.deadline_at}",
                target_type="MaintenanceCase",
                target_id=case.pk,
                url=reverse("web:case-detail", kwargs={"pk": case.pk}),
                priority=15,
            )
        )
    work = WorkOrder.objects.filter(
        case__building_id=building_id,
        deadline_at__lte=horizon,
        status__in=[
            WorkOrder.Status.ASSIGNED,
            WorkOrder.Status.IN_PROGRESS,
            WorkOrder.Status.AWAITING_ACCEPTANCE,
        ],
    ).order_by("deadline_at")[:30]
    for wo in work:
        items.append(
            ActionItem(
                kind="deadline_risk",
                title="Deadline risk",
                summary=f"Work order #{wo.pk} due {wo.deadline_at}",
                target_type="WorkOrder",
                target_id=wo.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": wo.pk}),
                priority=15,
            )
        )
    return items


def _assigned_work_items(user_id: int, building_id: int) -> list[ActionItem]:
    items = []
    qs = WorkOrder.objects.filter(
        case__building_id=building_id,
        assignee_id=user_id,
        status__in=[WorkOrder.Status.ASSIGNED, WorkOrder.Status.IN_PROGRESS],
    ).order_by("deadline_at")[:50]
    for wo in qs:
        items.append(
            ActionItem(
                kind="assigned_work",
                title="Assigned work",
                summary=f"Work order #{wo.pk} · {wo.status}",
                target_type="WorkOrder",
                target_id=wo.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": wo.pk}),
                priority=20,
            )
        )
    return items


def _proposal_create_candidates(building_id: int) -> list[ActionItem]:
    items = []
    qs = WorkOrder.objects.filter(
        case__building_id=building_id,
        requires_spending=True,
        authorization_status=WorkOrder.AuthorizationStatus.PENDING,
        proposal__isnull=True,
        emergency=False,
    ).order_by("created_at")[:30]
    for wo in qs:
        items.append(
            ActionItem(
                kind="proposal_create",
                title="Create proposal",
                summary=f"Work order #{wo.pk} needs a spending proposal",
                target_type="WorkOrder",
                target_id=wo.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": wo.pk}),
                priority=25,
            )
        )
    return items


def _proposal_approval_items(membership, building_id: int) -> list[ActionItem]:
    items = []
    stage = (
        ApprovalDecision.Stage.BOARD
        if membership.organization.kind == Organization.Kind.BOARD
        else ApprovalDecision.Stage.RESIDENT_REP
    )
    title = (
        "Proposal approval"
        if stage == ApprovalDecision.Stage.BOARD
        else "Representative co-approval"
    )
    qs = (
        Proposal.objects.filter(
            work_order__case__building_id=building_id,
            status=Proposal.Status.IN_REVIEW,
            current_version__isnull=False,
            mode=Proposal.Mode.NORMAL,
        )
        .exclude(
            current_version__approval_decisions__stage=stage,
        )
        .select_related("current_version")
        .order_by("created_at")[:50]
    )
    # RESIDENT_REP must wait for board approve
    for proposal in qs:
        version = proposal.current_version
        if version is None:
            continue
        if stage == ApprovalDecision.Stage.RESIDENT_REP:
            board = ApprovalDecision.objects.filter(
                version=version,
                stage=ApprovalDecision.Stage.BOARD,
                decision=ApprovalDecision.Decision.APPROVE,
            ).exists()
            if not board:
                continue
        items.append(
            ActionItem(
                kind="proposal_approval",
                title=title,
                summary=f"Proposal #{proposal.pk} · {version.amount_vnd} VND",
                target_type="Proposal",
                target_id=proposal.pk,
                url=reverse("web:proposal-detail", kwargs={"pk": proposal.pk}),
                priority=20 if stage == ApprovalDecision.Stage.BOARD else 22,
            )
        )
    return items


def _emergency_items(building_id: int, membership) -> list[ActionItem]:
    items = []
    # Pending emergency requests without authorization
    pending = WorkOrder.objects.filter(
        case__building_id=building_id,
        emergency=True,
        emergency_authorization__isnull=True,
    ).order_by("emergency_requested_at")[:30]
    for wo in pending:
        items.append(
            ActionItem(
                kind="emergency_authorize",
                title="Emergency authorization",
                summary=f"Work order #{wo.pk} · {wo.emergency_label or 'Emergency'}",
                target_type="WorkOrder",
                target_id=wo.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": wo.pk}),
                priority=5,
            )
        )
    # Open authorizations needing ratification (board may also track)
    open_auth = EmergencyAuthorization.objects.filter(
        work_order__case__building_id=building_id,
        ratification__isnull=True,
    ).order_by("ratification_deadline")[:30]
    for auth in open_auth:
        items.append(
            ActionItem(
                kind="emergency_ratification",
                title="Emergency ratification",
                summary=f"Authorization #{auth.pk} deadline {auth.ratification_deadline}",
                target_type="EmergencyAuthorization",
                target_id=auth.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": auth.work_order_id}),
                priority=5,
            )
        )
    return items


def _emergency_ratification_items(building_id: int) -> list[ActionItem]:
    items = []
    open_auth = EmergencyAuthorization.objects.filter(
        work_order__case__building_id=building_id,
        ratification__isnull=True,
    ).order_by("ratification_deadline")[:30]
    for auth in open_auth:
        items.append(
            ActionItem(
                kind="emergency_ratification",
                title="Emergency ratification",
                summary=f"Authorization #{auth.pk} deadline {auth.ratification_deadline}",
                target_type="EmergencyAuthorization",
                target_id=auth.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": auth.work_order_id}),
                priority=5,
            )
        )
    return items


def _work_acceptance_items(building_id: int) -> list[ActionItem]:
    items = []
    qs = WorkOrder.objects.filter(
        case__building_id=building_id,
        status=WorkOrder.Status.AWAITING_ACCEPTANCE,
    ).order_by("completed_at")[:40]
    for wo in qs:
        items.append(
            ActionItem(
                kind="work_acceptance",
                title="Work acceptance",
                summary=f"Work order #{wo.pk} awaiting acceptance",
                target_type="WorkOrder",
                target_id=wo.pk,
                url=reverse("web:work-order-detail", kwargs={"pk": wo.pk}),
                priority=18,
            )
        )
    return items


def _payment_record_items(building_id: int) -> list[ActionItem]:
    items = []
    qs = (
        AcceptanceRecord.objects.filter(
            work_order__case__building_id=building_id,
            payment__isnull=True,
        )
        .select_related("work_order")
        .order_by("accepted_at")[:40]
    )
    for acceptance in qs:
        items.append(
            ActionItem(
                kind="payment_record",
                title="Record payment",
                summary=f"Work order #{acceptance.work_order_id} · {acceptance.actual_cost_vnd} VND",
                target_type="AcceptanceRecord",
                target_id=acceptance.pk,
                url=reverse("web:payment-detail", kwargs={"pk": acceptance.pk}),
                priority=16,
            )
        )
    return items


def _payment_verify_items(building_id: int) -> list[ActionItem]:
    items = []
    qs = (
        PaymentEvidence.objects.filter(
            acceptance__work_order__case__building_id=building_id,
            verification__isnull=True,
        )
        .select_related("acceptance")
        .order_by("recorded_at")[:40]
    )
    for payment in qs:
        items.append(
            ActionItem(
                kind="payment_verification",
                title="Payment verification",
                summary=f"Payment #{payment.pk} · {payment.amount_vnd} VND",
                target_type="PaymentEvidence",
                target_id=payment.pk,
                url=reverse("web:payment-detail", kwargs={"pk": payment.pk}),
                priority=14,
            )
        )
    return items


def _pending_publication_items(building_id: int) -> list[ActionItem]:
    items = []
    # Verified payments without published ledger
    verified = (
        PaymentVerification.objects.filter(
            decision=PaymentVerification.Decision.VERIFIED,
            payment__acceptance__work_order__case__building_id=building_id,
        )
        .exclude(
            payment__acceptance__work_order__proposal__published_ledger_entry__isnull=False
        )
        .select_related("payment__acceptance__work_order__proposal")
        .order_by("verified_at")[:40]
    )
    for verification in verified:
        proposal = getattr(
            verification.payment.acceptance.work_order, "proposal", None
        )
        if proposal is None:
            continue
        if hasattr(proposal, "published_ledger_entry"):
            continue
        items.append(
            ActionItem(
                kind="pending_publication",
                title="Pending publication",
                summary=f"Proposal #{proposal.pk} ready to publish",
                target_type="Proposal",
                target_id=proposal.pk,
                url=reverse("web:proposal-detail", kwargs={"pk": proposal.pk}),
                priority=17,
            )
        )
    # Snapshots waiting finalize (CONFIRMED outbox)
    snaps = PublicationSnapshot.objects.filter(
        proposal__work_order__case__building_id=building_id,
        outbox_event__status=BlockchainOutboxEvent.Status.CONFIRMED,
    ).exclude(
        pk__in=PublishedLedgerEntry.objects.values("snapshot_id")
    ).order_by("pk")[:20]
    for snap in snaps:
        items.append(
            ActionItem(
                kind="pending_publication",
                title="Pending publication",
                summary=f"Snapshot #{snap.pk} confirmed — finalize pending",
                target_type="PublicationSnapshot",
                target_id=snap.pk,
                url=reverse("web:proposal-detail", kwargs={"pk": snap.proposal_id}),
                priority=17,
            )
        )
    return items


def _correction_review_items(membership, building_id: int) -> list[ActionItem]:
    items = []
    corrections = (
        Correction.objects.filter(
            original_entry__case__building_id=building_id,
        )
        .prefetch_related("decisions")
        .order_by("-created_at")[:40]
    )
    stage = None
    if membership.organization.kind == Organization.Kind.BOARD:
        stage = CorrectionDecision.Stage.BOARD
    elif membership.organization.kind == Organization.Kind.RESIDENT_REP:
        stage = CorrectionDecision.Stage.RESIDENT_REP

    for correction in corrections:
        if correction.status in {"PUBLISHED", "REJECTED"}:
            continue
        if stage and _has(membership, CORRECTION_APPROVE):
            decided = any(d.stage == stage for d in correction.decisions.all())
            if decided:
                continue
            if stage == CorrectionDecision.Stage.RESIDENT_REP:
                board_ok = any(
                    d.stage == CorrectionDecision.Stage.BOARD
                    and d.decision == CorrectionDecision.Decision.APPROVE
                    for d in correction.decisions.all()
                )
                if not board_ok:
                    continue
        items.append(
            ActionItem(
                kind="correction_review",
                title="Correction review",
                summary=f"Correction #{correction.pk} · {correction.status}",
                target_type="Correction",
                target_id=correction.pk,
                url=reverse("web:proposal-detail", kwargs={"pk": correction.original_entry.proposal_id})
                if correction.original_entry.proposal_id
                else reverse("web:action-inbox"),
                priority=19,
            )
        )
    return items


def _integrity_mismatch_items(building_id: int) -> list[ActionItem]:
    items = []
    latest_mismatch = (
        VerificationObservation.objects.filter(
            published_entry__case__building_id=building_id,
            result=VerificationObservation.Result.MISMATCH,
        )
        .order_by("-observed_at")[:30]
    )
    seen_entries = set()
    for obs in latest_mismatch:
        if obs.published_entry_id in seen_entries:
            continue
        # Only surface if latest observation for entry is still mismatch
        latest = (
            VerificationObservation.objects.filter(
                published_entry_id=obs.published_entry_id
            )
            .order_by("-observed_at", "-pk")
            .first()
        )
        if latest is None or latest.result != VerificationObservation.Result.MISMATCH:
            continue
        seen_entries.add(obs.published_entry_id)
        items.append(
            ActionItem(
                kind="integrity_mismatch",
                title="Integrity mismatch",
                summary=f"Ledger entry #{obs.published_entry_id}",
                target_type="PublishedLedgerEntry",
                target_id=obs.published_entry_id,
                url=reverse("web:audit-search")
                + f"?entry={obs.published_entry_id}",
                priority=8,
            )
        )
    return items


def _failed_outbox_items(building_id: int) -> list[ActionItem]:
    items = []
    # Outbox rows linked to wallets whose membership is in this building.
    qs = BlockchainOutboxEvent.objects.filter(
        status=BlockchainOutboxEvent.Status.FAILED,
        signer_wallet__membership__organization__building_id=building_id,
    ).order_by("-updated_at")[:30]
    for event in qs:
        items.append(
            ActionItem(
                kind="failed_outbox",
                title="Failed outbox",
                summary=f"Event {event.event_id[:18]}… · {event.last_error[:80]}",
                target_type="BlockchainOutboxEvent",
                target_id=event.pk,
                url=reverse("web:audit-search") + f"?outbox={event.pk}",
                priority=9,
            )
        )
    return items


def _quarantined_upload_items(building_id: int, membership) -> list[ActionItem]:
    items = []
    # Quarantined uploads by users in this building (uploader membership or occupancy).
    qs = QuarantinedUpload.objects.filter(
        Q(uploader__organizationmembership__organization__building_id=building_id)
        | Q(uploader__residentoccupancy__unit__building_id=building_id)
    ).distinct().order_by("-created_at")[:20]
    for upload in qs:
        items.append(
            ActionItem(
                kind="quarantined_upload",
                title="Quarantined upload",
                summary=f"{upload.filename} · {upload.reason}",
                target_type="QuarantinedUpload",
                target_id=upload.pk,
                url=reverse("web:action-inbox"),
                priority=12,
            )
        )
    return items
