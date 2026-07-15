"""Building-scoped read selectors shared by web templates and the future API.

Selectors are the single query path for tenant-scoped reads (spec 2.3, layer 2).
Every function takes an explicit building_id; ownership-scoped selectors take
the owning user. Bodies are moved verbatim from lamto.web.views.resident.
"""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from lamto.evidence.models import SETTLED_STATUSES, evidence_level
from lamto.finance.fund import _finalized_posting_q, _source_verified_q
from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry


def published_ledger_entries(building_id):
    """Resident-visible published ledger entries for one building, newest first."""
    return (
        PublishedLedgerEntry.objects.filter(
            case__building_id=building_id,
            snapshot__outbox_event__status__in=SETTLED_STATUSES,
        )
        .select_related(
            "snapshot",
            "snapshot__outbox_event",
            "work_order",
            "case",
            "proposal",
            "proposal__current_version",
            "payment",
            "payment__verification",
            "payment__verification__membership__user",
        )
        .order_by("-published_at", "-pk")
    )


def published_ledger_entry_for_proof(building_id, pk):
    """One settled published entry with relations needed by ``ledger_entry_proof``.

    Extends the list selector with acceptance/redacted-doc/payment event joins
    and corrections prefetch so detail assembly avoids obvious extra queries.
    """
    return (
        published_ledger_entries(building_id)
        .filter(pk=pk)
        .select_related(
            "work_order__acceptance",
            "work_order__acceptance__invoice_redacted",
            "work_order__acceptance__acceptance_redacted",
            "payment__proof_redacted",
            "payment__outbox_event",
            "payment__verification__outbox_event",
        )
        .prefetch_related("corrections")
        .first()
    )


def verified_fund_entries(building_id):
    """Fund rows held to the same verified/finalized bar as fund_balance(verified_only=True)."""
    return MaintenanceFundEntry.objects.filter(fund__building_id=building_id).filter(
        _source_verified_q() | _finalized_posting_q()
    )


def fund_period_flows(building_id, *, days=30):
    """(inflows, outflows) of verified entries in the trailing period, integer VND."""
    since = timezone.now() - timedelta(days=days)
    fund_entries = verified_fund_entries(building_id).filter(recorded_at__gte=since)
    inflows = (
        fund_entries.filter(
            entry_type__in=[
                MaintenanceFundEntry.EntryType.OPENING_BALANCE,
                MaintenanceFundEntry.EntryType.INFLOW,
            ]
        ).aggregate(total=Sum("amount_vnd"))["total"]
        or 0
    )
    outflows = (
        fund_entries.filter(
            entry_type__in=[
                MaintenanceFundEntry.EntryType.OUTFLOW,
                MaintenanceFundEntry.EntryType.REVERSAL,
                MaintenanceFundEntry.EntryType.REPLACEMENT,
            ]
        ).aggregate(total=Sum("amount_vnd"))["total"]
        or 0
    )
    return int(inflows), int(outflows)


def ledger_entry_proof(entry):
    """Detail assembly for one published entry, shared by the resident web
    template and the API (spec 3.1: one query path, one set of gates).
    """
    payload = entry.snapshot.resident_payload or {}
    version = entry.proposal.current_version
    verification = getattr(entry.payment, "verification", None)
    redacted_docs = []
    acceptance = getattr(entry.work_order, "acceptance", None)
    if acceptance is not None:
        for label, version_obj in (
            ("Invoice (redacted)", acceptance.invoice_redacted),
            ("Acceptance report (redacted)", acceptance.acceptance_redacted),
        ):
            if version_obj is not None:
                redacted_docs.append(
                    {
                        "label": label,
                        "filename": version_obj.filename,
                        "sha256": version_obj.sha256,
                    }
                )
    proof_redacted = entry.payment.proof_redacted
    if proof_redacted is not None:
        redacted_docs.append(
            {
                "label": "Payment proof (redacted)",
                "filename": proof_redacted.filename,
                "sha256": proof_redacted.sha256,
            }
        )
    events = [
        event
        for event in (
            entry.snapshot.outbox_event,
            getattr(verification, "outbox_event", None) if verification else None,
            entry.payment.outbox_event,
        )
        if event is not None
    ]
    return {
        "payload": payload,
        "proposed_amount": (
            version.amount_vnd
            if version is not None
            else payload.get("proposed_amount_vnd")
        ),
        "verification": verification,
        "redacted_docs": redacted_docs,
        "corrections": [
            correction
            for correction in entry.corrections.all()
            if correction.is_resident_visible
        ],
        "events": events,
        "transaction_ids": [
            event.transaction_hash for event in events if event.transaction_hash
        ],
        "emergency": payload.get("emergency"),
        "evidence_level": evidence_level(entry.snapshot.outbox_event.status),
    }


