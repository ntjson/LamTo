from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data

from .models import AcceptanceRecord, PaymentEvidence, PaymentVerification


EVIDENCE_EXTERNAL_STATUS = {
    PaymentEvidence.ExternalStatus.COMPLETED: "SETTLED",
    PaymentEvidence.ExternalStatus.FAILED: "FAILED",
    PaymentEvidence.ExternalStatus.REVERSED: "REVERSED",
}

EVIDENCE_VERIFICATION = {
    PaymentVerification.Decision.VERIFIED: ("APPROVE", "MATCH"),
    PaymentVerification.Decision.REJECTED: ("REJECT", "MISMATCH"),
}


def _allocate_pk(model):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence(%s, 'id'))",
            [model._meta.db_table],
        )
        return cursor.fetchone()[0]


def allocate_payment_id() -> int:
    """Reserve a PaymentEvidence primary key for sign-before-write.

    Call once before signing PAYMENT_RECORDED evidence, include the returned
    id in the signed payload, and pass the same id to record_payment.
    Clients must not peek finance_paymentevidence_id_seq.last_value.
    """
    return int(_allocate_pk(PaymentEvidence))


def normalize_bank_reference(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("Bank reference is required.")
    normalized = " ".join(value.split()).upper()
    if not normalized:
        raise ValidationError("Bank reference is required.")
    if len(normalized) > 128:
        raise ValidationError("Bank reference is too long.")
    return normalized


def _locked_acceptance(acceptance):
    locked = (
        AcceptanceRecord.objects.select_for_update()
        .select_related(
            "case",
            "outbox_event",
            "membership__user",
        )
        .filter(pk=getattr(acceptance, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Acceptance record does not exist.")
    return locked


def _locked_payment(payment):
    locked = (
        PaymentEvidence.objects.select_for_update()
        .select_related(
            "acceptance__case",
            "recorder__user",
            "outbox_event",
        )
        .filter(pk=getattr(payment, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Payment evidence does not exist.")
    return locked


def _require_proof_pair(original, redacted, building_id, *, lock=False):
    original_id = getattr(original, "pk", None)
    redacted_id = getattr(redacted, "pk", None)
    if original_id is None or redacted_id is None:
        raise ValidationError("Payment proof documents are required.")
    queryset = DocumentVersion.objects.select_related("document").filter(
        pk__in={original_id, redacted_id}
    )
    if lock:
        queryset = queryset.select_for_update()
    versions = {version.pk: version for version in queryset}
    if original_id not in versions or redacted_id not in versions:
        raise ValidationError("Payment proof versions must still exist.")
    original = versions[original_id]
    redacted = versions[redacted_id]
    kind = Document.Kind.PAYMENT_PROOF
    if (
        original.document.kind != kind
        or original.document.building_id != building_id
        or original.variant != DocumentVersion.Variant.ORIGINAL
        or original.scan_status != DocumentVersion.ScanStatus.CLEAN
        or original.redacts_id is not None
    ):
        raise ValidationError(
            "Payment proof originals must be clean, safe, and in the work-order building."
        )
    if (
        redacted.document_id != original.document_id
        or redacted.document.kind != kind
        or redacted.document.building_id != building_id
        or redacted.variant != DocumentVersion.Variant.REDACTED
        or redacted.scan_status != DocumentVersion.ScanStatus.CLEAN
        or redacted.redacts_id != original.pk
        or redacted.sha256 == original.sha256
    ):
        raise ValidationError(
            "Payment proof requires a distinct clean redacted copy in the work-order building."
        )
    return original, redacted


def build_payment_evidence_payload(
    acceptance,
    payment_id,
    bank_reference,
    amount_vnd,
    external_status,
    completed_at,
    proof_original,
    proof_redacted,
):
    if type(payment_id) is not int or payment_id <= 0:
        raise ValidationError("Payment id must be a positive integer.")
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Payment amount must be a positive integer VND amount.")
    if external_status not in PaymentEvidence.ExternalStatus.values:
        raise ValidationError("Payment external status is invalid.")
    if not isinstance(completed_at, type(timezone.now())) or completed_at.tzinfo is None:
        raise ValidationError("Payment completion time must be timezone-aware.")
    if (
        external_status == PaymentEvidence.ExternalStatus.COMPLETED
        and completed_at is None
    ):
        raise ValidationError("Completed payments require an external completion time.")
    bank_reference = normalize_bank_reference(bank_reference)
    proof_original, proof_redacted = _require_proof_pair(
        proof_original,
        proof_redacted,
        acceptance.case.building_id,
    )
    return {
        "case_id": acceptance.case_id,
        "payment_id": payment_id,
        "amount_vnd": amount_vnd,
        "bank_reference_digest": payload_hash({"bank_reference": bank_reference}),
        "external_status": EVIDENCE_EXTERNAL_STATUS[external_status],
        "external_timestamp": utc_rfc3339(completed_at),
        "payment_proof_original_hash": proof_original.sha256,
        "payment_proof_redacted_hash": proof_redacted.sha256,
    }


def build_payment_evidence_typed_data(
    acceptance,
    membership,
    payment_id,
    bank_reference,
    amount_vnd,
    external_status,
    completed_at,
    proof_original,
    proof_redacted,
    event_id,
):
    payload = build_payment_evidence_payload(
        acceptance,
        payment_id,
        bank_reference,
        amount_vnd,
        external_status,
        completed_at,
        proof_original,
        proof_redacted,
    )
    return build_evidence_typed_data(
        event_id,
        EvidenceType.PAYMENT_RECORDED,
        "0x" + payload_hash(payload),
        "0x" + acceptance.outbox_event.payload_hash,
    )


def build_payment_verification_evidence_payload(payment, decision, timestamp=None):
    if decision not in PaymentVerification.Decision.values:
        raise ValidationError("Payment verification decision is invalid.")
    evidence_decision, verification_result = EVIDENCE_VERIFICATION[decision]
    verified_at = timestamp or payment.recorded_at or timezone.now()
    return {
        "payment_hash": payment.outbox_event.payload_hash,
        "decision": evidence_decision,
        "verification_result": verification_result,
        "verification_timestamp": utc_rfc3339(verified_at),
    }


def build_payment_verification_evidence_typed_data(
    payment, membership, decision, event_id, timestamp=None
):
    payload = build_payment_verification_evidence_payload(
        payment, decision, timestamp=timestamp
    )
    return build_evidence_typed_data(
        event_id,
        EvidenceType.PAYMENT_VERIFIED,
        "0x" + payload_hash(payload),
        "0x" + payment.outbox_event.payload_hash,
    )


@transaction.atomic
def record_payment(
    acceptance,
    membership,
    bank_reference,
    amount_vnd,
    external_status,
    completed_at,
    proof_original,
    proof_redacted,
    signature,
    event_id,
    payment_id,
) -> PaymentEvidence:
    acceptance = _locked_acceptance(acceptance)
    case = acceptance.case
    actor = require_management(membership.user, case.building_id)
    if PaymentEvidence.objects.filter(acceptance=acceptance).exists():
        raise ValidationError("Payment evidence already exists for this acceptance.")
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Payment amount must be a positive integer VND amount.")
    if amount_vnd != acceptance.actual_cost_vnd:
        raise ValidationError("Payment amount must equal the accepted actual cost.")
    if external_status not in PaymentEvidence.ExternalStatus.values:
        raise ValidationError("Payment external status is invalid.")
    if not isinstance(completed_at, type(timezone.now())) or completed_at.tzinfo is None:
        raise ValidationError("Payment completion time must be timezone-aware.")
    if external_status == PaymentEvidence.ExternalStatus.COMPLETED and completed_at is None:
        raise ValidationError("Completed payments require an external completion time.")

    bank_reference = normalize_bank_reference(bank_reference)
    proof_original, proof_redacted = _require_proof_pair(
        proof_original,
        proof_redacted,
        case.building_id,
        lock=True,
    )
    if type(payment_id) is not int or payment_id <= 0:
        raise ValidationError("Payment id must be a positive integer.")
    if PaymentEvidence.objects.filter(pk=payment_id).exists():
        raise ValidationError("Payment id is already used.")
    payload = build_payment_evidence_payload(
        acceptance,
        payment_id,
        bank_reference,
        amount_vnd,
        external_status,
        completed_at,
        proof_original,
        proof_redacted,
    )
    event = queue_signed_event(
        event_id,
        EvidenceType.PAYMENT_RECORDED,
        payload,
        "0x" + acceptance.outbox_event.payload_hash,
        actor,
        signature,
    )
    payment = PaymentEvidence(
        pk=payment_id,
        acceptance=acceptance,
        bank_reference=bank_reference,
        amount_vnd=amount_vnd,
        external_status=external_status,
        completed_at=completed_at,
        proof_original=proof_original,
        proof_redacted=proof_redacted,
        recorder=actor,
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        recorded_at=timezone.now(),
    )
    payment.save(force_insert=True)
    record_audit(
        actor.user,
        actor,
        "payment.record",
        "PaymentEvidence",
        str(payment.pk),
        "accepted",
        {
            "acceptance_id": acceptance.pk,
            "amount_vnd": amount_vnd,
            "external_status": external_status,
            "event_id": event.event_id,
        },
    )
    try:
        from lamto.notifications.hooks import notify_payment_recorded

        notify_payment_recorded(payment)
    except Exception:
        pass
    return payment


def verify_payment(
    payment,
    membership,
    decision,
    reason,
    signature,
    event_id,
    timestamp=None,
) -> PaymentVerification:
    denied = False
    denied_target = None
    denied_actor = membership
    with transaction.atomic():
        payment = _locked_payment(payment)
        actor = require_management(
            membership.user, payment.acceptance.case.building_id
        )
        if actor.user_id == payment.recorder.user_id:
            denied = True
            denied_target = payment
            denied_actor = actor
        else:
            if decision not in PaymentVerification.Decision.values:
                raise ValidationError("Payment verification decision is invalid.")
            if not isinstance(reason, str) or not (reason := reason.strip()):
                raise ValidationError("Payment verification reason is required.")
            if PaymentVerification.objects.filter(payment=payment).exists():
                raise ValidationError("Payment evidence has already been verified.")
            verification_timestamp = timestamp or payment.recorded_at or timezone.now()
            payload = build_payment_verification_evidence_payload(
                payment, decision, timestamp=verification_timestamp
            )
            event = queue_signed_event(
                event_id,
                EvidenceType.PAYMENT_VERIFIED,
                payload,
                "0x" + payment.outbox_event.payload_hash,
                actor,
                signature,
            )
            verification = PaymentVerification.objects.create(
                payment=payment,
                membership=actor,
                decision=decision,
                reason=reason,
                wallet=event.signer_wallet,
                signature=event.signature,
                outbox_event=event,
                verified_at=timezone.now(),
            )
            record_audit(
                actor.user,
                actor,
                "payment.verify" if decision == PaymentVerification.Decision.VERIFIED else "payment.reject",
                "PaymentVerification",
                str(verification.pk),
                "accepted",
                {
                    "payment_id": payment.pk,
                    "decision": decision,
                    "event_id": event.event_id,
                    "reason": reason,
                },
            )
            try:
                from lamto.notifications.hooks import notify_payment_verified

                notify_payment_verified(verification)
            except Exception:
                pass
            return verification
    if denied:
        record_audit(
            denied_actor.user,
            denied_actor,
            "payment.verify",
            "PaymentEvidence",
            str(denied_target.pk),
            "denied",
            {"reason": "payment recorder cannot verify own evidence"},
        )
        raise PermissionDenied("Payment recorder cannot verify their own evidence.")
