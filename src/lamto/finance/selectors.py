"""Building-scoped read selectors shared by web templates and the future API.

Selectors are the single query path for tenant-scoped reads (spec 2.3, layer 2).
Every function takes an explicit building_id; ownership-scoped selectors take
the owning user. Bodies are moved verbatim from lamto.web.views.resident.
"""

from datetime import date, timedelta

from django.db.models import Exists, OuterRef, Prefetch, Sum
from django.utils import timezone

from lamto.evidence.models import SETTLED_STATUSES, evidence_level
from lamto.finance.fund import _finalized_posting_q, _source_verified_q
from lamto.finance.models import (
    MaintenanceFundEntry,
    Proposal,
    ProposalVersion,
    PublishedLedgerEntry,
)
from lamto.maintenance.models import CompletionRating, WorkUpdate


def resident_proposals(building_id, user):
    """Published proposal records with the complete resident detail graph."""
    versions = ProposalVersion.objects.select_related("outbox_event").prefetch_related(
        "quotations"
    ).order_by("number", "pk")
    updates = WorkUpdate.objects.order_by("created_at", "pk")
    return (
        Proposal.objects.filter(building_id=building_id)
        .exclude(status=Proposal.Status.DRAFT)
        .select_related("current_version", "case", "settlement")
        .prefetch_related(
            Prefetch("versions", queryset=versions),
            Prefetch("updates", queryset=updates),
            Prefetch("case__updates", queryset=updates),
        )
        .annotate(
            has_current_user_rating=Exists(
                CompletionRating.objects.filter(
                    resident=user,
                    proposal_id=OuterRef("pk"),
                )
            )
        )
        .order_by("-created_at", "-pk")
    )


def published_ledger_entries(building_id):
    """Resident-visible published ledger entries for one building, newest first."""
    return (
        PublishedLedgerEntry.objects.filter(
            proposal__building_id=building_id,
            proposal__current_version__outbox_event__status__in=SETTLED_STATUSES,
            settlement__outbox_event__status__in=SETTLED_STATUSES,
        )
        .select_related(
            "case",
            "case__decision__report",
            "proposal",
            "proposal__current_version",
            "settlement",
            "settlement__outbox_event",
        )
        .order_by("-published_at", "-pk")
    )


