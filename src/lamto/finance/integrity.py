import hashlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from lamto.audit.services import record_audit
from lamto.documents.access import _read_stored_version
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, is_settled
from lamto.finance.models import (
    ProposalDocument,
    ProposalVersion,
    PublishedLedgerEntry,
    Settlement,
    VerificationObservation,
)
from lamto.finance.proposals import _submission_snapshot
from lamto.finance.publication import _collect_document_checks, _load_execution_chain
from lamto.finance.settlements import build_settlement_evidence_payload

# Anchored fields that describe the maintenance case rather than the spend. The
# case can be re-triaged after publication and is not published with the spend,
# so the rebuilt payload keeps the anchored values for these.
_CASE_PAYLOAD_FIELDS = frozenset(
    {"case_id", "case_snapshot_hash", "report_id", "report_snapshot_hash",
     "estimated_amount_vnd", "photo_hash", "photo_hashes"}
)


def _stream_sha256(version):
    digest = hashlib.sha256()
    for chunk in _read_stored_version(version):
        digest.update(chunk)
    return digest.hexdigest()


def _proposal_version_payload(version, stored):
    db = version._state.db
    quotations = [
        link.document_version
        for link in ProposalDocument.objects.using(db)
        .filter(proposal_version=version)
        .select_related("document_version")
        .order_by("pk")
    ]
    _, rebuilt = _submission_snapshot(
        version.proposal,
        version.amount_vnd,
        version.contractor_name,
        version.purpose,
        version.proposed_action,
        version.expected_schedule,
        quotations,
        version.number,
        expected_start=version.expected_start,
        expected_end=version.expected_end,
    )
    payload = {key: value for key, value in rebuilt.items() if key not in _CASE_PAYLOAD_FIELDS}
    payload.update(
        (key, value) for key, value in stored.items() if key in _CASE_PAYLOAD_FIELDS
    )
    return payload


def published_payload(event):
    """Rebuild an outbox event's evidence payload from the rows LamTo publishes.

    The explorer and the Resident app show the proposal version and Settlement
    rows, not the outbox payload, so integrity is checked against what those
    rows hash to now. Returns None when the event belongs to neither.
    """
    stored = event.payload if isinstance(event.payload, dict) else {}
    try:
        return _proposal_version_payload(event.proposal_version, stored)
    except ProposalVersion.DoesNotExist:
        pass
    try:
        return build_settlement_evidence_payload(event.settlement)
    except Settlement.DoesNotExist:
        return None


def check_local_evidence(event):
    """Re-hash one outbox event locally; no chain call.

    MISMATCH when the stored payload no longer hashes to the stored hash, or
    when the published rows no longer hash to it. The stored hash is the one
    anchored, so either case means the published data differs from the anchor.
    """
    stored_hash = event.payload_hash.removeprefix("0x").lower()
    check = {"event_id": event.event_id, "local_payload_hash": stored_hash}
    try:
        check["stored_payload_rehash"] = payload_hash(event.payload)
    except (TypeError, ValueError) as exc:
        check["stored_payload_rehash"] = None
        check["error"] = str(exc)
    rebuilt = published_payload(event)
    check["published_rows_rehash"] = payload_hash(rebuilt) if rebuilt is not None else None
    matches = check["stored_payload_rehash"] == stored_hash and (
        rebuilt is None or check["published_rows_rehash"] == stored_hash
    )
    check["result"] = "VERIFIED" if matches else "MISMATCH"
    return check


def _check_local_records(events):
    """Return (local_ok, details) for every event's local re-hash."""
    checks = [check_local_evidence(event) for event in events]
    return all(check["result"] == "VERIFIED" for check in checks), {"local_checks": checks}


def _related_outbox_events(entry):
    proposal = entry.proposal
    settlement = _load_execution_chain(proposal)
    versions = proposal.versions.select_related("outbox_event").order_by("number")
    return [version.outbox_event for version in versions if version.outbox_event_id] + [
        settlement.outbox_event
    ]


