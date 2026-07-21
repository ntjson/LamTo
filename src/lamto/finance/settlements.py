import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.models import EvidenceType
from lamto.evidence.services import queue_platform_event, utc_rfc3339

from .models import Proposal, Settlement


def normalize_bank_reference(value):
    value = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    if not value:
        raise ValidationError("Bank reference is required.")
    return value


def _require_proof_pair(original, redacted, building_id, *, lock=False):
    ids = {getattr(original, "pk", None), getattr(redacted, "pk", None)}
    qs = DocumentVersion.objects.select_related("document").filter(pk__in=ids)
    if lock:
        qs = qs.select_for_update()
    versions = {v.pk: v for v in qs}
    original, redacted = versions.get(getattr(original, "pk", None)), versions.get(getattr(redacted, "pk", None))
    if not original or not redacted or original.document.kind != Document.Kind.PAYMENT_PROOF or original.document.building_id != building_id or original.variant != DocumentVersion.Variant.ORIGINAL or original.scan_status != DocumentVersion.ScanStatus.CLEAN or original.redacts_id is not None or redacted.document_id != original.document_id or redacted.variant != DocumentVersion.Variant.REDACTED or redacted.scan_status != DocumentVersion.ScanStatus.CLEAN or redacted.redacts_id != original.pk or redacted.sha256 == original.sha256:
        raise ValidationError("Settlement evidence requires a distinct clean original/redacted payment-proof pair in the proposal building.")
    return original, redacted


def build_settlement_evidence_payload(settlement):
    proposal = settlement.proposal
    return {"schema": "settlement.v1", "settlement_id": settlement.pk, "proposal_id": proposal.pk, "proposal_version": proposal.current_version.number, "amount_vnd": settlement.amount_vnd, "payee_name": settlement.payee_name, "bank_reference": normalize_bank_reference(settlement.bank_reference), "transfer_original_sha256": settlement.transfer_original.sha256, "transfer_redacted_sha256": settlement.transfer_redacted.sha256, "ack_original_sha256": settlement.ack_original.sha256, "ack_redacted_sha256": settlement.ack_redacted.sha256, "transfer_recorded_at": utc_rfc3339(settlement.transfer_recorded_at), "ack_recorded_at": utc_rfc3339(settlement.ack_recorded_at)}


@transaction.atomic
def record_transfer(proposal, membership, *, amount_vnd, payee_name, bank_reference, transfer_original, transfer_redacted):
    proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
    actor = require_management(membership.user, proposal.building_id)
    if proposal.status != Proposal.Status.COMPLETED:
        raise ValidationError("Only completed proposals can be settled.")
    if Settlement.objects.filter(proposal=proposal).exists():
        raise ValidationError("Settlement already exists for this proposal.")
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Settlement amount must be a positive integer VND amount.")
    payee_name = str(payee_name or "").strip()
    if not payee_name:
        raise ValidationError("Payee name is required.")
    original, redacted = _require_proof_pair(transfer_original, transfer_redacted, proposal.building_id, lock=True)
    settlement = Settlement.objects.create(proposal=proposal, amount_vnd=amount_vnd, payee_name=payee_name, bank_reference=normalize_bank_reference(bank_reference), transfer_original=original, transfer_redacted=redacted, transfer_recorded_by=actor, transfer_recorded_at=timezone.now())
    record_audit(actor.user, actor, "settlement.transfer_recorded", "Settlement", str(settlement.pk), "accepted")
    return settlement


@transaction.atomic
def record_acknowledgement(settlement, membership, *, ack_original, ack_redacted, event_id):
    settlement = Settlement.objects.select_for_update().get(pk=settlement.pk)
    actor = require_management(membership.user, settlement.proposal.building_id)
    if settlement.settled_at is not None:
        raise ValidationError("Settlement is already settled.")
    original, redacted = _require_proof_pair(ack_original, ack_redacted, settlement.proposal.building_id, lock=True)
    now = timezone.now()
    settlement.ack_original, settlement.ack_redacted, settlement.ack_recorded_by, settlement.ack_recorded_at = original, redacted, actor, now
    event = queue_platform_event(event_id, EvidenceType.SETTLEMENT, build_settlement_evidence_payload(settlement), "0x" + settlement.proposal.current_version.outbox_event.payload_hash, settlement.proposal.building)
    settlement.outbox_event, settlement.settled_at = event, now
    settlement.save(update_fields=["ack_original", "ack_redacted", "ack_recorded_by", "ack_recorded_at", "outbox_event", "settled_at"])
    from .fund import create_settlement_outflow
    create_settlement_outflow(settlement)
    from .publication import publish_settlement_entry
    publish_settlement_entry(settlement)
    record_audit(actor.user, actor, "settlement.settled", "Settlement", str(settlement.pk), "accepted", {"event_id": event.event_id})
    from lamto.notifications.hooks import notify_settled
    transaction.on_commit(lambda: notify_settled(settlement))
    return settlement
