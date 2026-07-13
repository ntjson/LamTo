import json
import re
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from eth_utils import to_checksum_address

from lamto.accounts.models import (
    OrganizationMembership,
    SignerAuthorizationRequest,
    SignerWallet,
    WalletRegistrationChallenge,
)
from lamto.audit.services import record_audit

from .canonical import canonical_bytes, payload_hash
from .models import BlockchainOutboxEvent, EvidenceType
from .signatures import (
    BYTES32_RE,
    build_evidence_typed_data,
    normalize_signature,
    recover_signer,
)


SIGNING_ROLES = {
    OrganizationMembership.Role.OPERATOR,
    OrganizationMembership.Role.BOARD,
    OrganizationMembership.Role.RESIDENT_REP,
}
HASH_RE = re.compile(r"(?:0x)?[0-9a-f]{64}\Z")
EVIDENCE_PAYLOAD_FIELDS = {
    EvidenceType.PROPOSAL_CREATED: frozenset({
        "proposal_id", "proposal_version", "record_id", "work_order_id", "case_id",
        "report_id", "amount_vnd", "estimated_amount_vnd", "proposal_snapshot_hash",
        "work_snapshot_hash", "case_snapshot_hash", "report_snapshot_hash",
        "quotation_original_hash", "quotation_redacted_hash", "photo_hash", "photo_hashes",
    }),
    EvidenceType.BOARD_APPROVAL: frozenset({
        "proposal_hash", "decision", "actor_organization_id", "decision_timestamp",
    }),
    EvidenceType.REPRESENTATIVE_APPROVAL: frozenset({
        "proposal_hash", "decision", "actor_organization_id", "decision_timestamp",
    }),
    EvidenceType.EMERGENCY_AUTHORIZATION: frozenset({
        "work_order_id", "reason_digest", "available_estimate_vnd",
        "estimate_document_hash", "authorization_timestamp", "drill",
    }),
    EvidenceType.EMERGENCY_OUTCOME: frozenset({
        "decision", "result", "reason_digest", "deadline_result", "decision_timestamp", "drill",
    }),
    EvidenceType.WORK_ACCEPTANCE: frozenset({
        "work_order_id", "actual_cost_vnd", "acceptance_timestamp", "invoice_original_hash",
        "invoice_redacted_hash", "acceptance_report_original_hash",
        "acceptance_report_redacted_hash", "photo_hashes", "drill",
    }),
    EvidenceType.PAYMENT_RECORDED: frozenset({
        "payment_id", "amount_vnd", "bank_reference_digest", "external_status",
        "external_timestamp", "payment_proof_original_hash", "payment_proof_redacted_hash",
    }),
    EvidenceType.PAYMENT_VERIFIED: frozenset({
        "payment_hash", "decision", "verification_result", "verification_timestamp",
    }),
    EvidenceType.PUBLICATION_SNAPSHOT: frozenset({
        "publication_id", "prerequisite_event_hashes", "emergency_outcome_hash",
        "resident_payload_hash", "document_hashes", "publication_timestamp", "drill",
    }),
    EvidenceType.CORRECTION: frozenset({
        "correction_id", "original_event_id", "original_hash", "replacement_hashes",
        "reason_digest", "decision", "actor_organization_id", "publisher_snapshot_hash",
        "correction_timestamp",
    }),
    EvidenceType.FUND_ENTRY: frozenset({
        "fund_entry_id", "entry_type", "amount_vnd", "source_document_original_hash",
        "source_document_redacted_hash", "maker_membership_id", "checker_membership_id",
        "entry_timestamp",
    }),
}


class EvidenceConflict(Exception):
    pass


@contextmanager
def _db_transition(name):
    setting = f"lamto.{name}_transition"
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, 'on', true)", [setting])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config(%s, 'off', true)", [setting])


