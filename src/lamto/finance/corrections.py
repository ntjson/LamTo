from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from lamto.accounts.capabilities import (
    CORRECTION_APPROVE,
    CORRECTION_CREATE,
    LEDGER_PUBLISH,
)
from lamto.accounts.models import Organization
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit
from lamto.documents.models import DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType, is_settled
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.fund import get_or_create_fund
from lamto.finance.models import (
    Correction,
    CorrectionDecision,
    CorrectionDocument,
    CorrectionPublicationSnapshot,
    MaintenanceFundEntry,
    PublishedLedgerEntry,
)
from lamto.finance.publication import _forbidden_publisher_user_ids, _load_execution_chain

ZERO_HASH = "0x" + "00" * 32
ZERO_HASH_BARE = "00" * 32

STAGE_BY_ORGANIZATION_KIND = {
    Organization.Kind.BOARD: CorrectionDecision.Stage.BOARD,
    Organization.Kind.RESIDENT_REP: CorrectionDecision.Stage.RESIDENT_REP,
}


def _allocate_pk(model):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence(%s, 'id'))",
            [model._meta.db_table],
        )
        return cursor.fetchone()[0]


def allocate_correction_id() -> int:
    return int(_allocate_pk(Correction))


def allocate_correction_publication_id() -> int:
    return int(_allocate_pk(CorrectionPublicationSnapshot))


def _reason_digest(reason):
    return payload_hash({"reason": reason})


def _locked_entry(entry):
    locked_id = (
        PublishedLedgerEntry.objects.select_for_update()
        .filter(pk=getattr(entry, "pk", None))
        .values_list("pk", flat=True)
        .first()
    )
    if locked_id is None:
        raise ValidationError("Published ledger entry does not exist.")
    return PublishedLedgerEntry.objects.select_related(
        "snapshot__outbox_event",
        "proposal__creator_membership",
        "proposal__current_version",
        "proposal__work_order__case",
        "payment__recorder",
        "case",
    ).get(pk=locked_id)


def _locked_correction(correction):
    locked_id = (
        Correction.objects.select_for_update()
        .filter(pk=getattr(correction, "pk", None))
        .values_list("pk", flat=True)
        .first()
    )
    if locked_id is None:
        raise ValidationError("Correction does not exist.")
    return Correction.objects.select_related(
        "original_entry__snapshot__outbox_event",
        "original_entry__proposal__creator_membership",
        "original_entry__proposal__current_version",
        "original_entry__payment__recorder",
        "original_entry__case",
        "outbox_event",
        "operator",
    ).get(pk=locked_id)


def _require_clean_versions(document_versions, building_id):
    if not document_versions:
        raise ValidationError("Correction replacement evidence documents are required.")
    ids = [getattr(v, "pk", v) for v in document_versions]
    versions = list(
        DocumentVersion.objects.select_related("document")
        .select_for_update()
        .filter(pk__in=ids)
    )
    if len(versions) != len(set(ids)):
        raise ValidationError("Correction document versions must still exist.")
    for version in versions:
        if (
            version.document.building_id != building_id
            or version.scan_status != DocumentVersion.ScanStatus.CLEAN
        ):
            raise ValidationError(
                "Correction evidence must be clean and belong to the building."
            )
    return versions


def _validate_replacement_payload(payload, original_entry):
    if not isinstance(payload, dict):
        raise ValidationError("Replacement payload must be an object.")
    amount = payload.get("actual_cost_vnd")
    if type(amount) is not int or amount <= 0:
        raise ValidationError("Replacement actual_cost_vnd must be a positive integer.")
    contractor = payload.get("contractor_name", original_entry.contractor_name)
    if not isinstance(contractor, str) or not contractor.strip():
        raise ValidationError("Replacement contractor_name is required.")
    return {
        "actual_cost_vnd": amount,
        "contractor_name": contractor.strip(),
        **{
            key: value
            for key, value in payload.items()
            if key not in {"actual_cost_vnd", "contractor_name"}
        },
    }