def pending_fund_verification_entries(building_id):
    """Source fund entries still awaiting verification (spec 4.3.2).

    Distinct from verified_fund_entries — never reuse that selector here.
    Source types only; rows with a verification relation are excluded.
    """
    from lamto.finance.fund import SOURCE_ENTRY_TYPES

    return (
        MaintenanceFundEntry.objects.filter(
            fund__building_id=building_id,
            entry_type__in=SOURCE_ENTRY_TYPES,
            verification__isnull=True,
        )
        .select_related("recorder", "outbox_event")
        .order_by("-recorded_at", "-pk")
    )


def pending_reconciliation_proposals(building_id):
    """Staff reconciliation aid: publication-eligible but not yet published.

    Mirrors settled verification/publication eligibility used by
    prepare_publication — not merely payment.decision == VERIFIED:
    - payment verification decision VERIFIED
    - payment external_status COMPLETED
    - proposal has current_version; work order not drill
    - no PublishedLedgerEntry and no PublicationSnapshot yet
    - prerequisite outbox events settled (proposal version, board+rep
      approvals for NORMAL mode, acceptance, payment, verification)
    """
    from lamto.accounts.models import Organization
    from lamto.evidence.models import SETTLED_STATUSES
    from lamto.finance.models import (
        ApprovalDecision,
        PaymentEvidence,
        PaymentVerification,
        Proposal,
        PublicationSnapshot,
        PublishedLedgerEntry,
    )

    published_proposal_ids = PublishedLedgerEntry.objects.filter(
        case__building_id=building_id, proposal__isnull=False
    ).values("proposal_id")
    snapshotted_ids = PublicationSnapshot.objects.filter(
        proposal__work_order__case__building_id=building_id
    ).values("proposal_id")

    qs = (
        Proposal.objects.filter(
            work_order__case__building_id=building_id,
            work_order__drill=False,
            current_version__isnull=False,
            work_order__acceptance__payment__verification__decision=PaymentVerification.Decision.VERIFIED,
            work_order__acceptance__payment__external_status=PaymentEvidence.ExternalStatus.COMPLETED,
            current_version__outbox_event__status__in=SETTLED_STATUSES,
            work_order__acceptance__outbox_event__status__in=SETTLED_STATUSES,
            work_order__acceptance__payment__outbox_event__status__in=SETTLED_STATUSES,
            work_order__acceptance__payment__verification__outbox_event__status__in=SETTLED_STATUSES,
        )
        .exclude(pk__in=published_proposal_ids)
        .exclude(pk__in=snapshotted_ids)
        .select_related("current_version", "work_order")
        .prefetch_related(
            "current_version__approval_decisions__outbox_event",
            "current_version__approval_decisions__membership__organization",
        )
        .order_by("-created_at")
    )
    eligible = []
    for proposal in qs:
        if proposal.mode == Proposal.Mode.NORMAL:
            approvals = list(proposal.current_version.approval_decisions.all())
            board = next(
                (
                    a
                    for a in approvals
                    if a.decision == ApprovalDecision.Decision.APPROVE
                    and a.membership.organization.kind == Organization.Kind.BOARD
                    and a.outbox_event_id
                    and a.outbox_event.status in SETTLED_STATUSES
                ),
                None,
            )
            rep = next(
                (
                    a
                    for a in approvals
                    if a.decision == ApprovalDecision.Decision.APPROVE
                    and a.membership.organization.kind == Organization.Kind.RESIDENT_REP
                    and a.outbox_event_id
                    and a.outbox_event.status in SETTLED_STATUSES
                ),
                None,
            )
            if board is None or rep is None:
                continue
        eligible.append(proposal)
    return eligible

