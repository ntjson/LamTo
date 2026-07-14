"""Building-scoped read selectors shared by web templates and the future API.

Selectors are the single query path for tenant-scoped reads (spec 2.3, layer 2).
Every function takes an explicit building_id; ownership-scoped selectors take
the owning user. Bodies are moved verbatim from lamto.web.views.resident.
"""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from lamto.evidence.models import SETTLED_STATUSES
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
