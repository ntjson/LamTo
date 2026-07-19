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
from lamto.documents.models import Document
from lamto.finance.models import AcceptanceRecord, PaymentEvidence
from lamto.web.forms.staff import (
    AcceptWorkForm,
    EmergencyAuthorizeForm,
    RecordPaymentForm,
    VerifyPaymentForm,
)
from lamto.web.staff import require_staff_capability, resolve_active_membership, staff_context
from lamto.web.views.staff_common import (
    accountability_chain_for,
    prepare_record_list,
    signed_action_failure,
)
from lamto.web.staff_signing import document_pair_options, selected_pair


@login_required
@require_http_methods(["POST"])
def payment_record(request):
    """Privileged signed financial action: requires MFA + recent re-auth."""
    require_staff_mfa(request)
    require_recent_auth(request)
    membership, memberships = require_staff_capability(request, PAYMENT_RECORD)
    building_id = membership.organization.building_id
    acceptance_id = request.POST.get("acceptance_id")
    acceptance = get_object_or_404(
        AcceptanceRecord,
        pk=acceptance_id,
        work_order__case__building_id=building_id,
    )
    if hasattr(acceptance, "payment") and acceptance.payment is not None:
        raise PermissionDenied("Payment already recorded.")
    proof_options = document_pair_options(building_id, Document.Kind.PAYMENT_PROOF)
    form = RecordPaymentForm(
        request.POST,
        proof_choices=[(v, label) for v, label, _, _ in proof_options],
    )
    if not form.is_valid():
        from django.http import JsonResponse

        return JsonResponse({"errors": form.errors}, status=400)
    pair = selected_pair(proof_options, form.cleaned_data["proof_pair"])
    if not pair:
        from django.http import JsonResponse

        form.add_error(
            "proof_pair", "Selected evidence is no longer available. Select it again."
        )
        return JsonResponse({"errors": form.errors}, status=400)
    proof_o, proof_r = pair
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
    messages.success(
        request,
        "Payment recorded. An independent verifier now checks it "
        "against the bank statement.",
    )
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
    status_groups = {
        "completed": (PaymentEvidence.ExternalStatus.COMPLETED,),
        "attention": (
            PaymentEvidence.ExternalStatus.FAILED,
            PaymentEvidence.ExternalStatus.REVERSED,
        ),
    }
    valid_status = status in PaymentEvidence.ExternalStatus.values
    active_group = status if status in status_groups else next(
        (group for group, values in status_groups.items() if status in values), ""
    )
    record_list = (
        prepare_record_list(
            request,
            AcceptanceRecord.objects.filter(
                work_order__case__building_id=building_id,
                payment__isnull=True,
            ).select_related("work_order__case"),
            search_fields=("work_order__case__category",),
            sorts=(("", "Newest first", ("-accepted_at",)),),
            page_param="rpage",
        )
        if PAYMENT_RECORD in caps
        else None
    )
    verify_qs = PaymentEvidence.objects.filter(
        acceptance__work_order__case__building_id=building_id,
        verification__isnull=True,
    )
    if status in status_groups:
        verify_qs = verify_qs.filter(external_status__in=status_groups[status])
    elif valid_status:
        verify_qs = verify_qs.filter(external_status=status)
    verify_list = (
        prepare_record_list(
            request,
            verify_qs.select_related("acceptance__work_order__case"),
            search_fields=(
                "bank_reference",
                "acceptance__work_order__case__category",
            ),
            sorts=(("", "Newest first", ("-recorded_at",)),),
        )
        if PAYMENT_VERIFY in caps
        else None
    )
    record_items = [
        {
            "url": f"/s/payments/record/{a.pk}/",
            "title": f"Acceptance #{a.pk} · {a.work_order.case.category}",
            "amount_vnd": a.actual_cost_vnd,
            "status": None,
            "deadline": None,
            "deadline_tone": "neutral",
            "next_action": "Record payment",
        }
        for a in (record_list["page"].object_list if record_list else [])
    ]
    verify_items = [
        {
            "url": f"/s/payments/verify/{p.pk}/",
            "title": f"Payment #{p.pk} · {p.acceptance.work_order.case.category}",
            "amount_vnd": p.amount_vnd,
            "status": p.get_external_status_display(),
            "deadline": None,
            "deadline_tone": "neutral",
            "next_action": "Verify against bank statement",
        }
        for p in (verify_list["page"].object_list if verify_list else [])
    ]
    filters = [
        {"label": label, "value": value, "active": value == active_group}
        for value, label in (("completed", "Completed"), ("attention", "Needs review"))
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
            record_items=record_items,
            record_list=record_list,
            verify_items=verify_items,
            verify_list=verify_list,
            search_label="Search payments",
            search_placeholder="ID, bank reference, or category…",
            filters=filters if PAYMENT_VERIFY in caps else None,
            filters_active=(valid_status or status in status_groups)
            if PAYMENT_VERIFY in caps
            else False,
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
    from django.utils.dateparse import parse_datetime

    from lamto.accounts.models import SignerWallet
    from lamto.evidence.services import utc_rfc3339
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

    # Rebuild scoped options on every GET/POST before constructing the form.
    proof_options = document_pair_options(building_id, Document.Kind.PAYMENT_PROOF)
    proof_choices = [(v, label) for v, label, _, _ in proof_options]
    record_form = RecordPaymentForm(
        request.POST or None, proof_choices=proof_choices
    )
    typed_data = None
    expected_signer = ""
    if request.method == "POST" and record_form.is_valid():
        require_recent_auth(request)
        pair = selected_pair(proof_options, record_form.cleaned_data["proof_pair"])
        if not pair:
            record_form.add_error(
                "proof_pair",
                "Selected evidence is no longer available. Select it again.",
            )
        else:
            proof_o, proof_r = pair
            try:
                payment = record_form.save(acceptance, membership, proof_o, proof_r)
            except (ValidationError, PermissionDenied) as error:
                signed_action_failure(
                    request,
                    error,
                    action="The payment record",
                    next_step="Check the amount and linked proof, then sign again.",
                )
            else:
                messages.success(
                    request,
                    f"Payment #{payment.pk} recorded ({payment.amount_vnd:,} VND, "
                    f"ref {payment.bank_reference}). An independent verifier now "
                    "checks it against the bank statement.",
                )
                return redirect("web:payment-verify-detail", pk=payment.pk)

    event_id = new_event_id()
    amount = acceptance.actual_cost_vnd
    bank_ref = "VCB-PILOT-001"
    ext_status = "COMPLETED"
    reason = "Thanh toan chuyen khoan"
    # Pin once for this form render; must be the same value MetaMask signs and
    # record_payment verifies (do not call timezone.now() again on POST).
    completed_at = timezone.now()
    payment_id = None
    # Prefer posted pair, else first available scoped option for typed-data pilot.
    proof_pair_value = ""
    proof_o = proof_r = None
    if proof_options:
        proof_pair_value, _, proof_o, proof_r = proof_options[0]
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
        posted_pair = selected_pair(proof_options, record_form.data.get("proof_pair"))
        if posted_pair:
            proof_o, proof_r = posted_pair
            proof_pair_value = record_form.data.get("proof_pair") or proof_pair_value
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

    # Keep bound form (and field errors) after a failed POST; only rebuild on GET.
    if not record_form.is_bound or not record_form.errors:
        record_form = RecordPaymentForm(
            proof_choices=proof_choices,
            initial={
                "event_id": event_id,
                "reason": reason,
                "bank_reference": bank_ref,
                "amount_vnd": amount,
                "external_status": ext_status,
                "proof_pair": proof_pair_value,
                "payment_id": payment_id,
                "completed_at": utc_rfc3339(completed_at),
            },
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
            accountability_stages=accountability_chain_for(acceptance),
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
    from lamto.finance.models import PublishedLedgerEntry

    payment = get_object_or_404(
        PaymentEvidence.objects.select_related(
            "acceptance__work_order",
            "recorder",
            "verification",
            "outbox_event",
            "wallet",
            "proof_original",
            "proof_redacted",
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
    ledger_entry = (
        PublishedLedgerEntry.objects.filter(payment_id=payment.pk)
        .only("pk")
        .first()
    )
    payment_doc_hashes = []
    for version in (payment.proof_original, payment.proof_redacted):
        if version is not None:
            payment_doc_hashes.append(
                {
                    "filename": version.filename,
                    "variant": version.variant,
                    "sha256": version.sha256,
                }
            )
    payment_signer = payment.wallet.address if payment.wallet_id else ""
    payment_tx = ""
    if payment.outbox_event_id and payment.outbox_event.transaction_hash:
        payment_tx = payment.outbox_event.transaction_hash

    if request.method == "POST" and verify_form is not None and can_verify:
        require_staff_capability(request, PAYMENT_VERIFY)
        require_recent_auth(request)
        if verify_form.is_valid():
            try:
                # timestamp defaults to payment.recorded_at — must match typed data below
                verify_form.save(payment, membership)
            except (ValidationError, PermissionDenied) as error:
                signed_action_failure(
                    request,
                    error,
                    action="The payment verification",
                    next_step="Check the decision and reason, then sign again.",
                )
            else:
                messages.success(
                    request,
                    f"Payment #{payment.pk} verified in the evidence chain. "
                    "The expense can now be published to residents.",
                )
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
            ledger_entry=ledger_entry,
            payment_doc_hashes=payment_doc_hashes,
            payment_signer=payment_signer,
            payment_tx=payment_tx,
            accountability_stages=accountability_chain_for(payment),
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
    building_id = membership.organization.building_id
    work_order = get_object_or_404(
        WorkOrder,
        pk=pk,
        case__building_id=building_id,
    )
    # Rebuild scoped options on every GET/POST before constructing the form.
    invoice_options = document_pair_options(building_id, Document.Kind.INVOICE)
    acceptance_options = document_pair_options(
        building_id, Document.Kind.ACCEPTANCE_REPORT
    )
    invoice_choices = [(v, label) for v, label, _, _ in invoice_options]
    acceptance_choices = [(v, label) for v, label, _, _ in acceptance_options]
    form = AcceptWorkForm(
        request.POST or None,
        invoice_choices=invoice_choices,
        acceptance_choices=acceptance_choices,
    )
    typed_data = None
    expected_signer = ""
    if request.method == "POST":
        require_recent_auth(request)
    if request.method == "POST" and form.is_valid():
        pair_inv = selected_pair(invoice_options, form.cleaned_data["invoice_pair"])
        pair_acc = selected_pair(
            acceptance_options, form.cleaned_data["acceptance_pair"]
        )
        if not pair_inv:
            form.add_error(
                "invoice_pair",
                "Selected evidence is no longer available. Select it again.",
            )
        elif not pair_acc:
            form.add_error(
                "acceptance_pair",
                "Selected evidence is no longer available. Select it again.",
            )
        else:
            docs = {
                "invoice_original": pair_inv[0],
                "invoice_redacted": pair_inv[1],
                "acceptance_original": pair_acc[0],
                "acceptance_redacted": pair_acc[1],
            }
            try:
                form.save(work_order, membership, docs)
            except (ValidationError, PermissionDenied) as error:
                signed_action_failure(
                    request,
                    error,
                    action="The work acceptance",
                    next_step="Check the cost and linked evidence, then sign again.",
                )
            else:
                messages.success(
                    request,
                    "Work accepted. A payment recorder signs the matching "
                    "bank transfer next.",
                )
                return redirect("web:work-order-detail", pk=work_order.pk)

    # Mint event id + typed data for MetaMask. Prefer POST values; else first
    # scoped pair so the form is fillable without a separate upload UI.
    event_id = new_event_id()
    cost = 5_000_000
    reason = "Nghiem thu OK"
    inv_pair_value = ""
    acc_pair_value = ""
    inv_o = inv_r = acc_o = acc_r = None
    if invoice_options:
        inv_pair_value, _, inv_o, inv_r = invoice_options[0]
    if acceptance_options:
        acc_pair_value, _, acc_o, acc_r = acceptance_options[0]
    if form.is_bound:
        try:
            cost = int(form.data.get("actual_cost_vnd") or cost)
        except (TypeError, ValueError):
            pass
        reason = (form.data.get("reason") or reason).strip() or reason
        posted_inv = selected_pair(invoice_options, form.data.get("invoice_pair"))
        posted_acc = selected_pair(acceptance_options, form.data.get("acceptance_pair"))
        if posted_inv:
            inv_o, inv_r = posted_inv
            inv_pair_value = form.data.get("invoice_pair") or inv_pair_value
        if posted_acc:
            acc_o, acc_r = posted_acc
            acc_pair_value = form.data.get("acceptance_pair") or acc_pair_value
        if request.method == "POST" and form.data.get("event_id"):
            event_id = form.data.get("event_id").strip() or event_id

    # Keep bound form (and field errors) after a failed POST; only rebuild on GET.
    if not form.is_bound or not form.errors:
        form = AcceptWorkForm(
            invoice_choices=invoice_choices,
            acceptance_choices=acceptance_choices,
            initial={
                "event_id": event_id,
                "reason": reason,
                "actual_cost_vnd": cost,
                "invoice_pair": inv_pair_value,
                "acceptance_pair": acc_pair_value,
            },
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
            accountability_stages=accountability_chain_for(work_order),
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
            messages.success(
                request,
                "Emergency authorized. A resident representative or the Board "
                "must ratify or reject this authorization afterwards.",
            )
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
            accountability_stages=accountability_chain_for(work_order),
        ),
    )
