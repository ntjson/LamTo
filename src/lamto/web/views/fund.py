"""Fund ops workspace: entries list, balance, source recording + verification."""

import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.capabilities import FUND_RECORD, FUND_VERIFY
from lamto.accounts.security import require_recent_auth
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.services import utc_rfc3339
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    fund_balance,
    get_or_create_fund,
    record_fund_source,
)
from lamto.finance.models import MaintenanceFund
from lamto.finance.selectors import (
    fund_period_flows,
    pending_fund_verification_entries,
    pending_reconciliation_proposals,
    verified_fund_entries,
)
from lamto.web.forms.staff import RecordFundSourceForm, SignFundSourceForm
from lamto.web.staff import capabilities_for, require_staff_capability, resolve_active_membership, staff_context
from lamto.web.staff_signing import new_event_id, upload_document_pair


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
    """Two-phase record of an opening-balance/inflow fund source (spec 4.3.2)."""
    membership, memberships = require_staff_capability(request, FUND_RECORD)
    building = membership.organization.building
    if request.method == "POST":
        require_recent_auth(request)
    fund = get_or_create_fund(building)

    record_form = RecordFundSourceForm(request.POST or None, request.FILES or None)
    sign_form = None
    typed_data = None
    action = request.POST.get("action") if request.method == "POST" else None

    if action == "prepare" and record_form.is_valid():
        try:
            original, redacted = upload_document_pair(
                building,
                Document.Kind.CONTRACT,
                request.user,
                record_form.cleaned_data["evidence_original"],
                record_form.cleaned_data["evidence_redacted"],
            )
            entry_type = record_form.cleaned_data["entry_type"]
            amount = record_form.cleaned_data["amount_vnd"]
            fund_entry_id = allocate_fund_entry_id()
            timestamp = timezone.now()
            event_id = new_event_id()
            typed = build_fund_source_evidence_typed_data(
                fund,
                membership,
                fund_entry_id,
                entry_type,
                amount,
                original,
                redacted,
                event_id,
                timestamp=timestamp,
            )
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                record_form.add_error(None, error)
            else:
                raise
        else:
            typed_data = json.dumps(typed)
            sign_form = SignFundSourceForm(
                initial={
                    "event_id": event_id,
                    "entry_type": entry_type,
                    "amount_vnd": amount,
                    "evidence_original_id": original.pk,
                    "evidence_redacted_id": redacted.pk,
                    "fund_entry_id": fund_entry_id,
                    "entry_timestamp": utc_rfc3339(timestamp),
                }
            )
    elif action == "submit":
        sign_form = SignFundSourceForm(request.POST)
        if sign_form.is_valid():
            original = get_object_or_404(
                DocumentVersion,
                pk=sign_form.cleaned_data["evidence_original_id"],
                document__building=building,
            )
            redacted = get_object_or_404(
                DocumentVersion,
                pk=sign_form.cleaned_data["evidence_redacted_id"],
                document__building=building,
            )
            timestamp = datetime.fromisoformat(sign_form.cleaned_data["entry_timestamp"])
            try:
                record_fund_source(
                    fund,
                    sign_form.cleaned_data["entry_type"],
                    sign_form.cleaned_data["amount_vnd"],
                    original,
                    redacted,
                    membership,
                    sign_form.cleaned_data["signature"],
                    sign_form.cleaned_data["event_id"],
                    fund_entry_id=sign_form.cleaned_data["fund_entry_id"],
                    timestamp=timestamp,
                )
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    sign_form.add_error(None, error)
                else:
                    raise
            else:
                messages.success(request, "Fund source recorded; awaiting verification.")
                return redirect("web:fund-home")

    return render(
        request,
        "web/staff/fund_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="fund",
            list_mode=False,
            mode="record",
            record_form=record_form,
            sign_form=sign_form,
            typed_data=typed_data,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def fund_verify(request, pk):
    """Placeholder route so fund_home template reverse works; Task 5 implements."""
    raise Http404("Fund verify not implemented yet")