def build_correction_evidence_payload(
    correction_id,
    original_event_id,
    original_hash,
    replacement_hashes,
    reason,
    decision,
    actor_organization_id,
    publisher_snapshot_hash,
    timestamp,
):
    if type(correction_id) is not int or correction_id <= 0:
        raise ValidationError("Correction id must be a positive integer.")
    decision = str(getattr(decision, "value", decision))
    if decision not in CorrectionDecision.Decision.values:
        raise ValidationError("Correction decision is invalid.")
    if type(actor_organization_id) is not int or actor_organization_id <= 0:
        raise ValidationError("Actor organization id must be a positive integer.")
    if not isinstance(replacement_hashes, list) or not replacement_hashes:
        raise ValidationError("Replacement hashes are required.")
    if not isinstance(timestamp, type(timezone.now())) or timestamp.tzinfo is None:
        raise ValidationError("Correction timestamp must be timezone-aware.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Correction reason is required.")
    event_id = str(original_event_id).lower()
    if not event_id.startswith("0x"):
        event_id = "0x" + event_id
    original = str(original_hash).removeprefix("0x")
    publisher_hash = str(publisher_snapshot_hash).removeprefix("0x")
    return {
        "correction_id": correction_id,
        "original_event_id": event_id,
        "original_hash": original,
        "replacement_hashes": [
            str(item).removeprefix("0x") for item in replacement_hashes
        ],
        "reason_digest": _reason_digest(reason.strip()),
        "decision": decision,
        "actor_organization_id": actor_organization_id,
        "publisher_snapshot_hash": publisher_hash,
        "correction_timestamp": utc_rfc3339(timestamp),
    }


def build_correction_evidence_typed_data(
    correction_id,
    original_event_id,
    original_hash,
    replacement_hashes,
    reason,
    decision,
    actor_organization_id,
    publisher_snapshot_hash,
    event_id,
    timestamp=None,
    previous_hash=None,
):
    ts = timestamp or timezone.now()
    payload = build_correction_evidence_payload(
        correction_id,
        original_event_id,
        original_hash,
        replacement_hashes,
        reason,
        decision,
        actor_organization_id,
        publisher_snapshot_hash,
        ts,
    )
    return build_evidence_typed_data(
        event_id,
        EvidenceType.CORRECTION,
        "0x" + payload_hash(payload),
        previous_hash or ZERO_HASH,
    )


def _replacement_hashes(versions):
    return sorted({version.sha256 for version in versions})


def _correction_previous_hash(correction, stage=None):
    """Previous evidence hash for a correction stage."""
    if stage is None:
        # creation: original publication
        return "0x" + correction.original_entry.snapshot.outbox_event.payload_hash
    if stage == CorrectionDecision.Stage.BOARD:
        return "0x" + correction.outbox_event.payload_hash
    if stage == CorrectionDecision.Stage.RESIDENT_REP:
        board = (
            CorrectionDecision.objects.select_related("outbox_event")
            .filter(correction=correction, stage=CorrectionDecision.Stage.BOARD)
            .first()
        )
        if board is None:
            raise ValidationError("Board correction approval is required first.")
        return "0x" + board.outbox_event.payload_hash
    raise ValidationError("Unknown correction stage.")


def _publication_previous_hash(correction):
    rep = (
        CorrectionDecision.objects.select_related("outbox_event")
        .filter(
            correction=correction,
            stage=CorrectionDecision.Stage.RESIDENT_REP,
            decision=CorrectionDecision.Decision.APPROVE,
        )
        .first()
    )
    if rep is None:
        raise ValidationError(
            "Resident-representative correction approval is required before publication."
        )
    return "0x" + rep.outbox_event.payload_hash


@transaction.atomic
def create_correction(
    entry,
    operator,
    reason,
    replacement_payload,
    document_versions,
    signature,
    event_id,
    correction_id=None,
    timestamp=None,
) -> Correction:
    entry = _locked_entry(entry)
    if not is_settled(entry.snapshot.outbox_event.status):
        raise ValidationError("Only published entries with settled snapshots may be corrected.")
    actor = require_capability(operator.user, operator.pk, CORRECTION_CREATE)
    if actor.organization.kind != Organization.Kind.OPERATOR:
        raise PermissionDenied("Only an operator membership may create corrections.")
    building_id = entry.case.building_id
    if actor.organization.building_id != building_id:
        raise PermissionDenied("Operator must belong to the entry building.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Correction reason is required.")
    payload = _validate_replacement_payload(replacement_payload, entry)
    versions = _require_clean_versions(document_versions, building_id)

    if correction_id is None:
        correction_id = allocate_correction_id()
    if type(correction_id) is not int or correction_id <= 0:
        raise ValidationError("Correction id must be a positive integer.")
    if Correction.objects.filter(pk=correction_id).exists():
        raise ValidationError("Correction id is already used.")

    created_at = timestamp or timezone.now()
    replacement_hashes = _replacement_hashes(versions)
    original_event = entry.snapshot.outbox_event
    evidence_payload = build_correction_evidence_payload(
        correction_id,
        original_event.event_id,
        original_event.payload_hash,
        replacement_hashes,
        reason,
        CorrectionDecision.Decision.APPROVE,
        actor.organization_id,
        ZERO_HASH_BARE,
        created_at,
    )
    previous_hash = "0x" + original_event.payload_hash
    event = queue_signed_event(
        event_id,
        EvidenceType.CORRECTION,
        evidence_payload,
        previous_hash,
        actor,
        signature,
    )
    correction = Correction(
        pk=correction_id,
        original_entry=entry,
        operator=actor,
        reason=reason.strip(),
        replacement_payload=payload,
        replacement_payload_hash=payload_hash(payload),
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        created_at=created_at,
    )
    correction.save(force_insert=True)
    for version in versions:
        CorrectionDocument.objects.create(correction=correction, version=version)
    record_audit(
        actor.user,
        actor,
        "correction.create",
        "Correction",
        str(correction.pk),
        "accepted",
        {
            "original_entry_id": entry.pk,
            "event_id": event.event_id,
            "replacement_payload_hash": correction.replacement_payload_hash,
        },
    )
    try:
        from lamto.notifications.hooks import notify_correction_status

        notify_correction_status(correction, "PENDING")
    except Exception:
        pass
    return correction