def utc_rfc3339(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("Timestamp must be a timezone-aware datetime.")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def lowercase_identifier(value) -> str:
    return str(value).lower()


def normalize_vnd(value) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("VND amounts must be non-negative integers.")
    return value


def _active_signing_membership(membership, *, lock=False):
    queryset = OrganizationMembership.objects.select_related("user", "organization")
    if lock:
        queryset = queryset.select_for_update()
    current = queryset.filter(pk=getattr(membership, "pk", None), active=True).first()
    if current is None or current.role not in SIGNING_ROLES:
        raise PermissionDenied("Membership is not eligible to sign pilot evidence.")
    return current


def _registration_typed_data(challenge) -> dict:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "WalletRegistration": [
                {"name": "membershipId", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
                {"name": "expiresAt", "type": "uint256"},
            ],
        },
        "primaryType": "WalletRegistration",
        "domain": {
            "name": "LamToWalletRegistration",
            "version": "1",
            "chainId": settings.BLOCKCHAIN_CHAIN_ID,
            "verifyingContract": settings.EVIDENCE_CONTRACT_ADDRESS,
        },
        "message": {
            "membershipId": challenge.membership_id,
            "nonce": "0x" + challenge.nonce,
            "expiresAt": int(challenge.expires_at.timestamp()),
        },
    }


@transaction.atomic
def begin_wallet_registration(membership) -> dict:
    membership = _active_signing_membership(membership, lock=True)
    now = timezone.now()
    WalletRegistrationChallenge.objects.filter(
        membership=membership, consumed_at__isnull=True
    ).update(consumed_at=now)
    challenge = WalletRegistrationChallenge.objects.create(
        membership=membership,
        nonce=secrets.token_hex(32),
        expires_at=now + timedelta(seconds=settings.WALLET_REGISTRATION_TTL_SECONDS),
    )
    record_audit(
        membership.user,
        membership,
        "wallet.registration.begin",
        "OrganizationMembership",
        str(membership.pk),
        "SUCCESS",
        {"expires_at": utc_rfc3339(challenge.expires_at)},
    )
    return _registration_typed_data(challenge)


