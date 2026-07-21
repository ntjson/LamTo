import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.documents.access import _read_stored_version
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType, is_settled
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.maintenance.models import WorkOrder

from .fund import create_publication_outflow, get_or_create_fund
from .models import (
    AcceptanceRecord,
    PaymentEvidence,
    PaymentVerification,
    Proposal,
    PublicationGateFailure,
    PublicationSnapshot,
    PublishedLedgerEntry,
)


def _allocate_pk(model):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence(%s, 'id'))",
            [model._meta.db_table],
        )
        return cursor.fetchone()[0]


def allocate_publication_id() -> int:
    """Reserve a PublicationSnapshot primary key for sign-before-write."""
    return int(_allocate_pk(PublicationSnapshot))


def _locked_proposal(proposal):
    locked_id = (
        Proposal.objects.select_for_update()
        .filter(pk=getattr(proposal, "pk", None))
        .values_list("pk", flat=True)
        .first()
    )
    if locked_id is None:
        raise ValidationError("Proposal does not exist.")
    return (
        Proposal.objects.select_related(
            "work_order__case__decision",
            "current_version__outbox_event",
            "creator_membership__user",
        ).get(pk=locked_id)
    )


def _record_gate_failure(
    proposal,
    gate_code,
    actor,
    *,
    expected_hash="",
    actual_hash="",
    severity=PublicationGateFailure.Severity.BLOCKING,
):
    failure = PublicationGateFailure.objects.create(
        proposal=proposal,
        gate_code=gate_code,
        expected_hash=expected_hash or "",
        actual_hash=actual_hash or "",
        severity=severity,
        actor=actor,
    )
    if actor is not None:
        record_audit(
            actor.user,
            actor,
            "publication.gate_failure",
            "PublicationGateFailure",
            str(failure.pk),
            "denied",
            {
                "gate_code": gate_code,
                "proposal_id": proposal.pk,
                "expected_hash": expected_hash or "",
                "actual_hash": actual_hash or "",
                "action_item": "publication_integrity",
            },
        )
    return failure


def _stream_sha256(version):
    digest = hashlib.sha256()
    for chunk in _read_stored_version(version):
        digest.update(chunk)
    return digest.hexdigest()


def _confirm_document(version, expected_hash, gate_code):
    """Return (actual_hash, None) or (None, failure_dict)."""
    try:
        actual = _stream_sha256(version)
    except Exception:
        return None, {
            "gate_code": gate_code + "_UNAVAILABLE",
            "expected_hash": expected_hash or "",
            "actual_hash": "",
            "message": "Required publication document storage is unavailable.",
        }
    if actual != version.sha256 or actual != expected_hash:
        return None, {
            "gate_code": gate_code + "_MISMATCH",
            "expected_hash": expected_hash or "",
            "actual_hash": actual,
            "message": "Required publication document hash mismatch.",
        }
    return actual, None


def _require_settled(event, label):
    if event is None:
        raise ValidationError(f"{label} evidence event is required.")
    if not is_settled(event.status):
        raise ValidationError(f"{label} evidence is not settled.")
    return event


def _load_execution_chain(proposal):
    work_order = proposal.work_order
    try:
        acceptance = work_order.acceptance
    except AcceptanceRecord.DoesNotExist as exc:
        raise ValidationError("Accepted work is required before publication.") from exc
    try:
        payment = acceptance.payment
    except PaymentEvidence.DoesNotExist as exc:
        raise ValidationError("Payment evidence is required before publication.") from exc
    try:
        verification = payment.verification
    except PaymentVerification.DoesNotExist as exc:
        raise ValidationError("Payment verification is required before publication.") from exc
    return acceptance, payment, verification


def _forbidden_publisher_user_ids(proposal, payment):
    forbidden = {proposal.creator_membership.user_id}
    forbidden.add(payment.recorder.user_id)
    return forbidden


def _assert_publisher_eligible(actor, proposal, payment):
    forbidden = _forbidden_publisher_user_ids(proposal, payment)
    if actor.user_id in forbidden:
        raise PermissionDenied(
            "Publisher must not be the proposal creator or payment recorder."
        )


def _resident_payload(
    proposal,
    version,
    acceptance,
    payment,
    verification,
    document_hashes,
):
    work_order = proposal.work_order
    case = work_order.case
    report_id = case.decision.report_id
    payload = {
        "report_id": report_id,
        "case_id": case.pk,
        "work_order_id": work_order.pk,
        "proposal_id": proposal.pk,
        "proposal_version": version.number,
        "proposed_amount_vnd": version.amount_vnd,
        "actual_cost_vnd": acceptance.actual_cost_vnd,
        "contractor_name": version.contractor_name,
        "document_hashes": document_hashes,
        "payment_verification": {
            "decision": verification.decision,
            "payment_id": payment.pk,
            "verification_event_hash": verification.outbox_event.payload_hash,
        },
    }
    return payload


