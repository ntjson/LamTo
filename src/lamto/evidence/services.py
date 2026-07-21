import hashlib
import json
import re
import secrets
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
UTC_RFC3339_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
APPROVAL = frozenset({"APPROVE", "REJECT"})
# Closed vocabulary of payload value shapes (spec 2.2 opacity). Free-text shapes
# must not be added — chain hashes remain non-invertible only if payloads stay opaque.
OPAQUE_PAYLOAD_SHAPES = frozenset({
    "id", "positive_int", "money", "bool", "hash", "hashes", "bytes32", "timestamp",
})
HASH_PAYLOAD_SHAPES = frozenset({"hash", "hashes", "bytes32"})
EVIDENCE_PAYLOAD_SCHEMAS = {
    EvidenceType.PROPOSAL_CREATED: ({
        "proposal_id": "id", "proposal_version": "positive_int", "record_id": "id",
        "work_order_id": "id", "case_id": "id", "report_id": "id",
        "amount_vnd": "money", "proposal_snapshot_hash": "hash",
        "work_snapshot_hash": "hash", "case_snapshot_hash": "hash",
        "report_snapshot_hash": "hash", "quotation_original_hash": "hash",
        "quotation_redacted_hash": "hash",
    }, {"estimated_amount_vnd": "money", "photo_hash": "hash", "photo_hashes": "hashes"}),
    EvidenceType.BOARD_APPROVAL: ({
        "proposal_hash": "hash", "decision": APPROVAL,
        "actor_organization_id": "id", "decision_timestamp": "timestamp",
    }, {}),
    EvidenceType.REPRESENTATIVE_APPROVAL: ({
        "proposal_hash": "hash", "decision": APPROVAL,
        "actor_organization_id": "id", "decision_timestamp": "timestamp",
    }, {}),
    EvidenceType.WORK_ACCEPTANCE: ({
        "work_order_id": "id", "actual_cost_vnd": "money",
        "acceptance_timestamp": "timestamp", "invoice_original_hash": "hash",
        "invoice_redacted_hash": "hash", "acceptance_report_original_hash": "hash",
        "acceptance_report_redacted_hash": "hash", "photo_hashes": "hashes",
    }, {}),
    EvidenceType.PAYMENT_RECORDED: ({
        "payment_id": "id", "amount_vnd": "money", "bank_reference_digest": "hash",
        "external_status": frozenset({"PENDING", "SETTLED", "FAILED", "REVERSED"}),
        "external_timestamp": "timestamp", "payment_proof_original_hash": "hash",
        "payment_proof_redacted_hash": "hash",
    }, {}),
    EvidenceType.PAYMENT_VERIFIED: ({
        "payment_hash": "hash", "decision": APPROVAL,
        "verification_result": frozenset({"MATCH", "MISMATCH"}),
        "verification_timestamp": "timestamp",
    }, {}),
    EvidenceType.PUBLICATION_SNAPSHOT: ({
        "publication_id": "id", "prerequisite_event_hashes": "hashes",
        "resident_payload_hash": "hash", "document_hashes": "hashes",
        "publication_timestamp": "timestamp",
    }, {}),
    EvidenceType.FUND_ENTRY: ({
        "fund_entry_id": "id", "entry_type": frozenset({"OPENING", "INFLOW"}),
        "amount_vnd": "money", "source_document_original_hash": "hash",
        "source_document_redacted_hash": "hash", "maker_membership_id": "id",
        "entry_timestamp": "timestamp",
    }, {"checker_membership_id": "id"}),
}


class EvidenceConflict(Exception):
    pass


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