def register_wallet(membership, checksum_address, proof_signature) -> SignerWallet:
    try:
        address = to_checksum_address(checksum_address)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Wallet address is invalid.") from exc

    error = None
    wallet = None
    with transaction.atomic():
        membership = _active_signing_membership(membership, lock=True)
        challenge = (
            WalletRegistrationChallenge.objects.select_for_update()
            .filter(membership=membership, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if challenge is None:
            raise ValidationError("Wallet registration challenge is missing or already used.")
        now = timezone.now()
        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at"])
        if challenge.expires_at <= now:
            error = "Wallet registration challenge has expired."
        else:
            try:
                recovered = recover_signer(_registration_typed_data(challenge), proof_signature)
            except Exception:
                recovered = None
            if recovered != address:
                error = "Wallet proof does not match the submitted address."
        if error is None:
            with _db_transition("wallet"), transaction.atomic():
                for previous in SignerWallet.objects.select_for_update().filter(
                    membership=membership, active=True
                ):
                    previous.active = False
                    previous.revoked_at = now
                    previous.save(update_fields=["active", "revoked_at"])
                    SignerAuthorizationRequest.objects.get_or_create(
                        wallet=previous,
                        action=SignerAuthorizationRequest.Action.REVOKE,
                        defaults={"requested_by": membership},
                    )
                wallet = SignerWallet.objects.create(membership=membership, address=address)
            SignerAuthorizationRequest.objects.create(
                wallet=wallet,
                requested_by=membership,
                action=SignerAuthorizationRequest.Action.AUTHORIZE,
            )
            record_audit(
                membership.user,
                membership,
                "wallet.register",
                "SignerWallet",
                str(wallet.pk),
                "SUCCESS",
                {"address": address},
            )
    if error:
        raise ValidationError(error)
    return wallet


@transaction.atomic
def revoke_wallet(wallet, authorizing_membership) -> SignerWallet:
    wallet = SignerWallet.objects.select_for_update().select_related("membership").get(pk=wallet.pk)
    authorizer = _active_signing_membership(authorizing_membership, lock=True)
    if wallet.membership.organization_id != authorizer.organization_id:
        raise PermissionDenied("Wallet revocation requires the same organization.")
    if not wallet.active:
        return wallet
    with _db_transition("wallet"), transaction.atomic():
        wallet.active = False
        wallet.revoked_at = timezone.now()
        wallet.save(update_fields=["active", "revoked_at"])
    SignerAuthorizationRequest.objects.get_or_create(
        wallet=wallet,
        action=SignerAuthorizationRequest.Action.REVOKE,
        defaults={"requested_by": authorizer},
    )
    record_audit(
        authorizer.user,
        authorizer,
        "wallet.revoke",
        "SignerWallet",
        str(wallet.pk),
        "SUCCESS",
        {"address": wallet.address},
    )
    return wallet


def _require_caller_transaction():
    if not connection.in_atomic_block or not any(
        not getattr(block, "_from_testcase", False) for block in connection.atomic_blocks
    ):
        raise RuntimeError("queue_signed_event must run inside the caller's transaction.")


def _validate_payload(event_type, payload):
    allowed = EVIDENCE_PAYLOAD_FIELDS.get(event_type)
    if allowed is None:
        raise ValueError("Evidence event type must be an integer from 1 through 11.")
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValidationError("Evidence payload must be an object with known fields.")
    if set(payload) - allowed:
        raise ValidationError("Evidence payload contains fields outside its event schema.")
    for key, value in payload.items():
        if key.endswith(("_hash", "_digest")) and (
            not isinstance(value, str) or not HASH_RE.fullmatch(value)
        ):
            raise ValidationError("Evidence hashes and digests must be lowercase 32-byte hex.")
        if key.endswith("_hashes") and (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not HASH_RE.fullmatch(item) for item in value)
        ):
            raise ValidationError("Evidence hash lists must contain lowercase 32-byte hex.")

    def reject_nested_objects(value):
        if isinstance(value, dict):
            raise ValidationError("Nested evidence objects are not allowed; include hashes or IDs.")
        if isinstance(value, list):
            for item in value:
                reject_nested_objects(item)

    for value in payload.values():
        reject_nested_objects(value)


def _resolve_duplicate(existing, event_type, payload, digest, previous_hash, wallet, signature):
    if (
        existing.event_type == event_type
        and existing.payload == payload
        and existing.payload_hash == digest
        and existing.previous_hash == previous_hash
        and existing.signer_wallet_id == wallet.pk
        and existing.signature == signature
    ):
        return existing
    raise EvidenceConflict("Event ID already exists with different signed identity.")


def queue_signed_event(
    event_id, event_type, payload, previous_hash, membership, signature
) -> BlockchainOutboxEvent:
    _require_caller_transaction()
    event_id = lowercase_identifier(event_id)
    previous_hash = lowercase_identifier(previous_hash)
    _validate_payload(event_type, payload)
    digest = payload_hash(payload)
    membership = _active_signing_membership(membership)
    if not BYTES32_RE.fullmatch(event_id) or not BYTES32_RE.fullmatch(previous_hash):
        raise ValidationError("Event ID and previous hash must be 0x-prefixed bytes32 values.")
    wallet = SignerWallet.objects.filter(membership=membership, active=True).first()
    if wallet is None:
        raise PermissionDenied("Membership has no active signing wallet.")
    normalized_payload = json.loads(canonical_bytes(payload))
    typed_data = build_evidence_typed_data(event_id, event_type, "0x" + digest, previous_hash)
    try:
        signature = normalize_signature(signature)
        recovered = recover_signer(typed_data, signature)
    except Exception as exc:
        raise ValidationError("Evidence signature is invalid.") from exc
    if recovered != wallet.address:
        raise PermissionDenied("Evidence signature does not match the active wallet.")
    existing = BlockchainOutboxEvent.objects.filter(event_id=event_id).first()
    if existing:
        return _resolve_duplicate(
            existing, event_type, normalized_payload, digest, previous_hash, wallet, signature
        )
    try:
        with _db_transition("outbox"), transaction.atomic():
            event = BlockchainOutboxEvent.objects.create(
                event_id=event_id, event_type=event_type, payload=normalized_payload,
                payload_hash=digest, previous_hash=previous_hash, signature=signature,
                signer_wallet=wallet,
            )
    except IntegrityError:
        existing = BlockchainOutboxEvent.objects.select_related("signer_wallet").get(
            event_id=event_id
        )
        return _resolve_duplicate(
            existing, event_type, normalized_payload, digest, previous_hash, wallet, signature
        )
    record_audit(
        membership.user,
        membership,
        "evidence.queue",
        "BlockchainOutboxEvent",
        event.event_id,
        "SUCCESS",
        {"event_type": int(event_type), "payload_hash": digest, "signer": wallet.address},
    )
    return event
