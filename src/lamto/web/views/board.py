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
from lamto.accounts.security import require_recent_auth, require_staff_mfa
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
@require_http_methods(["POST"])
def payment_record(request):
    """Privileged signed financial action: requires MFA + recent re-auth."""
    require_staff_mfa(request)
    require_recent_auth(request)
    membership, memberships = require_staff_capability(request, PAYMENT_RECORD)
    form = RecordPaymentForm(request.POST)
    if not form.is_valid():
        from django.http import JsonResponse

        return JsonResponse({"errors": form.errors}, status=400)
    acceptance_id = form.cleaned_data.get("acceptance_id") or request.POST.get("acceptance_id")
    acceptance = get_object_or_404(
        AcceptanceRecord,
        pk=acceptance_id,
        work_order__case__building_id=membership.organization.building_id,
    )
    if hasattr(acceptance, "payment") and acceptance.payment is not None:
        raise PermissionDenied("Payment already recorded.")
    proof_o = DocumentVersion.objects.filter(pk=form.cleaned_data["proof_original_id"]).first()
    proof_r = DocumentVersion.objects.filter(pk=form.cleaned_data["proof_redacted_id"]).first()
    try:
        payment = form.save(acceptance, membership, proof_o, proof_r)
    except ValidationError as error:
        from django.http import JsonResponse

        return JsonResponse(
            {
                "errors": error.message_dict
                if hasattr(error, "message_dict")
                else str(error)
            },
            status=400,
        )
    messages.success(request, "Payment recorded.")
    return redirect("web:payment-verify-detail", pk=payment.pk)


@login_required
@require_GET
def payment_list(request):
    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    if PAYMENT_RECORD not in caps and PAYMENT_VERIFY not in caps:
        raise PermissionDenied("payment access")
    building_id = membership.organization.building_id
    status = request.GET.get("status") or ""
    valid_status = status in PaymentEvidence.ExternalStatus.values
    pending_record = (
        AcceptanceRecord.objects.filter(
            work_order__case__building_id=building_id,
            payment__isnull=True,
        ).order_by("-accepted_at")[:50]
        if PAYMENT_RECORD in caps
        else []
    )
    verify_qs = PaymentEvidence.objects.filter(
        acceptance__work_order__case__building_id=building_id,
        verification__isnull=True,
    )
    if valid_status:
        verify_qs = verify_qs.filter(external_status=status)
    pending_verify = (
        verify_qs.order_by("-recorded_at")[:50] if PAYMENT_VERIFY in caps else []
    )
    record_items = [
        {
            "url": f"/s/payments/record/{a.pk}/",
            "title": f"Acceptance #{a.pk} · {a.actual_cost_vnd} VND",
            "status": None,
            "deadline": None,
        }
        for a in pending_record
    ]
    verify_items = [
        {
            "url": f"/s/payments/verify/{p.pk}/",
            "title": f"Payment #{p.pk} · {p.amount_vnd} VND",
            "status": p.get_external_status_display(),
            "deadline": None,
        }
        for p in pending_verify
    ]
    filters = [
        {"label": label, "value": value, "active": valid_status and value == status}
        for value, label in PaymentEvidence.ExternalStatus.choices
    ]
    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            list_mode=True,
            pending_record=pending_record,
            pending_verify=pending_verify,
            record_items=record_items,
            verify_items=verify_items,
            filters=filters,
            filters_active=valid_status,
            filter_param="status",
            can_record=PAYMENT_RECORD in caps,
            can_verify=PAYMENT_VERIFY in caps,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def payment_record_detail(request, pk):
    """Record payment against AcceptanceRecord pk (never PaymentEvidence pk)."""
    membership, memberships = require_staff_capability(request, PAYMENT_RECORD)
    building_id = membership.organization.building_id
    acceptance = get_object_or_404(
        AcceptanceRecord.objects.select_related("work_order", "payment"),
        pk=pk,
        work_order__case__building_id=building_id,
    )
    payment = getattr(acceptance, "payment", None)
    if payment is not None:
        return redirect("web:payment-verify-detail", pk=payment.pk)

    record_form = RecordPaymentForm(request.POST or None)
    if request.method == "POST" and record_form.is_valid():
        require_recent_auth(request)
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
            return redirect("web:payment-verify-detail", pk=payment.pk)

    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            list_mode=False,
            mode="record",
            acceptance=acceptance,
            payment=None,
            record_form=record_form,
            verify_form=None,
            can_record=True,
            can_verify=False,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def payment_verify_detail(request, pk):
    """Verify PaymentEvidence pk (never AcceptanceRecord pk)."""
    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    if PAYMENT_VERIFY not in caps and PAYMENT_RECORD not in caps:
        raise PermissionDenied("payment access")
    building_id = membership.organization.building_id
    payment = get_object_or_404(
        PaymentEvidence.objects.select_related(
            "acceptance__work_order", "recorder", "verification"
        ),
        pk=pk,
        acceptance__work_order__case__building_id=building_id,
    )
    acceptance = payment.acceptance
    verify_form = (
        VerifyPaymentForm(request.POST or None)
        if PAYMENT_VERIFY in caps and not hasattr(payment, "verification")
        else None
    )

    if request.method == "POST" and verify_form is not None and PAYMENT_VERIFY in caps:
        require_staff_capability(request, PAYMENT_VERIFY)
        require_recent_auth(request)
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
                return redirect("web:payment-verify-detail", pk=payment.pk)

    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            list_mode=False,
            mode="verify",
            acceptance=acceptance,
            payment=payment,
            record_form=None,
            verify_form=verify_form,
            can_record=False,
            can_verify=PAYMENT_VERIFY in caps and not hasattr(payment, "verification"),
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
    if request.method == "POST":
        require_recent_auth(request)
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
    if request.method == "POST":
        require_recent_auth(request)
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