def _collect_document_checks(
    proposal, version, acceptance, payment, verification, using="default"
):
    from lamto.documents.models import DocumentVersion

    checks = []
    for item in version.snapshot.get("quotation_versions", []):
        original = DocumentVersion.objects.using(using).get(pk=item["original_id"])
        redacted = DocumentVersion.objects.using(using).get(pk=item["redacted_id"])
        checks.append((original, item["original_sha256"], "QUOTATION_ORIGINAL"))
        checks.append((redacted, item["redacted_sha256"], "QUOTATION_REDACTED"))
    acc_payload = acceptance.outbox_event.payload
    checks.extend(
        [
            (
                acceptance.invoice_original,
                acc_payload["invoice_original_hash"],
                "INVOICE_ORIGINAL",
            ),
            (
                acceptance.invoice_redacted,
                acc_payload["invoice_redacted_hash"],
                "INVOICE_REDACTED",
            ),
            (
                acceptance.acceptance_original,
                acc_payload["acceptance_report_original_hash"],
                "ACCEPTANCE_ORIGINAL",
            ),
            (
                acceptance.acceptance_redacted,
                acc_payload["acceptance_report_redacted_hash"],
                "ACCEPTANCE_REDACTED",
            ),
        ]
    )
    pay_payload = payment.outbox_event.payload
    checks.extend(
        [
            (
                payment.proof_original,
                pay_payload["payment_proof_original_hash"],
                "PAYMENT_PROOF_ORIGINAL",
            ),
            (
                payment.proof_redacted,
                pay_payload["payment_proof_redacted_hash"],
                "PAYMENT_PROOF_REDACTED",
            ),
        ]
    )
    _ = verification
    return checks


def build_publication_evidence_payload(
    publication_id,
    prerequisite_event_hashes,
    resident_payload_hash,
    document_hashes,
    timestamp,
):
    if type(publication_id) is not int or publication_id <= 0:
        raise ValidationError("Publication id must be a positive integer.")
    if not isinstance(prerequisite_event_hashes, list) or not prerequisite_event_hashes:
        raise ValidationError("Prerequisite event hashes are required.")
    if not isinstance(document_hashes, list) or not document_hashes:
        raise ValidationError("Document hashes are required.")
    if not isinstance(timestamp, type(timezone.now())) or timestamp.tzinfo is None:
        raise ValidationError("Publication timestamp must be timezone-aware.")
    payload = {
        "publication_id": publication_id,
        "prerequisite_event_hashes": prerequisite_event_hashes,
        "resident_payload_hash": resident_payload_hash,
        "document_hashes": document_hashes,
        "publication_timestamp": utc_rfc3339(timestamp),
    }
    return payload


def build_publication_evidence_typed_data(
    proposal,
    membership,
    publication_id,
    prerequisite_event_hashes,
    resident_payload,
    document_hashes,
    event_id,
    timestamp=None,
    previous_hash=None,
):
    ts = timestamp or timezone.now()
    resident_payload_hash = payload_hash(resident_payload)
    payload = build_publication_evidence_payload(
        publication_id,
        prerequisite_event_hashes,
        resident_payload_hash,
        document_hashes,
        ts,
    )
    if previous_hash is None:
        previous_hash = "0x" + "00" * 32
    return build_evidence_typed_data(
        event_id,
        EvidenceType.PUBLICATION_SNAPSHOT,
        "0x" + payload_hash(payload),
        previous_hash,
    )


