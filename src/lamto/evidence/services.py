import json
import secrets
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address

from lamto.accounts.models import (
    OrganizationMembership,
    SignerAuthorizationRequest,
    SignerWallet,
    WalletRegistrationChallenge,
)
from lamto.audit.services import record_audit

from .canonical import canonical_bytes, payload_hash
from .models import BlockchainOutboxEvent
from .signatures import BYTES32_RE, build_evidence_typed_data, recover_signer


SIGNING_ROLES = {
    OrganizationMembership.Role.OPERATOR,
    OrganizationMembership.Role.BOARD,
    OrganizationMembership.Role.RESIDENT_REP,
}
PRIVATE_PAYLOAD_KEYS = {
    "report_text",
    "photo",
    "photos",
    "bank_account",
    "bank_details",
    "bank_reference",
    "display_name",
    "email",
    "personal_profile",
    "phone",
    "profile",
    "private_key",
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
                recovered = Account.recover_message(
                    encode_typed_data(full_message=_registration_typed_data(challenge)),
                    signature=proof_signature,
                )
            except Exception:
                recovered = None
            if recovered != address:
                error = "Wallet proof does not match the submitted address."
        if error is None:
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


def _reject_private_payload(value):
    if isinstance(value, dict):
        if any(key.casefold() in PRIVATE_PAYLOAD_KEYS for key in value if isinstance(key, str)):
            raise ValidationError("Evidence payload contains private data; include hashes only.")
        for item in value.values():
            _reject_private_payload(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private_payload(item)


def _resolve_duplicate(existing, digest, membership):
    if (
        existing.signer_wallet.membership_id != membership.pk
        or not existing.signer_wallet.active
    ):
        raise PermissionDenied("Evidence event belongs to another active signer wallet.")
    if existing.payload_hash == digest:
        return existing
    raise EvidenceConflict("Event ID already exists with a different payload hash.")


def queue_signed_event(
    event_id, event_type, payload, previous_hash, membership, signature
) -> BlockchainOutboxEvent:
    _require_caller_transaction()
    event_id = lowercase_identifier(event_id)
    previous_hash = lowercase_identifier(previous_hash)
    _reject_private_payload(payload)
    digest = payload_hash(payload)
    membership = _active_signing_membership(membership)
    existing = (
        BlockchainOutboxEvent.objects.select_related("signer_wallet")
        .filter(event_id=event_id)
        .first()
    )
    if existing:
        return _resolve_duplicate(existing, digest, membership)
    if not BYTES32_RE.fullmatch(event_id) or not BYTES32_RE.fullmatch(previous_hash):
        raise ValidationError("Event ID and previous hash must be 0x-prefixed bytes32 values.")
    wallet = SignerWallet.objects.filter(membership=membership, active=True).first()
    if wallet is None:
        raise PermissionDenied("Membership has no active signing wallet.")
    normalized_payload = json.loads(canonical_bytes(payload))
    typed_data = build_evidence_typed_data(event_id, event_type, "0x" + digest, previous_hash)
    try:
        recovered = recover_signer(typed_data, signature)
    except Exception as exc:
        raise ValidationError("Evidence signature is invalid.") from exc
    if recovered != wallet.address:
        raise PermissionDenied("Evidence signature does not match the active wallet.")
    signature = lowercase_identifier(signature)
    if not signature.startswith("0x"):
        signature = "0x" + signature
    try:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                payload=normalized_payload,
                payload_hash=digest,
                previous_hash=previous_hash,
                signature=signature,
                signer_wallet=wallet,
            )
    except IntegrityError:
        existing = BlockchainOutboxEvent.objects.select_related("signer_wallet").get(
            event_id=event_id
        )
        return _resolve_duplicate(existing, digest, membership)
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
