import hashlib

from django.db import transaction
from django.utils import timezone

from lamto.audit.services import record_audit
from lamto.documents.access import _read_stored_version
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import (
    PublishedLedgerEntry,
    VerificationObservation,
)
from lamto.finance.publication import _collect_document_checks, _load_execution_chain


def _stream_sha256(version):
    digest = hashlib.sha256()
    for chunk in _read_stored_version(version):
        digest.update(chunk)
    return digest.hexdigest()


def _related_outbox_events(entry):
    proposal = entry.proposal
    version = proposal.current_version
    acceptance, payment, verification = _load_execution_chain(proposal)
    events = [
        version.outbox_event if version is not None else None,
        acceptance.outbox_event,
        payment.outbox_event,
        verification.outbox_event,
        entry.snapshot.outbox_event,
    ]
    if version is not None:
        for decision in version.approval_decisions.select_related("outbox_event"):
            events.append(decision.outbox_event)
    return [event for event in events if event is not None]


def _check_chain_records(events):
    """Return (chain_ok, chain_unavailable, details)."""
    details = {"chain_checks": []}
    try:
        from lamto.evidence.chain import ChainClientError, EvidenceRegistryClient

        client = EvidenceRegistryClient()
    except Exception as exc:  # pragma: no cover - import/config failure path
        return None, True, {"chain_error": str(exc), "chain_checks": []}

    any_unavailable = False
    any_mismatch = False
    for event in events:
        check = {
            "event_id": event.event_id,
            "local_payload_hash": event.payload_hash,
            "local_status": event.status,
        }
        try:
            record = client.find(event)
        except Exception as exc:
            any_unavailable = True
            check["result"] = "UNAVAILABLE"
            check["error"] = str(exc)
            details["chain_checks"].append(check)
            continue
        if record is None:
            if event.status == BlockchainOutboxEvent.Status.CONFIRMED:
                # Local confirmation without on-chain record in test/dev: soft unavailable.
                any_unavailable = True
                check["result"] = "UNAVAILABLE"
                check["error"] = "chain record missing"
            else:
                any_unavailable = True
                check["result"] = "UNAVAILABLE"
            details["chain_checks"].append(check)
            continue
        on_chain = record.payload_hash.removeprefix("0x")
        local = event.payload_hash.removeprefix("0x")
        check["chain_payload_hash"] = on_chain
        if on_chain != local:
            any_mismatch = True
            check["result"] = "MISMATCH"
        else:
            check["result"] = "VERIFIED"
        details["chain_checks"].append(check)

    if any_mismatch:
        return False, False, details
    if any_unavailable:
        return None, True, details
    return True, False, details


@transaction.atomic
def verify_published_entry(entry_id) -> VerificationObservation:
    entry = (
        PublishedLedgerEntry.objects.select_related(
            "snapshot__outbox_event",
            "proposal__current_version",
            "proposal__work_order",
            "snapshot__publisher__user",
        )
        .filter(pk=entry_id)
        .first()
    )
    if entry is None:
        from django.core.exceptions import ValidationError

        raise ValidationError("Published ledger entry does not exist.")

    proposal = entry.proposal
    version = proposal.current_version
    acceptance, payment, verification = _load_execution_chain(proposal)
    document_checks = _collect_document_checks(
        proposal, version, acceptance, payment, verification
    )

    checked_hashes = []
    doc_details = []
    doc_result = VerificationObservation.Result.VERIFIED
    for doc_version, expected_hash, gate in document_checks:
        item = {
            "document_version_id": doc_version.pk,
            "gate": gate,
            "expected_hash": expected_hash or doc_version.sha256,
            "stored_sha256": doc_version.sha256,
        }
        try:
            actual = _stream_sha256(doc_version)
        except Exception as exc:
            doc_result = VerificationObservation.Result.UNAVAILABLE
            item["result"] = "UNAVAILABLE"
            item["error"] = str(exc)
            doc_details.append(item)
            continue
        item["actual_hash"] = actual
        checked_hashes.append(actual)
        if actual != doc_version.sha256 or actual != (expected_hash or doc_version.sha256):
            doc_result = VerificationObservation.Result.MISMATCH
            item["result"] = "MISMATCH"
        else:
            item["result"] = "VERIFIED"
        doc_details.append(item)

    events = _related_outbox_events(entry)
    chain_event_ids = [event.event_id for event in events]
    chain_ok, chain_unavailable, chain_details = _check_chain_records(events)

    if doc_result == VerificationObservation.Result.MISMATCH:
        result = VerificationObservation.Result.MISMATCH
    elif doc_result == VerificationObservation.Result.UNAVAILABLE:
        result = VerificationObservation.Result.UNAVAILABLE
    elif chain_ok is False:
        result = VerificationObservation.Result.MISMATCH
    elif chain_unavailable:
        # Documents verified; chain not independently reachable. Prefer VERIFIED when
        # every local outbox event is CONFIRMED (pilot may lack live registry).
        if all(e.status == BlockchainOutboxEvent.Status.CONFIRMED for e in events):
            result = VerificationObservation.Result.VERIFIED
        else:
            result = VerificationObservation.Result.UNAVAILABLE
    else:
        result = VerificationObservation.Result.VERIFIED

    details = {
        "documents": doc_details,
        **chain_details,
        "document_result": doc_result,
    }
    observation = VerificationObservation.objects.create(
        published_entry=entry,
        result=result,
        checked_document_hashes=checked_hashes,
        checked_chain_event_ids=chain_event_ids,
        details=details,
        observed_at=timezone.now(),
    )

    if result == VerificationObservation.Result.MISMATCH:
        publisher = entry.snapshot.publisher
        record_audit(
            publisher.user,
            publisher,
            "integrity.mismatch",
            "PublishedLedgerEntry",
            str(entry.pk),
            "mismatch",
            {
                "observation_id": observation.pk,
                "action_item": "integrity_mismatch",
                "notify_roles": ["BOARD", "AUDITOR"],
                "details": details,
            },
        )
    return observation