def build_publication_sign_package(proposal, publisher, *, event_id, publication_id, timestamp):
    """Compute the exact EIP-712 package MetaMask must sign for prepare_publication.

    Read-only: does not write snapshots. Raises ValidationError/PermissionDenied
    with the same gates as prepare_publication (except dual-control denial, which
    is still enforced on write).
    """
    proposal = (
        Proposal.objects.select_related(
            "work_order__case__decision",
            "current_version__outbox_event",
            "creator_membership__user",
        ).get(pk=proposal.pk)
    )
    work_order = proposal.work_order
    actor = require_management(publisher.user, work_order.case.building_id)
    if PublicationSnapshot.objects.filter(proposal=proposal).exists():
        raise ValidationError("Publication snapshot already exists for this proposal.")
    if PublishedLedgerEntry.objects.filter(proposal=proposal).exists():
        raise ValidationError("Proposal is already published.")

    version = proposal.current_version
    if version is None:
        raise ValidationError("A current proposal version is required.")
    acceptance, payment, verification = _load_execution_chain(proposal)
    if verification.decision != PaymentVerification.Decision.VERIFIED:
        raise ValidationError("Payment must be VERIFIED before publication.")
    if payment.external_status != PaymentEvidence.ExternalStatus.COMPLETED:
        raise ValidationError("Payment evidence status must be COMPLETED.")

    prerequisite_events = []
    prerequisite_events.append(version.outbox_event)

    prerequisite_events.extend(
        [acceptance.outbox_event, payment.outbox_event, verification.outbox_event]
    )
    for event in prerequisite_events:
        _require_settled(event, "Prerequisite")

    document_checks = _collect_document_checks(
        proposal, version, acceptance, payment, verification
    )
    document_hashes = []
    for version_doc, expected_hash, gate in document_checks:
        actual, failure = _confirm_document(version_doc, expected_hash, gate)
        if failure is not None:
            raise ValidationError(failure.get("message") or "Publication document check failed.")
        document_hashes.append(actual)
    document_hashes = sorted(set(document_hashes))
    resident_payload = _resident_payload(
        proposal,
        version,
        acceptance,
        payment,
        verification,
        document_hashes,
    )
    if type(publication_id) is not int or publication_id <= 0:
        raise ValidationError("Publication id must be a positive integer.")
    prerequisite_event_hashes = [event.payload_hash for event in prerequisite_events]
    previous_hash = "0x" + verification.outbox_event.payload_hash
    typed = build_publication_evidence_typed_data(
        proposal,
        actor,
        publication_id,
        prerequisite_event_hashes,
        resident_payload,
        document_hashes,
        event_id,
        timestamp=timestamp,
        previous_hash=previous_hash,
    )
    return {
        "typed_data": typed,
        "publication_id": publication_id,
        "event_id": event_id,
        "timestamp": timestamp,
        "forbidden_publisher": actor.user_id in _forbidden_publisher_user_ids(proposal, payment),
    }


def prepare_publication(
    proposal,
    publisher,
    signature,
    event_id,
    publication_id=None,
    timestamp=None,
) -> PublicationSnapshot:
    gate_failure = None
    denied = False
    denied_actor = None
    denied_proposal = None
    snapshot = None
    with transaction.atomic():
        proposal = _locked_proposal(proposal)
        work_order = proposal.work_order
        actor = require_management(publisher.user, work_order.case.building_id)
        if PublicationSnapshot.objects.filter(proposal=proposal).exists():
            raise ValidationError("Publication snapshot already exists for this proposal.")
        if PublishedLedgerEntry.objects.filter(proposal=proposal).exists():
            raise ValidationError("Proposal is already published.")

        version = proposal.current_version
        if version is None:
            raise ValidationError("A current proposal version is required.")
        acceptance, payment, verification = _load_execution_chain(proposal)
        if verification.decision != PaymentVerification.Decision.VERIFIED:
            raise ValidationError("Payment must be VERIFIED before publication.")
        if payment.external_status != PaymentEvidence.ExternalStatus.COMPLETED:
            raise ValidationError("Payment evidence status must be COMPLETED.")

        prerequisite_events = []
        prerequisite_events.append(version.outbox_event)

        prerequisite_events.extend(
            [
                acceptance.outbox_event,
                payment.outbox_event,
                verification.outbox_event,
            ]
        )
        for event in prerequisite_events:
            _require_settled(event, "Prerequisite")

        if actor.user_id in _forbidden_publisher_user_ids(proposal, payment):
            denied = True
            denied_actor = actor
            denied_proposal = proposal
        else:
            document_checks = _collect_document_checks(
                proposal, version, acceptance, payment, verification
            )
            document_hashes = []
            for version_doc, expected_hash, gate in document_checks:
                actual, failure = _confirm_document(version_doc, expected_hash, gate)
                if failure is not None:
                    gate_failure = {
                        "proposal": proposal,
                        "actor": actor,
                        **failure,
                    }
                    break
                document_hashes.append(actual)
            if gate_failure is None:
                document_hashes = sorted(set(document_hashes))
                resident_payload = _resident_payload(
                    proposal,
                    version,
                    acceptance,
                    payment,
                    verification,
                    document_hashes,
                )

                if publication_id is None:
                    publication_id = allocate_publication_id()
                if type(publication_id) is not int or publication_id <= 0:
                    raise ValidationError("Publication id must be a positive integer.")
                if PublicationSnapshot.objects.filter(pk=publication_id).exists():
                    raise ValidationError("Publication id is already used.")

                publication_timestamp = timestamp or timezone.now()
                resident_payload_hash = payload_hash(resident_payload)
                prerequisite_event_hashes = [
                    event.payload_hash for event in prerequisite_events
                ]
                previous_hash = "0x" + verification.outbox_event.payload_hash
                payload = build_publication_evidence_payload(
                    publication_id,
                    prerequisite_event_hashes,
                    resident_payload_hash,
                    document_hashes,
                    publication_timestamp,
                )
                event = queue_signed_event(
                    event_id,
                    EvidenceType.PUBLICATION_SNAPSHOT,
                    payload,
                    previous_hash,
                    actor,
                    signature,
                )
                snapshot = PublicationSnapshot(
                    pk=publication_id,
                    proposal=proposal,
                    resident_payload=resident_payload,
                    resident_payload_hash=resident_payload_hash,
                    publisher=actor,
                    wallet=event.signer_wallet,
                    signature=event.signature,
                    outbox_event=event,
                    prepared_at=timezone.now(),
                )
                snapshot.save(force_insert=True)
                record_audit(
                    actor.user,
                    actor,
                    "publication.prepare",
                    "PublicationSnapshot",
                    str(snapshot.pk),
                    "accepted",
                    {
                        "proposal_id": proposal.pk,
                        "event_id": event.event_id,
                        "resident_payload_hash": resident_payload_hash,
                    },
                )

    if denied:
        _record_gate_failure(denied_proposal, "PUBLISHER_INELIGIBLE", denied_actor)
        record_audit(
            denied_actor.user,
            denied_actor,
            "publication.prepare",
            "Proposal",
            str(denied_proposal.pk),
            "denied",
            {"reason": "publisher dual-control violation"},
        )
        raise PermissionDenied(
            "Publisher must not be the proposal creator or payment recorder."
        )
    if gate_failure is not None:
        _record_gate_failure(
            gate_failure["proposal"],
            gate_failure["gate_code"],
            gate_failure["actor"],
            expected_hash=gate_failure.get("expected_hash", ""),
            actual_hash=gate_failure.get("actual_hash", ""),
        )
        raise ValidationError(gate_failure["message"])
    return snapshot