def published_ledger_entry_for_proof(building_id, pk):
    """One settled published entry with relations needed by ``ledger_entry_proof``.

    Extends the list selector with settlement document/event joins
    so detail assembly avoids obvious extra queries.
    """
    return (
        published_ledger_entries(building_id)
        .filter(pk=pk)
        .select_related(
            "case__decision__report",
            "settlement__transfer__document",
            "settlement__outbox_event",
            "proposal__current_version",
            "proposal__decided_by__user",
        )
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


FUND_SERIES_RANGE_KEYS = ("30d", "6m", "12m")


def fund_series_from_entries(entries, *, range_key, today):
    """Pure bucketing core for fund_series.

    entries iterates (recorded_at aware-datetime, entry_type, amount_vnd).
    Buckets by the Asia/Ho_Chi_Minh calendar day of recorded_at; stored signs
    classify amounts (positive inflow, negative outflow), so balance is a plain
    sum.
    """
    if range_key not in FUND_SERIES_RANGE_KEYS:
        raise ValueError(f"range_key must be one of {FUND_SERIES_RANGE_KEYS}")
    if range_key == "30d":
        starts = [today - timedelta(days=offset) for offset in range(29, -1, -1)]

        def bucket_of(day):
            return day
    else:
        months = 6 if range_key == "6m" else 12
        year, month = today.year, today.month
        starts = []
        for _ in range(months):
            starts.append(date(year, month, 1))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        starts.reverse()

        def bucket_of(day):
            return day.replace(day=1)

    window_start = starts[0]
    flows = {start: [0, 0] for start in starts}
    balance = 0  # seeded with everything before the window
    for recorded_at, _entry_type, amount_vnd in entries:
        day = timezone.localtime(recorded_at).date()
        if day < window_start:
            balance += amount_vnd
            continue
        slot = flows.get(bucket_of(day))
        if slot is None:
            continue  # future-dated rows fall outside the chart window
        slot[0 if amount_vnd > 0 else 1] += amount_vnd
    series = []
    for start in starts:
        inflows, outflows = flows[start]
        balance += inflows + outflows
        series.append(
            {
                "period_start": start,
                "inflows_vnd": inflows,
                "outflows_vnd": outflows,
                "balance_vnd": balance,
            }
        )
    return series


def fund_series(building_id, *, range_key):
    """Chart rows for the fund pages (spec 2026-07-20-fund-balance-chart).

    Last point's balance_vnd equals fund_balance(verified_only=True).
    """
    rows = verified_fund_entries(building_id).values_list(
        "recorded_at", "entry_type", "amount_vnd"
    )
    # ponytail: Python-side bucketing; funds have few entries. Switch to
    # TruncDay/TruncMonth aggregates if a fund ever nears ~10k rows.
    return fund_series_from_entries(
        rows, range_key=range_key, today=timezone.localdate()
    )


def fund_month_calendar_from_entries(entries, *, today):
    """Pure core for fund_month_calendar: one month of daily flows as weeks.

    entries iterates (recorded_at aware-datetime, entry_type, amount_vnd), the
    same rows as fund_series. Weeks run Monday to Sunday; days outside the
    month are None. ``level`` (0-4) ranks a day's outflow against the month's
    largest, so the grid shades where the money went.
    """
    first = today.replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    flows = {}
    for recorded_at, _entry_type, amount_vnd in entries:
        day = timezone.localtime(recorded_at).date()
        if first <= day < next_month:
            slot = flows.setdefault(day, [0, 0])
            slot[0 if amount_vnd > 0 else 1] += amount_vnd
    peak = max((-out for _in, out in flows.values()), default=0)
    cells = [None] * first.weekday()
    day = first
    while day < next_month:
        inflows, outflows = flows.get(day, (0, 0))
        spent = -outflows
        cells.append(
            {
                "date": day,
                "day": day.day,
                "inflows_vnd": inflows,
                "outflows_vnd": outflows,
                "level": 0 if not spent else max(1, -(-4 * spent // peak)),
                "is_today": day == today,
                "is_future": day > today,
            }
        )
        day += timedelta(days=1)
    cells.extend([None] * (-len(cells) % 7))
    spent_days = sorted(
        (cell for cell in cells if cell and cell["outflows_vnd"]),
        key=lambda cell: (cell["outflows_vnd"], cell["date"]),
    )
    return {
        "month": first,
        "top_days": spent_days[:3],
        "weeks": [cells[i : i + 7] for i in range(0, len(cells), 7)],
        "inflows_vnd": sum(slot[0] for slot in flows.values()),
        "outflows_vnd": sum(slot[1] for slot in flows.values()),
    }


def fund_month_calendar(building_id):
    """Current month's verified fund flows by day (same rows as fund_series)."""
    rows = verified_fund_entries(building_id).values_list(
        "recorded_at", "entry_type", "amount_vnd"
    )
    return fund_month_calendar_from_entries(rows, today=timezone.localdate())


def ledger_story_fields(entry):
    """Resident-visible plain-language story for §6.3(6).

    Prefer the latest case progress narrative; fall back to report text /
    case category. Shared by the list and detail serializers so both wire
    the same ``what_was_fixed`` value.
    """
    # ponytail: one updates query per entry on the 20-row list page;
    # prefetch with a window function if ledger pages ever feel slow.
    case = entry.case
    work = (
        case.updates.order_by("-created_at", "-pk").first()
        if case
        else entry.proposal.updates.order_by("-created_at", "-pk").first()
    )
    report = None
    decision = getattr(case, "decision", None) if case else None
    if decision is not None:
        report = getattr(decision, "report", None)

    result = (getattr(work, "result", None) or "").strip()
    cause = (getattr(work, "cause", None) or "").strip()
    report_text = (getattr(report, "text", None) or "").strip() if report else ""
    category = (getattr(case, "category", None) or "").strip()
    purpose = (getattr(entry.proposal.current_version, "purpose", None) or "").strip()
    what_was_fixed = result or report_text or category or purpose
    why = cause or category or purpose

    return {
        "what_was_fixed": what_was_fixed,
        "why": why,
    }


def proceed_decision(proposal):
    """Who decided to proceed with ``proposal``, and when; None when nobody did.

    A decision to close the proposal as not proceeding also records a decider,
    but it is not a Proceed decision, so it is never reported as one.
    """
    if (
        proposal is None
        or proposal.decided_by_id is None
        or proposal.status == Proposal.Status.NOT_PROCEEDING
    ):
        return None
    return {
        "decided_by": proposal.decided_by.user.display_name,
        "decided_at": proposal.decided_at,
    }


def ledger_entry_proof(entry):
    """Detail assembly for one published entry, shared by the resident web
    template and the API (spec 3.1: one query path, one set of gates).
    """
    payload = entry.resident_payload or {}
    version = entry.proposal.current_version
    docs = []
    transfer = entry.settlement.transfer
    if transfer is not None:
        docs.append(
            {
                "kind": transfer.document.kind,
                "content_type": transfer.content_type,
                "filename": transfer.filename,
                "sha256": transfer.sha256,
                "version_id": transfer.pk,
            }
        )
    proposal_event = version.outbox_event if version else None
    settlement_event = entry.settlement.outbox_event
    events = [event for event in (proposal_event, settlement_event) if event]
    anchor = lambda event: {
        "event_id": event.event_id,
        "payload_hash": event.payload_hash,
        "evidence_level": evidence_level(event.status),
    }
    story = ledger_story_fields(entry)
    return {
        "payload": payload,
        "proposed_amount": (
            version.amount_vnd
            if version is not None
            else payload.get("proposed_amount_vnd")
        ),
        "verification": None,
        "proceed_decision": proceed_decision(entry.proposal),
        "docs": docs,
        "events": events,
        "transaction_ids": [
            event.transaction_hash for event in events if event.transaction_hash
        ],
        "evidence_level": evidence_level(settlement_event.status),
        "proposal_version": anchor(proposal_event),
        "settlement": anchor(settlement_event),
        "what_was_fixed": story["what_was_fixed"],
        "why": story["why"],
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
        .select_related("recorder")
        .order_by("-recorded_at", "-pk")
    )


def pending_reconciliation_proposals(building_id):
    """Staff reconciliation aid: publication-eligible but not yet published.

    Mirrors settlement-ledger eligibility:
    - settlement is finalized
    - proposal has current_version
    - no PublishedLedgerEntry yet
    - prerequisite outbox events settled
    """
    from lamto.evidence.models import SETTLED_STATUSES
    from lamto.finance.models import (
        Proposal,
        PublishedLedgerEntry,
    )
    published_proposal_ids = PublishedLedgerEntry.objects.filter(
        proposal__building_id=building_id, proposal__isnull=False
    ).values("proposal_id")

    qs = (
        Proposal.objects.filter(
            building_id=building_id,
            current_version__isnull=False,
            settlement__settled_at__isnull=False,
            settlement__outbox_event__status__in=SETTLED_STATUSES,
            current_version__outbox_event__status__in=SETTLED_STATUSES,
        )
        .exclude(pk__in=published_proposal_ids)
        .select_related(
            "current_version",
            "case",
            "settlement",
        )
        .order_by("-created_at")
    )
    return list(qs)
