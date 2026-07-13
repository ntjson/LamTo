"""Idempotent blockchain outbox worker and signer-authorization synchronizer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from eth_utils import to_checksum_address

from lamto.accounts.models import SignerAuthorizationRequest
from lamto.audit.services import record_audit

from .chain import ChainClientError, ChainRecord, ChainTimeoutError, default_client
from .models import BlockchainOutboxEvent

LEASE_SECONDS = 180

def _json_safe(value):
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "hex") and not isinstance(value, (str, int, bool, float)):
        try:
            hexed = value.hex()
            if isinstance(hexed, str):
                return hexed if hexed.startswith("0x") else "0x" + hexed
        except Exception:
            pass
    return value


RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 3600


class ChainClient(Protocol):
    last_receipt: dict | None

    def find(self, event) -> ChainRecord | None: ...

    def submit(self, event) -> str: ...

    def set_signer(self, address, authorized: bool) -> str: ...


def _retry_delay(attempts: int) -> timedelta:
    exponent = max(attempts - 1, 0)
    seconds = min(RETRY_BASE_SECONDS * (2**exponent), RETRY_MAX_SECONDS)
    return timedelta(seconds=seconds)


def _normalize_payload_hash(value: str) -> str:
    text = value.lower()
    return text[2:] if text.startswith("0x") else text


def _record_matches_event(record: ChainRecord, event: BlockchainOutboxEvent) -> bool:
    return (
        _normalize_payload_hash(record.payload_hash)
        == _normalize_payload_hash(event.payload_hash)
        and record.previous_hash.lower() == event.previous_hash.lower()
        and int(record.event_type) == int(event.event_type)
        and to_checksum_address(record.signer)
        == to_checksum_address(event.signer_wallet.address)
    )


def _claim_outbox_event(event_pk: int) -> BlockchainOutboxEvent | None:
    """Atomically claim a due outbox row with a short SUBMITTED lease."""
    now = timezone.now()
    with transaction.atomic():
        event = (
            BlockchainOutboxEvent.objects.select_for_update(skip_locked=True)
            .select_related("signer_wallet__membership__user")
            .filter(pk=event_pk)
            .filter(
                Q(status=BlockchainOutboxEvent.Status.PENDING)
                & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
                | Q(
                    status=BlockchainOutboxEvent.Status.SUBMITTED,
                    lease_expires_at__lte=now,
                )
            )
            .first()
        )
        if event is None:
            return None
        event.status = BlockchainOutboxEvent.Status.SUBMITTED
        event.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        event.submitted_at = event.submitted_at or now
        event.last_attempt_at = now
        event.last_error = ""
        event.save(
            update_fields=[
                "status",
                "lease_expires_at",
                "submitted_at",
                "last_attempt_at",
                "last_error",
                "updated_at",
            ]
        )
        return event


def _mark_confirmed(
    event: BlockchainOutboxEvent,
    *,
    transaction_hash: str = "",
    receipt: dict | None = None,
    recorded_at: int | None = None,
) -> BlockchainOutboxEvent:
    now = timezone.now()
    receipt = _json_safe(receipt or {})
    event.status = BlockchainOutboxEvent.Status.CONFIRMED
    event.lease_expires_at = None
    event.confirmed_at = now
    event.last_error = ""
    if transaction_hash:
        event.transaction_hash = transaction_hash
    if receipt:
        event.receipt = receipt
        if "status" in receipt:
            event.receipt_status = int(receipt["status"])
        block_number = receipt.get("blockNumber")
        if block_number is not None:
            event.chain_confirmed_block = int(block_number)
    if recorded_at:
        event.chain_block_timestamp = datetime.fromtimestamp(recorded_at, tz=UTC)
    event.save(
        update_fields=[
            "status",
            "lease_expires_at",
            "confirmed_at",
            "last_error",
            "transaction_hash",
            "receipt",
            "receipt_status",
            "chain_confirmed_block",
            "chain_block_timestamp",
            "updated_at",
        ]
    )
    return event


def _mark_mismatch(event: BlockchainOutboxEvent, record: ChainRecord) -> BlockchainOutboxEvent:
    event.status = BlockchainOutboxEvent.Status.MISMATCH
    event.lease_expires_at = None
    event.last_error = (
        "On-chain record does not match outbox signed identity "
        f"(payload={record.payload_hash}, previous={record.previous_hash}, "
        f"type={record.event_type}, signer={record.signer})."
    )
    event.save(
        update_fields=["status", "lease_expires_at", "last_error", "updated_at"]
    )
    membership = event.signer_wallet.membership
    record_audit(
        membership.user,
        membership,
        "evidence.chain_mismatch",
        "BlockchainOutboxEvent",
        event.event_id,
        "FAILURE",
        {
            "event_type": int(event.event_type),
            "payload_hash": event.payload_hash,
            "chain_payload_hash": record.payload_hash,
            "chain_previous_hash": record.previous_hash,
            "chain_event_type": int(record.event_type),
            "chain_signer": record.signer,
        },
    )
    return event


def _mark_retry(event: BlockchainOutboxEvent, error: BaseException) -> BlockchainOutboxEvent:
    now = timezone.now()
    event.attempts = int(event.attempts) + 1
    event.status = BlockchainOutboxEvent.Status.PENDING
    event.lease_expires_at = None
    event.next_attempt_at = now + _retry_delay(event.attempts)
    event.last_attempt_at = now
    event.last_error = str(error)[:2000]
    event.save(
        update_fields=[
            "attempts",
            "status",
            "lease_expires_at",
            "next_attempt_at",
            "last_attempt_at",
            "last_error",
            "updated_at",
        ]
    )
    return event


def process_outbox_event(event_id, client: ChainClient | None = None) -> BlockchainOutboxEvent:
    """
    Process one outbox row idempotently by stable event primary key.

    Never re-signs or changes payload identity fields. Only delivery status,
    attempts, lease, and receipt metadata are mutated.
    """
    client = client or default_client()

    existing = (
        BlockchainOutboxEvent.objects.select_related("signer_wallet__membership__user")
        .filter(pk=event_id)
        .first()
    )
    if existing is None:
        raise BlockchainOutboxEvent.DoesNotExist(
            f"BlockchainOutboxEvent id={event_id} does not exist"
        )
    if existing.status in {
        BlockchainOutboxEvent.Status.CONFIRMED,
        BlockchainOutboxEvent.Status.MISMATCH,
    }:
        # Terminal states: re-check chain for CONFIRMED but never resubmit.
        if existing.status == BlockchainOutboxEvent.Status.CONFIRMED:
            try:
                record = client.find(existing)
            except Exception:
                return existing
            if record is not None and not _record_matches_event(record, existing):
                with transaction.atomic():
                    return _mark_mismatch(existing, record)
        return existing

    claimed = _claim_outbox_event(event_id)
    if claimed is None:
        # Another worker holds the lease, or the row is not due.
        refreshed = BlockchainOutboxEvent.objects.select_related(
            "signer_wallet"
        ).get(pk=event_id)
        return refreshed

    # Database transaction released before network I/O.
    try:
        record = client.find(claimed)
    except Exception as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)

    if record is not None:
        with transaction.atomic():
            event = (
                BlockchainOutboxEvent.objects.select_for_update()
                .select_related("signer_wallet__membership__user")
                .get(pk=claimed.pk)
            )
            if _record_matches_event(record, event):
                return _mark_confirmed(
                    event,
                    transaction_hash=event.transaction_hash,
                    recorded_at=record.recorded_at,
                )
            return _mark_mismatch(event, record)

    try:
        tx_hash = client.submit(claimed)
        receipt = getattr(client, "last_receipt", None) or {}
    except (ChainTimeoutError, TimeoutError, ConnectionError, OSError) as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)
    except ChainClientError as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)
    except Exception as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)

    with transaction.atomic():
        event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
        return _mark_confirmed(event, transaction_hash=tx_hash, receipt=receipt)


def claim_next_due_outbox_event() -> BlockchainOutboxEvent | None:
    """Claim the next due outbox event for batch processing."""
    now = timezone.now()
    with transaction.atomic():
        event = (
            BlockchainOutboxEvent.objects.select_for_update(skip_locked=True)
            .select_related("signer_wallet__membership__user")
            .filter(
                Q(status=BlockchainOutboxEvent.Status.PENDING)
                & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
                | Q(
                    status=BlockchainOutboxEvent.Status.SUBMITTED,
                    lease_expires_at__lte=now,
                )
            )
            .order_by("created_at", "pk")
            .first()
        )
        if event is None:
            return None
        event.status = BlockchainOutboxEvent.Status.SUBMITTED
        event.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        event.submitted_at = event.submitted_at or now
        event.last_attempt_at = now
        event.last_error = ""
        event.save(
            update_fields=[
                "status",
                "lease_expires_at",
                "submitted_at",
                "last_attempt_at",
                "last_error",
                "updated_at",
            ]
        )
        return event


def process_due_outbox_events(
    *, limit: int = 100, client: ChainClient | None = None
) -> list[BlockchainOutboxEvent]:
    client = client or default_client()
    processed: list[BlockchainOutboxEvent] = []
    for _ in range(limit):
        claimed = claim_next_due_outbox_event()
        if claimed is None:
            break
        # process_outbox_event will see SUBMITTED with active lease owned by us;
        # re-claim path: call the post-claim pipeline directly via event id after
        # resetting claim is awkward. Instead, run the network portion inline by
        # temporarily treating the already-claimed row.
        result = _process_claimed_event(claimed, client=client)
        processed.append(result)
    return processed


def _process_claimed_event(
    claimed: BlockchainOutboxEvent, *, client: ChainClient
) -> BlockchainOutboxEvent:
    try:
        record = client.find(claimed)
    except Exception as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)

    if record is not None:
        with transaction.atomic():
            event = (
                BlockchainOutboxEvent.objects.select_for_update()
                .select_related("signer_wallet__membership__user")
                .get(pk=claimed.pk)
            )
            if _record_matches_event(record, event):
                return _mark_confirmed(
                    event,
                    transaction_hash=event.transaction_hash,
                    recorded_at=record.recorded_at,
                )
            return _mark_mismatch(event, record)

    try:
        tx_hash = client.submit(claimed)
        receipt = getattr(client, "last_receipt", None) or {}
    except Exception as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)

    with transaction.atomic():
        event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
        return _mark_confirmed(event, transaction_hash=tx_hash, receipt=receipt)


def sync_signer_authorizations(
    client: ChainClient | None = None,
) -> list[SignerAuthorizationRequest]:
    """
    Synchronize pending wallet authorization/revocation requests on-chain.

    Uses the contract-owner key (via client.set_signer). Revocation prevents new
    signatures but never mutates historical chain records.
    """
    client = client or default_client()
    pending = (
        SignerAuthorizationRequest.objects.select_related("wallet")
        .filter(status=SignerAuthorizationRequest.Status.PENDING)
        .order_by("created_at", "pk")
    )
    results: list[SignerAuthorizationRequest] = []
    for request in pending:
        authorized = request.action == SignerAuthorizationRequest.Action.AUTHORIZE
        try:
            tx_hash = client.set_signer(request.wallet.address, authorized)
        except Exception as exc:
            request.last_error = str(exc)[:2000]
            request.save(update_fields=["last_error"])
            results.append(request)
            continue
        request.status = SignerAuthorizationRequest.Status.CONFIRMED
        request.transaction_hash = tx_hash
        request.confirmed_at = timezone.now()
        request.last_error = ""
        request.save(
            update_fields=[
                "status",
                "transaction_hash",
                "confirmed_at",
                "last_error",
            ]
        )
        results.append(request)
    return results