@transaction.atomic
def decide_correction(
    correction,
    membership,
    stage,
    decision,
    reason,
    signature,
    event_id,
    timestamp=None,
) -> CorrectionDecision:
    correction = _locked_correction(correction)
    actor = require_capability(membership.user, membership.pk, CORRECTION_APPROVE)
    expected_stage = STAGE_BY_ORGANIZATION_KIND.get(actor.organization.kind)
    if expected_stage is None:
        raise PermissionDenied(
            "Only Board and resident-representative memberships may decide corrections."
        )
    if stage != expected_stage:
        raise ValidationError("Correction stage does not match the actor organization.")
    if actor.organization.building_id != correction.original_entry.case.building_id:
        raise PermissionDenied("Approver must belong to the entry building.")
    decision = str(getattr(decision, "value", decision))
    if decision not in CorrectionDecision.Decision.values:
        raise ValidationError("Correction decision is invalid.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Correction decision reason is required.")
    if CorrectionDecision.objects.filter(correction=correction, stage=stage).exists():
        raise ValidationError("This correction stage has already been decided.")

    if stage == CorrectionDecision.Stage.RESIDENT_REP:
        board = (
            CorrectionDecision.objects.select_for_update()
            .filter(correction=correction, stage=CorrectionDecision.Stage.BOARD)
            .first()
        )
        if board is None or board.decision != CorrectionDecision.Decision.APPROVE:
            raise ValidationError(
                "Board correction approval is required before resident co-approval."
            )

    if not is_settled(correction.outbox_event.status):
        raise ValidationError("Correction creation must be settled before decisions.")

    versions = [link.version for link in correction.documents.select_related("version")]
    replacement_hashes = _replacement_hashes(versions)
    decided_at = timestamp or timezone.now()
    original_event = correction.original_entry.snapshot.outbox_event
    evidence_payload = build_correction_evidence_payload(
        correction.pk,
        original_event.event_id,
        original_event.payload_hash,
        replacement_hashes,
        reason,
        decision,
        actor.organization_id,
        ZERO_HASH_BARE,
        decided_at,
    )
    previous_hash = _correction_previous_hash(correction, stage)
    event = queue_signed_event(
        event_id,
        EvidenceType.CORRECTION,
        evidence_payload,
        previous_hash,
        actor,
        signature,
    )
    row = CorrectionDecision.objects.create(
        correction=correction,
        stage=stage,
        decision=decision,
        reason=reason.strip(),
        membership=actor,
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        decided_at=decided_at,
    )
    record_audit(
        actor.user,
        actor,
        "correction.approve" if decision == CorrectionDecision.Decision.APPROVE else "correction.reject",
        "CorrectionDecision",
        str(row.pk),
        "accepted" if decision == CorrectionDecision.Decision.APPROVE else "rejected",
        {
            "correction_id": correction.pk,
            "stage": stage,
            "decision": decision,
            "event_id": event.event_id,
        },
    )
    try:
        from lamto.notifications.hooks import notify_correction_status

        notify_correction_status(correction, decision)
    except Exception:
        pass
    return row


def _assert_correction_publisher_eligible(actor, correction, payment):
    forbidden = _forbidden_publisher_user_ids(correction.original_entry.proposal, payment)
    board = (
        CorrectionDecision.objects.select_related("membership")
        .filter(
            correction=correction,
            stage=CorrectionDecision.Stage.BOARD,
            decision=CorrectionDecision.Decision.APPROVE,
        )
        .first()
    )
    if board is not None:
        forbidden.add(board.membership.user_id)
    if actor.user_id in forbidden:
        raise PermissionDenied(
            "Correction publisher must differ from original excluded actors and the correction Board approver."
        )


