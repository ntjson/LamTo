from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from lamto.accounts.security import require_recent_auth
from lamto.documents.models import Document
from lamto.finance.models import Proposal, Settlement
from lamto.finance.settlements import record_acknowledgement, record_transfer
from lamto.web.forms.staff import RecordSettlementAcknowledgementForm, RecordSettlementTransferForm
from lamto.web.staff import require_management_context, staff_context
from lamto.web.staff_signing import document_pair_options, new_event_id, selected_pair


def _context(request, membership, memberships, **extra):
    return staff_context(request, membership, memberships, nav_active="finance", finance_active="settlements", **extra)


@login_required
def settlement_list(request):
    membership, memberships = require_management_context(request)
    settlements = Settlement.objects.filter(proposal__building_id=membership.building_id).select_related("proposal", "outbox_event")
    pending = Proposal.objects.filter(building_id=membership.building_id, status=Proposal.Status.COMPLETED, settlement__isnull=True)
    return render(request, "web/staff/settlement_detail.html", _context(request, membership, memberships, settlements=settlements, pending=pending, list_mode=True))


@login_required
@require_http_methods(["GET", "POST"])
def settlement_record_transfer(request, pk):
    membership, memberships = require_management_context(request)
    proposal = get_object_or_404(Proposal, pk=pk, building_id=membership.building_id)
    options = document_pair_options(membership.building_id, Document.Kind.PAYMENT_PROOF)
    form = RecordSettlementTransferForm(request.POST or None, proof_choices=[(value, label) for value, label, _, _ in options])
    if request.method == "POST" and form.is_valid():
        require_recent_auth(request)
        pair = selected_pair(options, form.cleaned_data["proof_pair"])
        if pair is None:
            form.add_error("proof_pair", "Selected evidence is no longer available.")
        else:
            try:
                settlement = record_transfer(proposal, membership, transfer_original=pair[0], transfer_redacted=pair[1], **{key: form.cleaned_data[key] for key in ("amount_vnd", "payee_name", "bank_reference")})
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Transfer evidence recorded.")
                return redirect("web:settlement-detail", pk=settlement.pk)
    return render(request, "web/staff/settlement_detail.html", _context(request, membership, memberships, proposal=proposal, transfer_form=form, transfer_mode=True))


@login_required
@require_http_methods(["GET", "POST"])
def settlement_record_ack(request, pk):
    membership, memberships = require_management_context(request)
    settlement = get_object_or_404(Settlement, pk=pk, proposal__building_id=membership.building_id)
    options = document_pair_options(membership.building_id, Document.Kind.PAYMENT_PROOF)
    initial = {"event_id": new_event_id()}
    form = RecordSettlementAcknowledgementForm(request.POST or None, initial=initial, proof_choices=[(value, label) for value, label, _, _ in options])
    if request.method == "POST" and form.is_valid():
        require_recent_auth(request)
        pair = selected_pair(options, form.cleaned_data["proof_pair"])
        if pair is None:
            form.add_error("proof_pair", "Selected evidence is no longer available.")
        else:
            try:
                record_acknowledgement(settlement, membership, ack_original=pair[0], ack_redacted=pair[1], event_id=form.cleaned_data["event_id"])
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Acknowledgement recorded; settlement anchored.")
                return redirect("web:settlement-detail", pk=settlement.pk)
    return render(request, "web/staff/settlement_detail.html", _context(request, membership, memberships, settlement=settlement, ack_form=form, ack_mode=True))


@login_required
def settlement_detail(request, pk):
    membership, memberships = require_management_context(request)
    settlement = get_object_or_404(Settlement.objects.select_related("proposal", "outbox_event", "transfer_original", "transfer_redacted", "ack_original", "ack_redacted"), pk=pk, proposal__building_id=membership.building_id)
    return render(request, "web/staff/settlement_detail.html", _context(request, membership, memberships, settlement=settlement))
