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
            finance_active="payments",
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
    import json
    from django.utils import timezone

    from lamto.accounts.models import SignerWallet
    from lamto.documents.models import Document
    from lamto.finance.payments import (
        allocate_payment_id,
        build_payment_evidence_typed_data,
    )
    from lamto.web.staff_signing import new_event_id

    membership, memberships = require_staff_capability(request, PAYMENT_RECORD)
    building_id = membership.organization.building_id
    acceptance = get_object_or_404(
        AcceptanceRecord.objects.select_related("work_order", "payment", "outbox_event"),
        pk=pk,
        work_order__case__building_id=building_id,
    )
    payment = getattr(acceptance, "payment", None)
    if payment is not None:
        return redirect("web:payment-verify-detail", pk=payment.pk)

    record_form = RecordPaymentForm(request.POST or None)
    typed_data = None
    expected_signer = ""
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
        except ValidationError as error:
            messages.error(
                request,
                error.messages[0] if getattr(error, "messages", None) else str(error),
            )
        except PermissionDenied as error:
            messages.error(request, str(error) or "Permission denied.")
        else:
            messages.success(request, "Payment recorded.")
            return redirect("web:payment-verify-detail", pk=payment.pk)

    from django.utils.dateparse import parse_datetime
    from lamto.evidence.services import utc_rfc3339

    event_id = new_event_id()
    amount = acceptance.actual_cost_vnd
    bank_ref = "VCB-PILOT-001"
    ext_status = "COMPLETED"
    reason = "Thanh toan chuyen khoan"
    # Pin once for this form render; must be the same value MetaMask signs and
    # record_payment verifies (do not call timezone.now() again on POST).
    completed_at = timezone.now()
    payment_id = None
    proof_o = (
        DocumentVersion.objects.filter(
            document__building_id=building_id,
            document__kind=Document.Kind.PAYMENT_PROOF,
            variant=DocumentVersion.Variant.ORIGINAL,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        )
        .order_by("-pk")
        .first()
    )
    proof_r = (
        DocumentVersion.objects.filter(
            document_id=getattr(proof_o, "document_id", None),
            variant=DocumentVersion.Variant.REDACTED,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        )
        .order_by("-pk")
        .first()
        if proof_o
        else None
    )
    if record_form.is_bound:
        bank_ref = record_form.data.get("bank_reference") or bank_ref
        reason = record_form.data.get("reason") or reason
        ext_status = record_form.data.get("external_status") or ext_status
        try:
            amount = int(record_form.data.get("amount_vnd") or amount)
        except (TypeError, ValueError):
            pass
        try:
            payment_id = int(record_form.data.get("payment_id") or 0) or None
        except (TypeError, ValueError):
            payment_id = None
        proof_o = DocumentVersion.objects.filter(
            pk=record_form.data.get("proof_original_id")
        ).first() or proof_o
        proof_r = DocumentVersion.objects.filter(
            pk=record_form.data.get("proof_redacted_id")
        ).first() or proof_r
        # Reuse pinned timestamp from the signed attempt when re-showing errors.
        raw_ts = (record_form.data.get("completed_at") or "").strip()
        if raw_ts:
            parsed = parse_datetime(raw_ts)
            if parsed is not None:
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.utc)
                completed_at = parsed
        # Keep event_id from the signed form so re-display can still show errors
        # without forcing a new sign mid-debug — new GET still mints a fresh id.
        if request.method == "POST" and record_form.data.get("event_id"):
            event_id = record_form.data.get("event_id").strip() or event_id
    if payment_id is None:
        payment_id = allocate_payment_id()

    record_form = RecordPaymentForm(
        initial={
            "event_id": event_id,
            "reason": reason,
            "bank_reference": bank_ref,
            "amount_vnd": amount,
            "external_status": ext_status,
            "proof_original_id": getattr(proof_o, "pk", None),
            "proof_redacted_id": getattr(proof_r, "pk", None),
            "payment_id": payment_id,
            "completed_at": utc_rfc3339(completed_at),
        }
    )
    if proof_o and proof_r:
        try:
            typed_data = json.dumps(
                build_payment_evidence_typed_data(
                    acceptance,
                    membership,
                    payment_id,
                    bank_ref,
                    amount,
                    ext_status,
                    completed_at,
                    proof_o,
                    proof_r,
                    event_id,
                )
            )
        except (ValidationError, PermissionDenied, ValueError, TypeError):
            typed_data = None
    wallet = (
        SignerWallet.objects.filter(membership=membership, active=True).order_by("pk").first()
    )
    if wallet is not None:
        expected_signer = wallet.address

    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            finance_active="payments",
            list_mode=False,
            mode="record",
            acceptance=acceptance,
            payment=None,
            record_form=record_form,
            verify_form=None,
            can_record=True,
            can_verify=False,
            typed_data=typed_data,
            expected_signer=expected_signer,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def payment_verify_detail(request, pk):
    """Verify PaymentEvidence pk (never AcceptanceRecord pk)."""
    import json

    from lamto.accounts.models import SignerWallet
    from lamto.finance.payments import build_payment_verification_evidence_typed_data
    from lamto.web.staff_signing import new_event_id

    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    if PAYMENT_VERIFY not in caps and PAYMENT_RECORD not in caps:
        raise PermissionDenied("payment access")
    building_id = membership.organization.building_id
    payment = get_object_or_404(
        PaymentEvidence.objects.select_related(
            "acceptance__work_order",
            "recorder",
            "verification",
            "outbox_event",
        ),
        pk=pk,
        acceptance__work_order__case__building_id=building_id,
    )
    acceptance = payment.acceptance
    already = hasattr(payment, "verification") and payment.verification is not None
    can_verify = PAYMENT_VERIFY in caps and not already
    verify_form = VerifyPaymentForm(request.POST or None) if can_verify else None
    typed_data = None
    expected_signer = ""

    if request.method == "POST" and verify_form is not None and can_verify:
        require_staff_capability(request, PAYMENT_VERIFY)
        require_recent_auth(request)
        if verify_form.is_valid():
            try:
                # timestamp defaults to payment.recorded_at — must match typed data below
                verify_form.save(payment, membership)
            except ValidationError as error:
                messages.error(
                    request,
                    error.messages[0] if getattr(error, "messages", None) else str(error),
                )
            except PermissionDenied as error:
                messages.error(request, str(error) or "Permission denied.")
            else:
                messages.success(request, "Payment verification recorded.")
                return redirect("web:payment-verify-detail", pk=payment.pk)

    if can_verify:
        event_id = new_event_id()
        decision = "VERIFIED"
        reason = ""
        if verify_form is not None and verify_form.is_bound:
            decision = (verify_form.data.get("decision") or "VERIFIED").upper()
            if decision not in ("VERIFIED", "REJECTED"):
                decision = "VERIFIED"
            reason = verify_form.data.get("reason") or ""
            if verify_form.data.get("event_id"):
                event_id = verify_form.data.get("event_id").strip() or event_id
        elif request.method == "GET":
            decision = (request.GET.get("decision") or "VERIFIED").upper()
            if decision not in ("VERIFIED", "REJECTED"):
                decision = "VERIFIED"
        # Stable: same default as verify_payment() when timestamp is omitted.
        pin_ts = payment.recorded_at
        verify_form = VerifyPaymentForm(
            initial={
                "event_id": event_id,
                "decision": decision,
                "reason": reason or "Da kiem tra OK",
            }
        )
        try:
            typed_data = json.dumps(
                build_payment_verification_evidence_typed_data(
                    payment,
                    membership,
                    decision,
                    event_id,
                    timestamp=pin_ts,
                )
            )
        except (ValidationError, PermissionDenied, ValueError, TypeError):
            typed_data = None
        wallet = (
            SignerWallet.objects.filter(membership=membership, active=True)
            .order_by("pk")
            .first()
        )
        if wallet is not None:
            expected_signer = wallet.address

    return render(
        request,
        "web/staff/payment_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="finance",
            finance_active="payments",
            list_mode=False,
            mode="verify",
            acceptance=acceptance,
            payment=payment,
            record_form=None,
            verify_form=verify_form,
            can_record=False,
            can_verify=can_verify,
            typed_data=typed_data,
            expected_signer=expected_signer,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def accept_work(request, pk):
    import json

    from lamto.accounts.models import SignerWallet
    from lamto.finance.acceptance import build_acceptance_evidence_typed_data
    from lamto.maintenance.models import WorkOrder
    from lamto.web.staff_signing import new_event_id

    membership, memberships = require_staff_capability(request, WORK_ACCEPT)
    work_order = get_object_or_404(
        WorkOrder,
        pk=pk,
        case__building_id=membership.organization.building_id,
    )
    form = AcceptWorkForm(request.POST or None)
    typed_data = None
    expected_signer = ""
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
        except ValidationError as error:
            messages.error(
                request,
                error.messages[0] if getattr(error, "messages", None) else str(error),
            )
        except PermissionDenied as error:
            messages.error(request, str(error) or "Permission denied.")
        else:
            messages.success(request, "Work accepted.")
            return redirect("web:work-order-detail", pk=work_order.pk)

    # Mint event id + typed data for MetaMask. Prefer POST values; else pilot
    # defaults so the form is fillable without a separate upload UI.
    from lamto.documents.models import Document

    event_id = new_event_id()
    cost = 5_000_000
    reason = "Nghiem thu OK"
    if form.is_bound:
        try:
            cost = int(form.data.get("actual_cost_vnd") or cost)
        except (TypeError, ValueError):
            pass
        reason = (form.data.get("reason") or reason).strip() or reason
        inv_o = DocumentVersion.objects.filter(pk=form.data.get("invoice_original_id")).first()
        inv_r = DocumentVersion.objects.filter(pk=form.data.get("invoice_redacted_id")).first()
        acc_o = DocumentVersion.objects.filter(
            pk=form.data.get("acceptance_original_id")
        ).first()
        acc_r = DocumentVersion.objects.filter(
            pk=form.data.get("acceptance_redacted_id")
        ).first()
    else:
        # Latest clean invoice / acceptance pairs for this building (pilot docs).
        building_id = work_order.case.building_id
        inv_o = (
            DocumentVersion.objects.filter(
                document__building_id=building_id,
                document__kind=Document.Kind.INVOICE,
                variant=DocumentVersion.Variant.ORIGINAL,
                scan_status=DocumentVersion.ScanStatus.CLEAN,
            )
            .order_by("-pk")
            .first()
        )
        inv_r = (
            DocumentVersion.objects.filter(
                document_id=getattr(inv_o, "document_id", None),
                variant=DocumentVersion.Variant.REDACTED,
                scan_status=DocumentVersion.ScanStatus.CLEAN,
            )
            .order_by("-pk")
            .first()
            if inv_o
            else None
        )
        acc_o = (
            DocumentVersion.objects.filter(
                document__building_id=building_id,
                document__kind=Document.Kind.ACCEPTANCE_REPORT,
                variant=DocumentVersion.Variant.ORIGINAL,
                scan_status=DocumentVersion.ScanStatus.CLEAN,
            )
            .order_by("-pk")
            .first()
        )
        acc_r = (
            DocumentVersion.objects.filter(
                document_id=getattr(acc_o, "document_id", None),
                variant=DocumentVersion.Variant.REDACTED,
                scan_status=DocumentVersion.ScanStatus.CLEAN,
            )
            .order_by("-pk")
            .first()
            if acc_o
            else None
        )

    form = AcceptWorkForm(
        initial={
            "event_id": event_id,
            "reason": reason,
            "actual_cost_vnd": cost,
            "invoice_original_id": getattr(inv_o, "pk", None),
            "invoice_redacted_id": getattr(inv_r, "pk", None),
            "acceptance_original_id": getattr(acc_o, "pk", None),
            "acceptance_redacted_id": getattr(acc_r, "pk", None),
        }
    )
    if inv_o and inv_r and acc_o and acc_r:
        try:
            typed_data = json.dumps(
                build_acceptance_evidence_typed_data(
                    work_order,
                    membership,
                    cost,
                    inv_o,
                    inv_r,
                    acc_o,
                    acc_r,
                    event_id,
                )
            )
        except (ValidationError, PermissionDenied, ValueError):
            typed_data = None
    wallet = (
        SignerWallet.objects.filter(membership=membership, active=True).order_by("pk").first()
    )
    if wallet is not None:
        expected_signer = wallet.address

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
            typed_data=typed_data,
            expected_signer=expected_signer,
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
