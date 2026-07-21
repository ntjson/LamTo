from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.maintenance.models import MaintenanceCase, WorkUpdate, WorkUpdateEvidence

from .models import AcceptanceRecord, Proposal



def _locked_case(case):
    locked = (
        MaintenanceCase.objects.select_for_update()
        .filter(pk=getattr(case, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Case does not exist.")
    return locked


def _require_document_pair(original, redacted, kind, building_id, *, lock=False):
    original_id = getattr(original, "pk", None)
    redacted_id = getattr(redacted, "pk", None)
    if original_id is None or redacted_id is None:
        raise ValidationError("Invoice and acceptance documents are required.")
    queryset = DocumentVersion.objects.select_related("document").filter(
        pk__in={original_id, redacted_id}
    )
    if lock:
        queryset = queryset.select_for_update()
    versions = {version.pk: version for version in queryset}
    if original_id not in versions or redacted_id not in versions:
        raise ValidationError("Required document versions must still exist.")
    original = versions[original_id]
    redacted = versions[redacted_id]
    if (
        original.document.kind != kind
        or original.document.building_id != building_id
        or original.variant != DocumentVersion.Variant.ORIGINAL
        or original.scan_status != DocumentVersion.ScanStatus.CLEAN
        or original.redacts_id is not None
    ):
        raise ValidationError(
            "Document originals must be clean, safe, and in the work-order building."
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
            "Each original requires a distinct clean redacted copy in the work-order building."
        )
    return original, redacted


def _completion_photo_hashes(case, *, lock=False):
    updates = WorkUpdate.objects.filter(case=case).order_by("-pk")
    if lock:
        updates = updates.select_for_update()
    update = updates.first()
    if update is None:
        raise ValidationError("Completed work evidence is required before acceptance.")
    links = (
        WorkUpdateEvidence.objects.select_related("version")
        .filter(update=update)
        .order_by("kind", "version_id")
    )
    if lock:
        links = links.select_for_update()
    links = list(links)
    before = [link.version.sha256 for link in links if link.kind == WorkUpdateEvidence.Kind.BEFORE]
    after = [link.version.sha256 for link in links if link.kind == WorkUpdateEvidence.Kind.AFTER]
    if not before or not after:
        raise ValidationError("Acceptance requires before and after image hashes.")
    if not update.cause.strip() or not update.result.strip():
        raise ValidationError("Acceptance requires work cause and result.")
    return before + after


def _acceptance_previous_hash(case):
    try:
        proposal = case.proposal
    except Proposal.DoesNotExist as exc:
        raise ValidationError("A proposal is required before work acceptance.") from exc
    version = proposal.current_version
    if version is None:
        raise ValidationError("A current proposal version is required before acceptance.")
    return "0x" + version.outbox_event.payload_hash


def build_acceptance_evidence_payload(
    case,
    actual_cost_vnd,
    invoice_original,
    invoice_redacted,
    acceptance_original,
    acceptance_redacted,
    timestamp=None,
):
    if type(actual_cost_vnd) is not int or actual_cost_vnd <= 0:
        raise ValidationError("Actual cost must be a positive integer VND amount.")
    building_id = case.building_id
    invoice_original, invoice_redacted = _require_document_pair(
        invoice_original,
        invoice_redacted,
        Document.Kind.INVOICE,
        building_id,
    )
    acceptance_original, acceptance_redacted = _require_document_pair(
        acceptance_original,
        acceptance_redacted,
        Document.Kind.ACCEPTANCE_REPORT,
        building_id,
    )
    if case.completed_at is None:
        raise ValidationError("Case work must be completed before acceptance.")
    photo_hashes = _completion_photo_hashes(case)
    acceptance_timestamp = timestamp or case.completed_at
    return {
        "case_id": case.pk,
        "actual_cost_vnd": actual_cost_vnd,
        "acceptance_timestamp": utc_rfc3339(acceptance_timestamp),
        "invoice_original_hash": invoice_original.sha256,
        "invoice_redacted_hash": invoice_redacted.sha256,
        "acceptance_report_original_hash": acceptance_original.sha256,
        "acceptance_report_redacted_hash": acceptance_redacted.sha256,
        "photo_hashes": photo_hashes,
    }


def build_acceptance_evidence_typed_data(
    case,
    membership,
    actual_cost_vnd,
    invoice_original,
    invoice_redacted,
    acceptance_original,
    acceptance_redacted,
    event_id,
    timestamp=None,
):
    payload = build_acceptance_evidence_payload(
        case,
        actual_cost_vnd,
        invoice_original,
        invoice_redacted,
        acceptance_original,
        acceptance_redacted,
        timestamp=timestamp,
    )
    return build_evidence_typed_data(
        event_id,
        EvidenceType.WORK_ACCEPTANCE,
        "0x" + payload_hash(payload),
        _acceptance_previous_hash(case),
    )


@transaction.atomic
def accept_work(
    case,
    membership,
    actual_cost_vnd,
    invoice_original,
    invoice_redacted,
    acceptance_original,
    acceptance_redacted,
    signature,
    event_id,
    timestamp=None,
) -> AcceptanceRecord:
    case = _locked_case(case)
    actor = require_management(membership.user, case.building_id)
    if case.completed_at is None:
        raise ValidationError("Case work must be completed before acceptance.")
    if AcceptanceRecord.objects.filter(case=case).exists():
        raise ValidationError("Case has already been accepted.")
    if type(actual_cost_vnd) is not int or actual_cost_vnd <= 0:
        raise ValidationError("Actual cost must be a positive integer VND amount.")

    building_id = case.building_id
    invoice_original, invoice_redacted = _require_document_pair(
        invoice_original,
        invoice_redacted,
        Document.Kind.INVOICE,
        building_id,
        lock=True,
    )
    acceptance_original, acceptance_redacted = _require_document_pair(
        acceptance_original,
        acceptance_redacted,
        Document.Kind.ACCEPTANCE_REPORT,
        building_id,
        lock=True,
    )
    photo_hashes = _completion_photo_hashes(case, lock=True)
    previous_hash = _acceptance_previous_hash(case)
    acceptance_timestamp = timestamp or case.completed_at
    payload = {
        "case_id": case.pk,
        "actual_cost_vnd": actual_cost_vnd,
        "acceptance_timestamp": utc_rfc3339(acceptance_timestamp),
        "invoice_original_hash": invoice_original.sha256,
        "invoice_redacted_hash": invoice_redacted.sha256,
        "acceptance_report_original_hash": acceptance_original.sha256,
        "acceptance_report_redacted_hash": acceptance_redacted.sha256,
        "photo_hashes": photo_hashes,
    }
    event = queue_signed_event(
        event_id,
        EvidenceType.WORK_ACCEPTANCE,
        payload,
        previous_hash,
        actor,
        signature,
    )
    accepted_at = timezone.now()
    record = AcceptanceRecord.objects.create(
        case=case,
        actual_cost_vnd=actual_cost_vnd,
        invoice_original=invoice_original,
        invoice_redacted=invoice_redacted,
        acceptance_original=acceptance_original,
        acceptance_redacted=acceptance_redacted,
        membership=actor,
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        accepted_at=accepted_at,
    )
    record_audit(
        actor.user,
        actor,
        "work.accept",
        "AcceptanceRecord",
        str(record.pk),
        "accepted",
        {
            "case_id": case.pk,
            "actual_cost_vnd": actual_cost_vnd,
            "event_id": event.event_id,
        },
    )
    try:
        from lamto.notifications.hooks import notify_work_accepted

        notify_work_accepted(record)
    except Exception:
        pass
    return record
