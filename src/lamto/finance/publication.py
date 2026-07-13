import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from lamto.accounts.capabilities import LEDGER_PUBLISH
from lamto.accounts.models import Organization
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit
from lamto.documents.access import _read_stored_version
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.maintenance.models import WorkOrder

from .fund import create_publication_outflow, get_or_create_fund
from .models import (
    AcceptanceRecord,
    ApprovalDecision,
    EmergencyAuthorization,
    EmergencyRatification,
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
                "notify_roles": ["BOARD", "AUDITOR"],
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


def _require_confirmed(event, label):
    if event is None:
        raise ValidationError(f"{label} evidence event is required.")
    if event.status != BlockchainOutboxEvent.Status.CONFIRMED:
        raise ValidationError(f"{label} evidence is not chain-confirmed.")
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


def _board_approval(version):
    return (
        ApprovalDecision.objects.select_related("outbox_event", "membership__user")
        .filter(
            version=version,
            stage=ApprovalDecision.Stage.BOARD,
            decision=ApprovalDecision.Decision.APPROVE,
        )
        .first()
    )


def _rep_approval(version):
    return (
        ApprovalDecision.objects.select_related("outbox_event", "membership__user")
        .filter(
            version=version,
            stage=ApprovalDecision.Stage.RESIDENT_REP,
            decision=ApprovalDecision.Decision.APPROVE,
        )
        .first()
    )


def _forbidden_publisher_user_ids(proposal, payment):
    forbidden = {proposal.creator_membership.user_id}
    version = proposal.current_version
    if version is not None and proposal.mode == Proposal.Mode.NORMAL:
        board = _board_approval(version)
        if board is not None:
            forbidden.add(board.membership.user_id)
    forbidden.add(payment.recorder.user_id)
    return forbidden


def _assert_publisher_eligible(actor, proposal, payment):
    forbidden = _forbidden_publisher_user_ids(proposal, payment)
    if actor.user_id in forbidden:
        raise PermissionDenied(
            "Publisher must not be the proposal creator, Board proposal approver, or payment recorder."
        )


def _emergency_context(proposal, now):
    work_order = proposal.work_order
    try:
        authorization = work_order.emergency_authorization
    except EmergencyAuthorization.DoesNotExist as exc:
        raise ValidationError("Emergency authorization is required for emergency publication.") from exc
    try:
        ratification = authorization.ratification
    except EmergencyRatification.DoesNotExist as exc:
        raise ValidationError("Emergency terminal outcome is required before publication.") from exc
    if now < authorization.ratification_deadline:
        raise ValidationError("Emergency publication requires the 24-hour decision window to pass.")
    if ratification.outcome not in EmergencyRatification.Outcome.values:
        raise ValidationError("Emergency outcome is invalid.")
    return authorization, ratification


def _resident_payload(
    proposal,
    version,
    acceptance,
    payment,
    verification,
    document_hashes,
    emergency_outcome=None,
):
    work_order = proposal.work_order
    case = work_order.case
    report_id = case.decision.report_id
    board = _board_approval(version) if proposal.mode == Proposal.Mode.NORMAL else None
    rep = _rep_approval(version) if proposal.mode == Proposal.Mode.NORMAL else None
    payload = {
        "report_id": report_id,
        "case_id": case.pk,
        "work_order_id": work_order.pk,
        "proposal_id": proposal.pk,
        "proposal_version": version.number,
        "proposed_amount_vnd": version.amount_vnd,
        "actual_cost_vnd": acceptance.actual_cost_vnd,
        "contractor_name": version.contractor_name,
        "mode": proposal.mode,
        "document_hashes": document_hashes,
        "payment_verification": {
            "decision": verification.decision,
            "payment_id": payment.pk,
            "verification_event_hash": verification.outbox_event.payload_hash,
        },
        "approvals": {},
    }
    if board is not None:
        payload["approvals"]["board"] = {
            "membership_id": board.membership_id,
            "decision": board.decision,
            "user_id": board.membership.user_id,
        }
    if rep is not None:
        payload["approvals"]["resident_rep"] = {
            "membership_id": rep.membership_id,
            "decision": rep.decision,
            "user_id": rep.membership.user_id,
        }
    if emergency_outcome is not None:
        authorization, ratification = emergency_outcome
        label = "Emergency"
        if ratification.outcome == EmergencyRatification.Outcome.RATIFIED:
            outcome_label = "Ratified"
        elif ratification.outcome == EmergencyRatification.Outcome.REJECTED:
            outcome_label = "Ratification rejected"
        else:
            outcome_label = "Ratification overdue"
        # Rejected/overdue must never render as approved.
        payload["emergency"] = {
            "label": label,
            "outcome": ratification.outcome,
            "outcome_label": outcome_label,
            "approved": ratification.outcome == EmergencyRatification.Outcome.RATIFIED,
            "authorization_event_hash": authorization.outbox_event.payload_hash,
            "outcome_event_hash": (
                ratification.outbox_event.payload_hash
                if ratification.outbox_event_id
                else None
            ),
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
    drill,
    emergency_outcome_hash=None,
):
    if type(publication_id) is not int or publication_id <= 0:
        raise ValidationError("Publication id must be a positive integer.")
    if not isinstance(prerequisite_event_hashes, list) or not prerequisite_event_hashes:
        raise ValidationError("Prerequisite event hashes are required.")
    if not isinstance(document_hashes, list) or not document_hashes:
        raise ValidationError("Document hashes are required.")
    if type(drill) is not bool:
        raise ValidationError("Drill flag must be a boolean.")
    if not isinstance(timestamp, type(timezone.now())) or timestamp.tzinfo is None:
        raise ValidationError("Publication timestamp must be timezone-aware.")
    payload = {
        "publication_id": publication_id,
        "prerequisite_event_hashes": prerequisite_event_hashes,
        "resident_payload_hash": resident_payload_hash,
        "document_hashes": document_hashes,
        "publication_timestamp": utc_rfc3339(timestamp),
        "drill": drill,
    }
    if emergency_outcome_hash:
        payload["emergency_outcome_hash"] = emergency_outcome_hash
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
    emergency_outcome_hash=None,
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
        bool(proposal.work_order.drill),
        emergency_outcome_hash=emergency_outcome_hash,
    )
    if previous_hash is None:
        previous_hash = "0x" + "00" * 32
    return build_evidence_typed_data(
        event_id,
        EvidenceType.PUBLICATION_SNAPSHOT,
        "0x" + payload_hash(payload),
        previous_hash,
    )


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
        actor = require_capability(publisher.user, publisher.pk, LEDGER_PUBLISH)
        if actor.organization.kind != Organization.Kind.BOARD:
            raise PermissionDenied("Only a Board membership may publish the ledger.")
        work_order = proposal.work_order
        if actor.organization.building_id != work_order.case.building_id:
            raise PermissionDenied("Board must belong to the work-order building.")
        if work_order.drill:
            raise ValidationError("Drill-mode proposals cannot be published to the ledger.")
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

        emergency_outcome = None
        emergency_outcome_hash = None
        prerequisite_events = []
        now = timezone.now()

        if proposal.mode == Proposal.Mode.NORMAL:
            board = _board_approval(version)
            rep = _rep_approval(version)
            if board is None or rep is None:
                raise ValidationError(
                    "Normal publication requires Board and resident-representative approvals."
                )
            prerequisite_events.extend(
                [
                    version.outbox_event,
                    board.outbox_event,
                    rep.outbox_event,
                ]
            )
        elif proposal.mode == Proposal.Mode.EMERGENCY:
            authorization, ratification = _emergency_context(proposal, now)
            emergency_outcome = (authorization, ratification)
            prerequisite_events.extend(
                [
                    authorization.outbox_event,
                    version.outbox_event,
                ]
            )
            if ratification.outbox_event_id:
                prerequisite_events.append(ratification.outbox_event)
                emergency_outcome_hash = ratification.outbox_event.payload_hash
            else:
                emergency_outcome_hash = authorization.outbox_event.payload_hash
        else:
            raise ValidationError("Proposal mode is not publishable.")

        prerequisite_events.extend(
            [
                acceptance.outbox_event,
                payment.outbox_event,
                verification.outbox_event,
            ]
        )
        for event in prerequisite_events:
            _require_confirmed(event, "Prerequisite")

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
                    emergency_outcome=emergency_outcome,
                )
                if emergency_outcome is not None:
                    if resident_payload["emergency"]["approved"] and emergency_outcome[
                        1
                    ].outcome != EmergencyRatification.Outcome.RATIFIED:
                        raise ValidationError("Emergency approval label is inconsistent.")

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
                    bool(work_order.drill),
                    emergency_outcome_hash=emergency_outcome_hash,
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
            "Publisher must not be the proposal creator, Board proposal approver, or payment recorder."
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
    if snapshot.outbox_event.status != BlockchainOutboxEvent.Status.CONFIRMED:
        raise ValidationError(
            "Publication snapshot must be chain-confirmed before finalization."
        )
    proposal = snapshot.proposal
    if PublishedLedgerEntry.objects.filter(proposal=proposal).exists():
        return PublishedLedgerEntry.objects.get(proposal=proposal)

    acceptance, payment, verification = _load_execution_chain(proposal)
    if verification.decision != PaymentVerification.Decision.VERIFIED:
        raise ValidationError("Payment must remain VERIFIED at finalization.")
    version = proposal.current_version
    work_order = proposal.work_order
    if work_order.drill:
        raise ValidationError("Drill-mode proposals cannot post to the Maintenance Fund.")
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
    return entry