def _check_chain_records(events):
    """Return (chain_ok, chain_unavailable, details).

    Chain-dependent checks are skipped, never faked (spec 5.2): disabled mode
    skips every event; besu mode skips LOCAL-settled events individually.
    """
    if settings.EVIDENCE_ANCHORING_BACKEND == "disabled":
        return None, True, {
            "anchoring_backend": "disabled",
            "chain_checks": [
                {
                    "event_id": event.event_id,
                    "local_status": event.status,
                    "result": "SKIPPED_ANCHORING_DISABLED",
                }
                for event in events
            ],
        }

    details = {"chain_checks": []}
    chain_events = []
    for event in events:
        if event.status == BlockchainOutboxEvent.Status.LOCAL:
            details["chain_checks"].append(
                {
                    "event_id": event.event_id,
                    "local_status": event.status,
                    "result": "SKIPPED_LOCAL",
                }
            )
        else:
            chain_events.append(event)
    if not chain_events:
        return None, True, details

    try:
        from lamto.evidence.chain import EvidenceRegistryClient

        client = EvidenceRegistryClient()
    except Exception as exc:  # pragma: no cover - import/config failure path
        details["chain_error"] = str(exc)
        return None, True, details

    any_unavailable = False
    any_mismatch = False
    for event in chain_events:
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


def verify_published_entry(entry_id, using="default") -> VerificationObservation:
    """Append a verification observation for a published entry.

    ``using`` selects the Django DB alias for reads and the insert-only
    observation write (restored-DB integrity drills). The filesystem report
    path remains outside this function.
    """
    with transaction.atomic(using=using):
        entry = (
            PublishedLedgerEntry.objects.using(using)
            .select_related(
                "proposal__current_version",
                "proposal__case",
                "settlement__settled_by__user",
            )
            .filter(pk=entry_id)
            .first()
        )
        if entry is None:
            from django.core.exceptions import ValidationError

            raise ValidationError(_("Published ledger entry does not exist."))

        proposal = entry.proposal
        version = proposal.current_version
        settlement = _load_execution_chain(proposal)
        document_checks = _collect_document_checks(
            proposal, version, settlement, using=using
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
        local_ok, local_details = _check_local_records(events)
        chain_ok, chain_unavailable, chain_details = _check_chain_records(events)

        if doc_result == VerificationObservation.Result.MISMATCH:
            result = VerificationObservation.Result.MISMATCH
        elif doc_result == VerificationObservation.Result.UNAVAILABLE:
            result = VerificationObservation.Result.UNAVAILABLE
        elif not local_ok or chain_ok is False:
            result = VerificationObservation.Result.MISMATCH
        elif chain_unavailable:
            # Documents verified; chain not independently reachable or anchoring
            # skipped. Prefer VERIFIED when every local outbox event is settled.
            if all(is_settled(event.status) for event in events):
                result = VerificationObservation.Result.VERIFIED
            else:
                result = VerificationObservation.Result.UNAVAILABLE
        else:
            result = VerificationObservation.Result.VERIFIED

        # Consulted only when the chain itself answered for every event. A
        # skipped, LOCAL or unreachable event leaves LamTo checking its own
        # records, so the observation is never presented as independent.
        chain_checks = chain_details.get("chain_checks", [])
        chain_consulted = bool(chain_checks) and all(
            check.get("result")
            in (VerificationObservation.Result.VERIFIED, VerificationObservation.Result.MISMATCH)
            for check in chain_checks
        )
        details = {
            "documents": doc_details,
            **local_details,
            **chain_details,
            "document_result": doc_result,
        }
        observation = VerificationObservation.objects.using(using).create(
            published_entry=entry,
            result=result,
            checked_document_hashes=checked_hashes,
            checked_chain_event_ids=chain_event_ids,
            chain_consulted=chain_consulted,
            details=details,
            observed_at=timezone.now(),
        )

        if result == VerificationObservation.Result.MISMATCH:
            publisher = entry.settlement.settled_by
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
                    "details": details,
                },
            )
            try:
                from lamto.notifications.hooks import notify_integrity_mismatch

                notify_integrity_mismatch(entry, observation)
            except Exception:
                pass
        return observation
