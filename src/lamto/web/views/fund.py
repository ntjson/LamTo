"""Fund ops workspace: entries list, balance, source recording + verification."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.capabilities import FUND_RECORD, FUND_VERIFY
from lamto.finance.fund import fund_balance
from lamto.finance.models import MaintenanceFund
from lamto.finance.selectors import (
    fund_period_flows,
    pending_fund_verification_entries,
    pending_reconciliation_proposals,
    verified_fund_entries,
)
from lamto.web.staff import capabilities_for, resolve_active_membership, staff_context


def _require_fund_access(request):
    from lamto.accounts.security import require_staff_mfa

    require_staff_mfa(request)
    membership, memberships = resolve_active_membership(request)
    caps = capabilities_for(membership)
    if FUND_RECORD not in caps and FUND_VERIFY not in caps:
        raise PermissionDenied("fund access")
    return membership, memberships, caps


@login_required
@require_GET
def fund_home(request):
    membership, memberships, caps = _require_fund_access(request)
    building_id = membership.organization.building_id
    entries = (
        verified_fund_entries(building_id)
        .select_related("recorder", "verification")
        .order_by("-recorded_at", "-pk")[:100]
    )
    pending_verification = list(pending_fund_verification_entries(building_id)[:50])
    inflows, outflows = fund_period_flows(building_id, days=30)
    pending = pending_reconciliation_proposals(building_id)[:50]
    return render(
        request,
        "web/staff/fund_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="fund",
            list_mode=True,
            entries=entries,
            pending_verification=pending_verification,
            balance_vnd=fund_balance(building_id, verified_only=True),
            period_inflows=inflows,
            period_outflows=outflows,
            pending=pending,
            fund_exists=MaintenanceFund.objects.filter(building_id=building_id).exists(),
            can_record=FUND_RECORD in caps,
            can_verify=FUND_VERIFY in caps,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def fund_record(request):
    """Placeholder route so fund_home template reverse works; Task 4 implements."""
    raise Http404("Fund record not implemented yet")


@login_required
@require_http_methods(["GET", "POST"])
def fund_verify(request, pk):
    """Placeholder route so fund_home template reverse works; Task 5 implements."""
    raise Http404("Fund verify not implemented yet")