@transaction.atomic
def finalize_publication(snapshot_id) -> PublishedLedgerEntry:
    locked_id = (
        PublicationSnapshot.objects.select_for_update()
        .filter(pk=snapshot_id)
        .values_list("pk", flat=True)
        .first()
    )
    if locked_id is None:
        raise ValidationError("Publication snapshot does not exist.")
    snapshot = (
        PublicationSnapshot.objects.select_related(
            "outbox_event",
            "proposal__work_order__case",
            "proposal__current_version",
            "publisher",
        ).get(pk=locked_id)
    )
    existing = PublishedLedgerEntry.objects.filter(snapshot=snapshot).first()
    if existing is not None:
        return existing
    if not is_settled(snapshot.outbox_event.status):
        raise ValidationError(
            "Publication snapshot must be settled before finalization."
        )
    proposal = snapshot.proposal
    if PublishedLedgerEntry.objects.filter(proposal=proposal).exists():
        return PublishedLedgerEntry.objects.get(proposal=proposal)

    acceptance, payment, verification = _load_execution_chain(proposal)
    if verification.decision != PaymentVerification.Decision.VERIFIED:
        raise ValidationError("Payment must remain VERIFIED at finalization.")
    version = proposal.current_version
    work_order = proposal.work_order
    if work_order.status != WorkOrder.Status.ACCEPTED:
        # Acceptance is required; status should already be ACCEPTED.
        pass

    fund = get_or_create_fund(work_order.case.building_id)
    published_at = timezone.now()
    create_publication_outflow(
        fund=fund,
        proposal=proposal,
        publication=snapshot,
        amount_vnd=acceptance.actual_cost_vnd,
        recorded_at=published_at,
    )
    entry, created = PublishedLedgerEntry.objects.get_or_create(
        proposal=proposal,
        defaults={
            "snapshot": snapshot,
            "work_order": work_order,
            "case": work_order.case,
            "payment": payment,
            "actual_cost_vnd": acceptance.actual_cost_vnd,
            "contractor_name": version.contractor_name,
            "published_at": published_at,
        },
    )
    if not created and entry.snapshot_id != snapshot.pk:
        raise ValidationError("Proposal already has a different published ledger entry.")
    if created:
        record_audit(
            snapshot.publisher.user,
            snapshot.publisher,
            "publication.finalize",
            "PublishedLedgerEntry",
            str(entry.pk),
            "accepted",
            {
                "proposal_id": proposal.pk,
                "snapshot_id": snapshot.pk,
                "actual_cost_vnd": entry.actual_cost_vnd,
            },
        )
        try:
            from lamto.notifications.hooks import notify_publication

            notify_publication(entry)
        except Exception:
            pass
    return entry