def _correction_resident_payload(correction):
    entry = correction.original_entry
    versions = [link.version for link in correction.documents.select_related("version")]
    decisions = {
        row.stage: {
            "membership_id": row.membership_id,
            "decision": row.decision,
            "user_id": row.membership.user_id,
        }
        for row in correction.decisions.select_related("membership")
    }
    return {
        "correction_id": correction.pk,
        "original_entry_id": entry.pk,
        "original_actual_cost_vnd": entry.actual_cost_vnd,
        "replacement_actual_cost_vnd": correction.replacement_payload["actual_cost_vnd"],
        "replacement_contractor_name": correction.replacement_payload.get(
            "contractor_name", entry.contractor_name
        ),
        "reason": correction.reason,
        "replacement_payload_hash": correction.replacement_payload_hash,
        "document_hashes": _replacement_hashes(versions),
        "decisions": decisions,
        "original_publication_event_id": entry.snapshot.outbox_event.event_id,
        "original_publication_hash": entry.snapshot.outbox_event.payload_hash,
    }


@transaction.atomic
def prepare_correction_publication(
    correction,
    publisher,
    signature,
    event_id,
    snapshot_id=None,
    timestamp=None,
) -> CorrectionPublicationSnapshot:
    correction = _locked_correction(correction)
    actor = require_capability(publisher.user, publisher.pk, LEDGER_PUBLISH)
    if actor.organization.kind != Organization.Kind.BOARD:
        raise PermissionDenied("Only a Board membership may publish a correction.")
    if actor.organization.building_id != correction.original_entry.case.building_id:
        raise PermissionDenied("Board must belong to the entry building.")
    if CorrectionPublicationSnapshot.objects.filter(correction=correction).exists():
        raise ValidationError("Correction publication snapshot already exists.")

    board = (
        CorrectionDecision.objects.select_related("outbox_event", "membership")
        .filter(correction=correction, stage=CorrectionDecision.Stage.BOARD)
        .first()
    )
    rep = (
        CorrectionDecision.objects.select_related("outbox_event", "membership")
        .filter(correction=correction, stage=CorrectionDecision.Stage.RESIDENT_REP)
        .first()
    )
    if (
        board is None
        or rep is None
        or board.decision != CorrectionDecision.Decision.APPROVE
        or rep.decision != CorrectionDecision.Decision.APPROVE
    ):
        raise ValidationError(
            "Correction requires Board and resident-representative approvals before publication."
        )
    for label, event in (
        ("Correction creation", correction.outbox_event),
        ("Board correction decision", board.outbox_event),
        ("Representative correction decision", rep.outbox_event),
    ):
        if not is_settled(event.status):
            raise ValidationError(f"{label} is not settled.")

    from lamto.finance.models import PaymentVerification

    _, payment, verification = _load_execution_chain(correction.original_entry.proposal)
    if verification.decision != PaymentVerification.Decision.VERIFIED:
        raise ValidationError("Original payment must remain VERIFIED.")
    _assert_correction_publisher_eligible(actor, correction, payment)

    if snapshot_id is None:
        snapshot_id = allocate_correction_publication_id()
    if type(snapshot_id) is not int or snapshot_id <= 0:
        raise ValidationError("Correction publication id must be a positive integer.")
    if CorrectionPublicationSnapshot.objects.filter(pk=snapshot_id).exists():
        raise ValidationError("Correction publication id is already used.")

    prepared_at = timestamp or timezone.now()
    resident_payload = _correction_resident_payload(correction)
    resident_payload_hash = payload_hash(resident_payload)
    versions = [link.version for link in correction.documents.select_related("version")]
    replacement_hashes = _replacement_hashes(versions)
    original_event = correction.original_entry.snapshot.outbox_event
    evidence_payload = build_correction_evidence_payload(
        correction.pk,
        original_event.event_id,
        original_event.payload_hash,
        replacement_hashes,
        correction.reason,
        CorrectionDecision.Decision.APPROVE,
        actor.organization_id,
        resident_payload_hash,
        prepared_at,
    )
    previous_hash = _publication_previous_hash(correction)
    event = queue_signed_event(
        event_id,
        EvidenceType.CORRECTION,
        evidence_payload,
        previous_hash,
        actor,
        signature,
    )
    snapshot = CorrectionPublicationSnapshot(
        pk=snapshot_id,
        correction=correction,
        resident_payload=resident_payload,
        resident_payload_hash=resident_payload_hash,
        publisher=actor,
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        prepared_at=prepared_at,
    )
    snapshot.save(force_insert=True)
    record_audit(
        actor.user,
        actor,
        "correction.publication.prepare",
        "CorrectionPublicationSnapshot",
        str(snapshot.pk),
        "accepted",
        {
            "correction_id": correction.pk,
            "event_id": event.event_id,
            "resident_payload_hash": resident_payload_hash,
        },
    )
    return snapshot


