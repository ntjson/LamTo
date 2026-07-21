"""Management action inbox queries.

The inbox is authoritative for staff work; email is a secondary channel.
Callers pass a single building-scoped management membership.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from lamto.accounts.models import ManagementMembership
from lamto.documents.models import QuarantinedUpload
from lamto.evidence.models import BlockchainOutboxEvent, SETTLED_STATUSES
from lamto.finance.models import (
    Settlement,
    Proposal,
    PublishedLedgerEntry,
    VerificationObservation,
)
from lamto.finance.proposals import spending_proposal_cases
from lamto.maintenance.models import (
    IssueReport,
    MaintenanceCase,
    TriageJob,
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
    deadline_at: datetime | None = None
    amount_vnd: int | None = None

    @property
    def deadline_tone(self) -> str:
        from lamto.web.views.staff_common import deadline_tone

        return deadline_tone(self.deadline_at)


def _building_id(membership) -> int:
    return membership.building_id


def action_items_for(membership: ManagementMembership) -> list[ActionItem]:
    """Return every surviving queue for one active management membership."""
    if membership is None or not membership.active:
        return []
    membership = (
        ManagementMembership.objects.select_related("building", "user")
        .filter(pk=membership.pk, active=True)
        .first()
    )
    if membership is None:
        return []

    items: list[ActionItem] = []
    building_id = _building_id(membership)
    now = timezone.now()

    items.extend(_manual_triage_items(building_id))
    items.extend(_review_queue_items(building_id))
    items.extend(_deadline_risk_items(building_id))
    items.extend(_in_progress_case_items(building_id))
    items.extend(_proposal_create_candidates(building_id))
    items.extend(_proposal_decision_items(building_id))
    items.extend(_settlement_transfer_items(building_id))
    items.extend(_settlement_ack_items(building_id))
    items.extend(_integrity_mismatch_items(building_id))
    items.extend(_failed_outbox_items(building_id))
    items.extend(_quarantined_upload_items(building_id, membership))

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
            status__in=[IssueReport.Status.SUBMITTED, IssueReport.Status.IN_REVIEW],
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
                url=reverse("web:staff-report-detail", kwargs={"pk": report.pk}),
                priority=10,
            )
        )
    return items


def _review_queue_items(building_id: int) -> list[ActionItem]:
    return [
        ActionItem(
            kind="review_report", title=f"Review request #{report.pk}",
            summary=report.text[:120], target_type="IssueReport", target_id=report.pk,
            url=reverse("web:staff-report-detail", kwargs={"pk": report.pk}), priority=11,
        )
        for report in IssueReport.objects.filter(
            building_id=building_id, status=IssueReport.Status.IN_REVIEW,
            triage_decision__isnull=True,
        ).order_by("created_at")[:20]
    ]


def _deadline_risk_items(building_id: int) -> list[ActionItem]:
    items = []
    horizon = timezone.now() + timedelta(hours=24)
    cases = MaintenanceCase.objects.filter(
        building_id=building_id,
        active=True,
        completed_at__isnull=True,
        deadline_at__lt=horizon,
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
                deadline_at=case.deadline_at,
            )
        )
    return items


def _in_progress_case_items(building_id: int) -> list[ActionItem]:
    return [ActionItem(kind="in_progress_case", title="Case in progress",
                       summary=f"Case #{case.pk} · {case.category}", target_type="MaintenanceCase",
                       target_id=case.pk, url=reverse("web:case-detail", kwargs={"pk": case.pk}),
                       priority=20, deadline_at=case.deadline_at)
            for case in MaintenanceCase.objects.filter(
                building_id=building_id, active=True, completed_at__isnull=True,
                reports__status=IssueReport.Status.IN_PROGRESS).distinct().order_by("deadline_at")[:50]]


def _proposal_create_candidates(building_id: int) -> list[ActionItem]:
    items = []
    qs = spending_proposal_cases().filter(
        building_id=building_id,
        proposal__isnull=True,
    ).distinct().order_by("created_at")[:30]
    for case in qs:
        items.append(
            ActionItem(
                kind="proposal_create",
                title="Create proposal",
                summary=f"Case #{case.pk} needs a spending proposal",
                target_type="MaintenanceCase",
                target_id=case.pk,
                url=reverse("web:proposal-create", kwargs={"pk": case.pk}),
                priority=25,
            )
        )
    return items


def _proposal_decision_items(building_id: int) -> list[ActionItem]:
    return [ActionItem(
        kind="proposal_decision", title="Decide proposal",
        summary=f"Proposal #{proposal.pk} awaits a proceed decision", target_type="Proposal",
        target_id=proposal.pk, url=reverse("web:proposal-detail", kwargs={"pk": proposal.pk}),
        priority=16,
    ) for proposal in Proposal.objects.filter(
        building_id=building_id, status=Proposal.Status.PUBLISHED, decided_at__isnull=True,
    ).order_by("created_at")[:30]]


def _settlement_transfer_items(building_id: int) -> list[ActionItem]:
    return [ActionItem(kind="settlement_transfer", title="Record transfer", summary=f"Proposal #{p.pk}", target_type="Proposal", target_id=p.pk, url=reverse("web:proposal-detail", kwargs={"pk": p.pk}), priority=16, amount_vnd=p.current_version.amount_vnd) for p in Proposal.objects.filter(building_id=building_id, status=Proposal.Status.COMPLETED, settlement__isnull=True).select_related("current_version")[:40]]


def _settlement_ack_items(building_id: int) -> list[ActionItem]:
    return [ActionItem(kind="settlement_ack", title="Record acknowledgement", summary=f"Settlement #{s.pk}", target_type="Settlement", target_id=s.pk, url=reverse("web:settlement-detail", kwargs={"pk": s.pk}), priority=14, amount_vnd=s.amount_vnd) for s in Settlement.objects.filter(proposal__building_id=building_id, settled_at__isnull=True)[:40]]


def _integrity_mismatch_items(building_id: int) -> list[ActionItem]:
    items = []
    latest_mismatch = (
        VerificationObservation.objects.filter(
            published_entry__proposal__building_id=building_id,
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
                url=reverse("web:audit-export")
                + f"?entry={obs.published_entry_id}",
                priority=8,
            )
        )
    return items


def _failed_outbox_items(building_id: int) -> list[ActionItem]:
    items = []
    # Denormalized building on the outbox event is the tenant key (spec 2.2).
    qs = BlockchainOutboxEvent.objects.filter(
        status=BlockchainOutboxEvent.Status.FAILED,
        building_id=building_id,
    ).order_by("-updated_at")[:30]
    for event in qs:
        items.append(
            ActionItem(
                kind="failed_outbox",
                title="Failed outbox",
                summary=f"Event {event.event_id[:18]}… · {event.last_error[:80]}",
                target_type="BlockchainOutboxEvent",
                target_id=event.pk,
                url=reverse("web:audit-export") + f"?outbox={event.pk}",
                priority=9,
            )
        )
    return items


def _quarantined_upload_items(building_id: int, membership) -> list[ActionItem]:
    items = []
    qs = (
        QuarantinedUpload.objects.filter(building_id=building_id)
        .order_by("-created_at")[:20]
    )
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
