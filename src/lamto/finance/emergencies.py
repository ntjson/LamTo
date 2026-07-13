from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.capabilities import EMERGENCY_AUTHORIZE, PROPOSAL_APPROVE, WORK_ASSIGN
from lamto.accounts.models import Organization
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.maintenance.models import WorkOrder

from .models import EmergencyAuthorization, EmergencyRatification


ZERO_HASH = "0x" + "00" * 32
PENDING_ANCHORING_LABEL = "Pending blockchain anchoring"
ANCHORED_LABEL = "Blockchain anchored"


def _label(drill):
    return "Emergency drill" if drill else "Emergency"


def _locked_work_order(work_order):
    locked = (
        WorkOrder.objects.select_for_update()
        .select_related("case")
        .filter(pk=getattr(work_order, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Work order does not exist.")
    return locked


def _require_same_building(membership, work_order, message):
    if membership.organization.building_id != work_order.case.building_id:
        raise PermissionDenied(message)


def _reason_digest(reason):
    return payload_hash({"reason": reason})


def build_emergency_authorization_evidence_payload(work_order, estimate_vnd, timestamp=None):
    if not work_order.emergency_requested_at:
        work_order = WorkOrder.objects.filter(pk=getattr(work_order, "pk", None)).first()
    if not work_order.emergency_requested_at or not work_order.emergency_reason:
        raise ValidationError("An emergency request is required.")
    if estimate_vnd is not None and (type(estimate_vnd) is not int or estimate_vnd <= 0):
        raise ValidationError("Emergency estimate must be a positive integer when supplied.")
    return {
        "work_order_id": work_order.pk,
        "reason_digest": _reason_digest(work_order.emergency_reason),
        "available_estimate_vnd": estimate_vnd or 0,
        "authorization_timestamp": utc_rfc3339(timestamp or work_order.emergency_requested_at),
        "drill": work_order.drill,
    }


def build_emergency_authorization_evidence_typed_data(
    work_order, membership, estimate_vnd, event_id, timestamp=None
):
    payload = build_emergency_authorization_evidence_payload(work_order, estimate_vnd, timestamp)
    return build_evidence_typed_data(
        event_id, EvidenceType.EMERGENCY_AUTHORIZATION, "0x" + payload_hash(payload), ZERO_HASH
    )


def build_emergency_ratification_evidence_payload(
    authorization, decision, reason, timestamp=None
):
    if decision not in {"RATIFY", "REJECT"}:
        raise ValidationError("Emergency decision is invalid.")
    if not isinstance(reason, str) or not (reason := reason.strip()):
        raise ValidationError("Emergency outcome reason is required.")
    return {
        "decision": decision,
        "result": "RATIFIED" if decision == "RATIFY" else "REJECTED",
        "reason_digest": _reason_digest(reason),
        "deadline_result": "MET",
        "decision_timestamp": utc_rfc3339(timestamp or authorization.authorized_at),
        "drill": authorization.drill,
    }


def build_emergency_ratification_evidence_typed_data(
    authorization, membership, decision, reason, event_id, timestamp=None
):
    payload = build_emergency_ratification_evidence_payload(
        authorization, decision, reason, timestamp
    )
    return build_evidence_typed_data(
        event_id,
        EvidenceType.EMERGENCY_OUTCOME,
        "0x" + payload_hash(payload),
        "0x" + authorization.outbox_event.payload_hash,
    )


@transaction.atomic
def request_emergency(work_order, operator_membership, reason, drill=False) -> WorkOrder:
    work_order = _locked_work_order(work_order)
    membership = require_capability(
        operator_membership.user, operator_membership.pk, WORK_ASSIGN
    )
    _require_same_building(membership, work_order, "Operator must belong to the work-order building.")
    if not isinstance(reason, str) or not (reason := reason.strip()):
        raise ValidationError("Emergency safety reason is required.")
    if type(drill) is not bool:
        raise ValidationError("Emergency drill must be a boolean.")
    if work_order.emergency_requested_at is not None:
        raise ValidationError("Emergency has already been requested.")
    if EmergencyAuthorization.objects.filter(work_order=work_order).exists():
        raise ValidationError("Emergency has already been authorized.")
    if work_order.authorization_status == WorkOrder.AuthorizationStatus.AUTHORIZED:
        raise ValidationError(
            "Cannot request emergency on an already authorized work order."
        )
    if work_order.authorization_status not in {
        WorkOrder.AuthorizationStatus.PENDING,
        WorkOrder.AuthorizationStatus.NOT_REQUIRED,
    }:
        raise ValidationError("Work order is not eligible for emergency request.")
    work_order.emergency = True
    work_order.drill = drill
    work_order.emergency_requested_by = membership
    work_order.emergency_reason = reason
    work_order.emergency_requested_at = timezone.now()
    work_order.save(
        update_fields=[
            "emergency",
            "drill",
            "emergency_requested_by",
            "emergency_reason",
            "emergency_requested_at",
        ]
    )
    record_audit(
        membership.user,
        membership,
        "emergency.request",
        "WorkOrder",
        str(work_order.pk),
        "accepted",
        {"drill": drill},
    )
    return work_order


@transaction.atomic
def authorize_emergency(
    work_order, board_membership, estimate_vnd, signature, event_id, now
) -> EmergencyAuthorization:
    work_order = _locked_work_order(work_order)
    membership = require_capability(
        board_membership.user, board_membership.pk, EMERGENCY_AUTHORIZE
    )
    _require_same_building(membership, work_order, "Board must belong to the work-order building.")
    if not work_order.emergency or work_order.emergency_requested_at is None:
        raise ValidationError("An emergency request is required before authorization.")
    if EmergencyAuthorization.objects.filter(work_order=work_order).exists():
        raise ValidationError("Emergency has already been authorized.")
    if not isinstance(now, type(timezone.now())) or now.tzinfo is None:
        raise ValidationError("Authorization time must be timezone-aware.")
    if now < work_order.emergency_requested_at:
        raise ValidationError("Authorization time cannot precede the emergency request.")
    payload = build_emergency_authorization_evidence_payload(
        work_order, estimate_vnd, timestamp=now
    )
    event = queue_signed_event(
        event_id,
        EvidenceType.EMERGENCY_AUTHORIZATION,
        payload,
        ZERO_HASH,
        membership,
        signature,
    )
    authorization = EmergencyAuthorization.objects.create(
        work_order=work_order,
        reason=work_order.emergency_reason,
        estimate_vnd=estimate_vnd,
        membership=membership,
        wallet=event.signer_wallet,
        signature=event.signature,
        authorized_at=now,
        ratification_deadline=now + timedelta(hours=24),
        drill=work_order.drill,
        label=_label(work_order.drill),
        outbox_event=event,
    )
    work_order.authorization_status = WorkOrder.AuthorizationStatus.AUTHORIZED
    work_order.save(update_fields=["authorization_status"])
    record_audit(
        membership.user,
        membership,
        "emergency.authorize",
        "EmergencyAuthorization",
        str(authorization.pk),
        "accepted",
        {"event_id": event.event_id, "drill": authorization.drill},
    )
    try:
        from lamto.notifications.hooks import notify_emergency_authorized

        notify_emergency_authorized(authorization)
    except Exception:
        pass
    return authorization


def _locked_authorization(authorization):
    locked = (
        EmergencyAuthorization.objects.select_for_update()
        .select_related("work_order__case", "outbox_event")
        .filter(pk=getattr(authorization, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Emergency authorization does not exist.")
    return locked


def decide_emergency(
    authorization,
    representative_membership,
    decision,
    reason,
    signature,
    event_id,
    *,
    now=None,
) -> EmergencyRatification:
    if now is None:
        now = timezone.now()
    if not isinstance(now, type(timezone.now())) or now.tzinfo is None:
        raise ValidationError("Decision time must be timezone-aware.")
    late = False
    with transaction.atomic():
        authorization = _locked_authorization(authorization)
        membership = require_capability(
            representative_membership.user, representative_membership.pk, PROPOSAL_APPROVE
        )
        if membership.organization.kind != Organization.Kind.RESIDENT_REP:
            raise PermissionDenied("Only a resident representative may ratify an emergency.")
        _require_same_building(
            membership, authorization.work_order, "Representative must belong to the work-order building."
        )
        existing = EmergencyRatification.objects.filter(authorization=authorization).first()
        if existing is not None:
            if existing.outcome == EmergencyRatification.Outcome.OVERDUE:
                late = True
            else:
                raise ValidationError("Emergency already has a terminal outcome.")
        if now >= authorization.ratification_deadline:
            late = True
        else:
            if decision not in {"RATIFY", "REJECT"}:
                raise ValidationError("Emergency decision is invalid.")
            if not isinstance(reason, str) or not (reason := reason.strip()):
                raise ValidationError("Emergency outcome reason is required.")
            payload = build_emergency_ratification_evidence_payload(
                authorization, decision, reason, timestamp=now
            )
            event = queue_signed_event(
                event_id,
                EvidenceType.EMERGENCY_OUTCOME,
                payload,
                "0x" + authorization.outbox_event.payload_hash,
                membership,
                signature,
            )
            outcome = EmergencyRatification.objects.create(
                authorization=authorization,
                decision=decision,
                outcome=("RATIFIED" if decision == "RATIFY" else "REJECTED"),
                reason=reason,
                membership=membership,
                wallet=event.signer_wallet,
                signature=event.signature,
                outbox_event=event,
                decided_at=now,
                label=_label(authorization.drill),
            )
            record_audit(
                membership.user,
                membership,
                "emergency.ratify" if decision == "RATIFY" else "emergency.reject",
                "EmergencyRatification",
                str(outcome.pk),
                "accepted",
                {"event_id": event.event_id},
            )
            try:
                from lamto.notifications.hooks import notify_emergency_outcome

                notify_emergency_outcome(outcome)
            except Exception:
                pass
            return outcome
    if late:
        record_audit(
            representative_membership.user,
            representative_membership,
            "emergency.ratify" if decision == "RATIFY" else "emergency.reject",
            "EmergencyAuthorization",
            str(authorization.pk),
            "denied",
            {"reason": "ratification deadline passed"},
        )
        raise ValidationError("Emergency ratification deadline has passed.")


def mark_overdue_ratifications(now) -> int:
    if not isinstance(now, type(timezone.now())) or now.tzinfo is None:
        raise ValidationError("Overdue check time must be timezone-aware.")
    with transaction.atomic():
        authorizations = EmergencyAuthorization.objects.select_for_update().filter(
            ratification_deadline__lte=now,
        ).exclude(
            pk__in=EmergencyRatification.objects.values("authorization_id")
        )
        outcomes = [
            EmergencyRatification(
                authorization=authorization,
                decision=EmergencyRatification.Decision.OVERDUE,
                outcome=EmergencyRatification.Outcome.OVERDUE,
                reason="No resident representative decision by the ratification deadline.",
                decided_at=now,
                label=_label(authorization.drill),
            )
            for authorization in authorizations
        ]
        EmergencyRatification.objects.bulk_create(outcomes)
    return len(outcomes)


def emergency_verification_label(work_order):
    try:
        authorization = work_order.emergency_authorization
    except EmergencyAuthorization.DoesNotExist:
        return _label(work_order.drill)
    try:
        outcome = authorization.ratification
    except EmergencyRatification.DoesNotExist:
        outcome = None
    # Unsigned OVERDUE has no outbox event; keep pending until a later publisher
    # snapshot can anchor that exact overdue fact.
    if outcome is not None and not outcome.outbox_event_id:
        return PENDING_ANCHORING_LABEL
    events = [authorization.outbox_event]
    if outcome is not None and outcome.outbox_event_id:
        events.append(outcome.outbox_event)
    if any(event.status != BlockchainOutboxEvent.Status.CONFIRMED for event in events):
        return PENDING_ANCHORING_LABEL
    return ANCHORED_LABEL