def _current_effective_cost_vnd(entry, exclude_correction_id=None) -> int:
    """Effective actual cost after prior finalized amount corrections.

    Fund postings keep the original OUTFLOW and adjust via REVERSAL/REPLACEMENT.
    The latest REPLACEMENT magnitude (excluding the correction being finalized)
    is the current effective cost; otherwise the immutable original amount.
    """
    qs = MaintenanceFundEntry.objects.filter(
        correction__original_entry_id=entry.pk,
        entry_type=MaintenanceFundEntry.EntryType.REPLACEMENT,
    )
    if exclude_correction_id is not None:
        qs = qs.exclude(correction_id=exclude_correction_id)
    latest = (
        qs.order_by("-recorded_at", "-pk").values_list("amount_vnd", flat=True).first()
    )
    if latest is None:
        return entry.actual_cost_vnd
    return abs(int(latest))


def _create_correction_fund_entries(correction, recorded_at):
    entry = correction.original_entry
    current_amount = _current_effective_cost_vnd(
        entry, exclude_correction_id=correction.pk
    )
    new_amount = correction.replacement_payload["actual_cost_vnd"]
    if new_amount == current_amount:
        return None, None

    fund = get_or_create_fund(entry.case.building_id)
    reverse_key = f"REVERSAL:correction:{correction.pk}"
    replace_key = f"REPLACEMENT:correction:{correction.pk}"
    reverse = MaintenanceFundEntry.objects.filter(source_key=reverse_key).first()
    if reverse is None:
        reverse = MaintenanceFundEntry.objects.create(
            fund=fund,
            entry_type=MaintenanceFundEntry.EntryType.REVERSAL,
            amount_vnd=current_amount,  # undo current effective outflow, not always original
            proposal=entry.proposal,
            publication=entry.snapshot,
            correction=correction,
            source_key=reverse_key,
            recorded_at=recorded_at,
        )
    replacement = MaintenanceFundEntry.objects.filter(source_key=replace_key).first()
    if replacement is None:
        replacement = MaintenanceFundEntry.objects.create(
            fund=fund,
            entry_type=MaintenanceFundEntry.EntryType.REPLACEMENT,
            amount_vnd=-new_amount,
            proposal=entry.proposal,
            publication=entry.snapshot,
            correction=correction,
            source_key=replace_key,
            recorded_at=recorded_at,
        )
    return reverse, replacement


@transaction.atomic
def finalize_correction_publication(snapshot_id) -> Correction:
    locked_id = (
        CorrectionPublicationSnapshot.objects.select_for_update()
        .filter(pk=snapshot_id)
        .values_list("pk", flat=True)
        .first()
    )
    if locked_id is None:
        raise ValidationError("Correction publication snapshot does not exist.")
    snapshot = (
        CorrectionPublicationSnapshot.objects.select_related(
            "outbox_event",
            "correction__original_entry__proposal__work_order__case",
            "correction__original_entry__snapshot",
            "publisher",
        ).get(pk=locked_id)
    )
    correction = snapshot.correction
    if not is_settled(snapshot.outbox_event.status):
        raise ValidationError(
            "Correction publication snapshot must be settled before finalization."
        )
    if not correction.board_and_rep_approved:
        raise ValidationError("Correction approvals must remain APPROVE at finalization.")

    published_at = timezone.now()
    reverse, replacement = _create_correction_fund_entries(correction, published_at)
    # Idempotent: fund entries use unique source_key; no mutation of original records.
    from lamto.audit.models import AuditEvent

    if not AuditEvent.objects.filter(
        action="correction.publication.finalize",
        target_type="Correction",
        target_id=str(correction.pk),
        result="accepted",
    ).exists():
        record_audit(
            snapshot.publisher.user,
            snapshot.publisher,
            "correction.publication.finalize",
            "Correction",
            str(correction.pk),
            "accepted",
            {
                "snapshot_id": snapshot.pk,
                "reverse_fund_entry_id": reverse.pk if reverse else None,
                "replacement_fund_entry_id": replacement.pk if replacement else None,
                "original_entry_id": correction.original_entry_id,
            },
        )
    return correction
