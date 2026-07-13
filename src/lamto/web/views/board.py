"""Board workspace: acceptance, payments, emergencies, publication."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.capabilities import (
    EMERGENCY_AUTHORIZE,
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    WORK_ACCEPT,
)
from lamto.audit.services import record_audit
from lamto.documents.models import DocumentVersion
from lamto.finance.models import AcceptanceRecord, PaymentEvidence
from lamto.web.forms.staff import (
    AcceptWorkForm,
    EmergencyAuthorizeForm,
    RecordPaymentForm,
    VerifyPaymentForm,
)
from lamto.web.staff import require_staff_capability, resolve_active_membership, staff_context


@login_required
@require_GET
def payment_list(request):
    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    if PAYMENT_RECORD not in caps and PAYMENT_VERIFY not in caps:
        raise PermissionDenied("payment access")
    building_id = membership.organization.building_id
    pending_record = (
        AcceptanceRecord.objects.filter(
            work_order__case__building_id=building_id,
            payment__isnull=True,
        ).order_by("-accepted_at")[:50]
        if PAYMENT_RECORD in caps
        else []
    )
    pending_verify = (
        PaymentEvidence.objects.filter(
            acceptance__work_order__case__building_id=building_id,
            verification__isnull=True,
        ).order_by("-recorded_at")[:50]
        if PAYMENT_VERIFY in caps
        else []
    )
    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="payments",
            list_mode=True,
            pending_record=pending_record,
            pending_verify=pending_verify,
            can_record=PAYMENT_RECORD in caps,
            can_verify=PAYMENT_VERIFY in caps,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def payment_detail(request, pk):
    """pk is AcceptanceRecord id (record) or PaymentEvidence id (verify)."""
    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    building_id = membership.organization.building_id

    acceptance = AcceptanceRecord.objects.filter(
        pk=pk, work_order__case__building_id=building_id
    ).select_related("work_order", "payment").first()
    payment = None
    if acceptance is None:
        payment = get_object_or_404(
            PaymentEvidence.objects.select_related(
                "acceptance__work_order", "recorder", "verification"
            ),
            pk=pk,
            acceptance__work_order__case__building_id=building_id,
        )
        acceptance = payment.acceptance
    else:
        payment = getattr(acceptance, "payment", None)

    record_form = RecordPaymentForm(request.POST or None) if payment is None else None
    verify_form = VerifyPaymentForm(request.POST or None) if payment is not None else None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "record" and record_form is not None and PAYMENT_RECORD in caps:
            require_staff_capability(request, PAYMENT_RECORD)
            if record_form.is_valid():
                proof_o = DocumentVersion.objects.filter(
                    pk=record_form.cleaned_data["proof_original_id"]
                ).first()
                proof_r = DocumentVersion.objects.filter(
                    pk=record_form.cleaned_data["proof_redacted_id"]
                ).first()
                try:
                    payment = record_form.save(acceptance, membership, proof_o, proof_r)
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        record_form.add_error(None, error)
                    else:
                        raise
                else:
                    messages.success(request, "Payment recorded.")
                    return redirect("web:payment-detail", pk=payment.pk)
        elif action == "verify" and verify_form is not None and PAYMENT_VERIFY in caps:
            require_staff_capability(request, PAYMENT_VERIFY)
            if verify_form.is_valid():
                try:
                    verify_form.save(payment, membership)
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        verify_form.add_error(None, error)
                    else:
                        raise
                else:
                    messages.success(request, "Payment verification recorded.")
                    return redirect("web:payment-detail", pk=payment.pk)

    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="payments",
            list_mode=False,
            acceptance=acceptance,
            payment=payment,
            record_form=record_form if PAYMENT_RECORD in caps else None,
            verify_form=verify_form if PAYMENT_VERIFY in caps else None,
            can_record=PAYMENT_RECORD in caps and payment is None,
            can_verify=PAYMENT_VERIFY in caps
            and payment is not None
            and not hasattr(payment, "verification"),
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def accept_work(request, pk):
    from lamto.maintenance.models import WorkOrder

    membership, memberships = require_staff_capability(request, WORK_ACCEPT)
    work_order = get_object_or_404(
        WorkOrder,
        pk=pk,
        case__building_id=membership.organization.building_id,
    )
    form = AcceptWorkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        docs = {
            "invoice_original": DocumentVersion.objects.filter(
                pk=form.cleaned_data["invoice_original_id"]
            ).first(),
            "invoice_redacted": DocumentVersion.objects.filter(
                pk=form.cleaned_data["invoice_redacted_id"]
            ).first(),
            "acceptance_original": DocumentVersion.objects.filter(
                pk=form.cleaned_data["acceptance_original_id"]
            ).first(),
            "acceptance_redacted": DocumentVersion.objects.filter(
                pk=form.cleaned_data["acceptance_redacted_id"]
            ).first(),
        }
        try:
            form.save(work_order, membership, docs)
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Work accepted.")
            return redirect("web:work-order-detail", pk=work_order.pk)
    return render(
        request,
        "web/staff/work_order_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="work",
            work_order=work_order,
            accept_form=form,
            list_mode=False,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def emergency_authorize(request, pk):
    from lamto.maintenance.models import WorkOrder

    membership, memberships = require_staff_capability(request, EMERGENCY_AUTHORIZE)
    work_order = get_object_or_404(
        WorkOrder,
        pk=pk,
        case__building_id=membership.organization.building_id,
    )
    form = EmergencyAuthorizeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            form.save(work_order, membership)
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Emergency authorized.")
            return redirect("web:work-order-detail", pk=work_order.pk)
    return render(
        request,
        "web/staff/work_order_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="work",
            work_order=work_order,
            emergency_form=form,
            list_mode=False,
        ),
    )