def _signed_write_authorization(scope, *parts) -> str:
    message = "|".join((scope, *(str(part) for part in parts)))
    secret = settings.EVIDENCE_WRITE_SECRET.encode()
    inner = hashlib.sha256(secret + message.encode()).digest()
    return hashlib.sha256(secret + inner).hexdigest()


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
            authorization = _signed_write_authorization(
                "wallet-register", membership.pk, address
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT lamto_security.accounts_register_signer_wallet(%s, %s, %s)",
                    [membership.pk, address, authorization],
                )
                wallet_id = cursor.fetchone()[0]
            wallet = SignerWallet.objects.get(pk=wallet_id)
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
    authorizer_id = getattr(authorizing_membership, "pk", None)
    owner_membership_id = (
        SignerWallet.objects.filter(pk=getattr(wallet, "pk", None))
        .values_list("membership_id", flat=True)
        .first()
    )
    if authorizer_id is None or owner_membership_id is None:
        raise PermissionDenied("Wallet revocation authorization is invalid.")
    locked_memberships = {
        membership.pk: membership
        for membership in OrganizationMembership.objects.select_related(
            "user", "organization"
        )
        .select_for_update()
        .filter(pk__in={owner_membership_id, authorizer_id})
        .order_by("pk")
    }
    authorizer = locked_memberships.get(authorizer_id)
    owner_membership = locked_memberships.get(owner_membership_id)
    if (
        authorizer is None
        or owner_membership is None
        or not authorizer.active
        or authorizer.role not in SIGNING_ROLES
    ):
        raise PermissionDenied("Membership is not eligible to authorize wallet revocation.")
    wallet = SignerWallet.objects.select_for_update().select_related("membership").get(pk=wallet.pk)
    if wallet.membership.organization_id != authorizer.organization_id:
        raise PermissionDenied("Wallet revocation requires the same organization.")
    if not wallet.active:
        return wallet
    authorization = _signed_write_authorization(
        "wallet-revoke", wallet.pk, authorizer.pk
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT lamto_security.accounts_revoke_signer_wallet(%s, %s, %s)",
            [wallet.pk, authorizer.pk, authorization],
        )
    wallet.refresh_from_db()
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
    if not isinstance(event_type, int) or isinstance(event_type, bool):
        raise ValueError("Evidence event type must be an integer from 1 through 11.")
    schema = EVIDENCE_PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise ValueError("Evidence event type must be an integer from 1 through 11.")
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValidationError("Evidence payload must be an object with known fields.")
    required, optional = schema
    if set(payload) - required.keys() - optional.keys():
        raise ValidationError("Evidence payload contains fields outside its event schema.")
    if missing := required.keys() - payload.keys():
        raise ValidationError(f"Evidence payload is missing required fields: {', '.join(sorted(missing))}.")
    for field, value in payload.items():
        shape = required.get(field, optional.get(field))
        if isinstance(shape, str) and shape not in OPAQUE_PAYLOAD_SHAPES:
            raise ValidationError(
                f"Evidence payload field {field!r} uses non-opaque shape {shape!r}."
            )
        valid = (
            (shape == "id" and type(value) is int and value > 0)
            or (shape == "positive_int" and type(value) is int and value > 0)
            or (shape == "money" and type(value) is int and value >= 0)
            or (shape == "bool" and type(value) is bool)
            or (shape == "hash" and isinstance(value, str) and bool(HASH_RE.fullmatch(value)))
            or (shape == "bytes32" and isinstance(value, str) and bool(BYTES32_RE.fullmatch(value)))
            or (
                shape == "hashes" and isinstance(value, list) and bool(value)
                and all(isinstance(item, str) and HASH_RE.fullmatch(item) for item in value)
            )
            or (
                shape == "timestamp" and isinstance(value, str)
                and bool(UTC_RFC3339_RE.fullmatch(value))
                and _is_valid_utc_timestamp(value)
            )
            or (isinstance(shape, frozenset) and type(value) is str and value in shape)
        )
        if not valid:
            raise ValidationError(f"Evidence payload field {field!r} has an invalid value.")


def _is_valid_utc_timestamp(value):
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


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
    membership = _active_signing_membership(membership, lock=True)
    if not BYTES32_RE.fullmatch(event_id) or not BYTES32_RE.fullmatch(previous_hash):
        raise ValidationError("Event ID and previous hash must be 0x-prefixed bytes32 values.")
    wallet = SignerWallet.objects.select_for_update().filter(
        membership=membership, active=True
    ).first()
    if wallet is None:
        raise PermissionDenied("Membership has no active signing wallet.")
    normalized_payload = json.loads(canonical_bytes(payload))
    canonical_payload = canonical_bytes(normalized_payload).decode("utf-8")
    typed_data = build_evidence_typed_data(event_id, event_type, "0x" + digest, previous_hash)
    try:
        signature = normalize_signature(signature)
        recovered = recover_signer(typed_data, signature)
    except Exception as exc:
        raise ValidationError("Evidence signature is invalid.") from exc
    # MetaMask / eth_account may differ on checksum casing; compare canonically.
    if recovered.lower() != wallet.address.lower():
        raise PermissionDenied(
            "Evidence signature does not match the active wallet "
            f"(signed as {recovered}, expected {wallet.address})."
        )
    authorization = _signed_write_authorization(
        "evidence-queue",
        event_id,
        int(event_type),
        digest,
        previous_hash,
        signature,
        wallet.pk,
        membership.pk,
        canonical_payload,
    )
    existing = BlockchainOutboxEvent.objects.filter(event_id=event_id).first()
    if existing:
        return _resolve_duplicate(
            existing, event_type, normalized_payload, digest, previous_hash, wallet, signature
        )
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT lamto_security.evidence_insert_outbox_event(
                        %s, %s::smallint, %s::jsonb, %s, %s, %s, %s, %s, %s, %s
                    )""",
                    [event_id, event_type, canonical_payload, digest, previous_hash,
                     signature, wallet.pk, membership.pk, canonical_payload, authorization],
                )
                event_id_pk = cursor.fetchone()[0]
            event = BlockchainOutboxEvent.objects.get(pk=event_id_pk)
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
