from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    SignerAuthorizationRequest,
    SignerWallet,
    WalletRegistrationChallenge,
)
from lamto.audit.models import AuditEvent
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    EvidenceConflict,
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    revoke_wallet,
)
from lamto.evidence.signatures import build_evidence_typed_data


@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
)
class EvidenceOutboxTests(TestCase):
    def make_membership(self, role=OrganizationMembership.Role.OPERATOR, suffix="one"):
        kind = OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role]
        building = Building.objects.create(name=f"Building {suffix}")
        organization = Organization.objects.create(
            building=building, name=f"Organization {suffix}", kind=kind
        )
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        return OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )

    def register(self, membership, account=None):
        account = account or Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        return account, register_wallet(membership, account.address.lower(), proof)

    def sign_event(self, account, event_id, event_type, payload, previous_hash=None):
        previous_hash = previous_hash or "0x" + "00" * 32
        typed = build_evidence_typed_data(
            event_id,
            event_type,
            "0x" + payload_hash(payload),
            previous_hash,
        )
        return Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()

    def test_evidence_type_values_are_permanent(self):
        self.assertEqual([choice.value for choice in EvidenceType], list(range(1, 12)))

    def test_wallet_registration_normalizes_address_consumes_nonce_and_handoffs(self):
        membership = self.make_membership()
        account, wallet = self.register(membership)

        self.assertEqual(wallet.address, account.address)
        self.assertTrue(wallet.active)
        self.assertIsNotNone(
            WalletRegistrationChallenge.objects.get(membership=membership).consumed_at
        )
        request = SignerAuthorizationRequest.objects.get(wallet=wallet)
        self.assertEqual(request.action, SignerAuthorizationRequest.Action.AUTHORIZE)
        self.assertEqual(request.status, SignerAuthorizationRequest.Status.PENDING)
        self.assertTrue(AuditEvent.objects.filter(action="wallet.register", target_id=str(wallet.pk)).exists())

    def test_wallet_registration_rejects_ineligible_role_and_expired_or_reused_nonce(self):
        maintenance = self.make_membership(OrganizationMembership.Role.MAINTENANCE, "maintenance")
        with self.assertRaises(PermissionDenied):
            begin_wallet_registration(maintenance)

        membership = self.make_membership(suffix="expiry")
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        WalletRegistrationChallenge.objects.filter(membership=membership).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(ValidationError):
            register_wallet(membership, account.address, proof)
        self.assertIsNotNone(
            WalletRegistrationChallenge.objects.get(membership=membership).consumed_at
        )
        with self.assertRaises(ValidationError):
            register_wallet(membership, account.address, proof)

    def test_revocation_requires_active_same_organization_authorizer_and_preserves_history(self):
        membership = self.make_membership()
        _, wallet = self.register(membership)
        outsider = self.make_membership(suffix="outsider")
        with self.assertRaises(PermissionDenied):
            revoke_wallet(wallet, outsider)

        revoked = revoke_wallet(wallet, membership)
        self.assertFalse(revoked.active)
        self.assertIsNotNone(revoked.revoked_at)
        self.assertTrue(SignerWallet.objects.filter(pk=wallet.pk).exists())
        self.assertTrue(
            SignerAuthorizationRequest.objects.filter(
                wallet=wallet, action=SignerAuthorizationRequest.Action.REVOKE
            ).exists()
        )

    def test_queue_signed_event_verifies_wallet_audits_and_is_idempotent(self):
        membership = self.make_membership()
        account, wallet = self.register(membership)
        event_id = "0x" + "AB" * 32
        normalized_id = event_id.lower()
        payload = {"amount_vnd": 18_500_000, "record_id": "abc"}
        signature = self.sign_event(account, normalized_id, EvidenceType.PROPOSAL_CREATED, payload)

        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                "0x" + "00" * 32,
                membership,
                signature,
            )
        with transaction.atomic():
            duplicate = queue_signed_event(
                normalized_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                "0x" + "00" * 32,
                membership,
                signature,
            )

        self.assertEqual(event.pk, duplicate.pk)
        self.assertEqual(event.event_id, normalized_id)
        self.assertEqual(event.payload_hash, payload_hash(payload))
        self.assertEqual(event.signer_wallet, wallet)
        self.assertEqual(event.status, BlockchainOutboxEvent.Status.PENDING)
        self.assertTrue(AuditEvent.objects.filter(action="evidence.queue", target_id=event.event_id).exists())

    def test_queue_rejects_conflict_wallet_mismatch_and_missing_caller_transaction(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "22" * 32
        payload = {"proposal_version": 1}
        signature = self.sign_event(account, event_id, 1, payload)
        with self.assertRaises(RuntimeError):
            queue_signed_event(event_id, 1, payload, "0x" + "00" * 32, membership, signature)
        with transaction.atomic():
            queue_signed_event(event_id, 1, payload, "0x" + "00" * 32, membership, signature)
        with transaction.atomic(), self.assertRaises(EvidenceConflict):
            queue_signed_event(
                event_id,
                1,
                {"proposal_version": 2},
                "0x" + "00" * 32,
                membership,
                signature,
            )

        other = Account.create()
        other_signature = self.sign_event(other, "0x" + "33" * 32, 1, payload)
        with transaction.atomic(), self.assertRaises(PermissionDenied):
            queue_signed_event(
                "0x" + "33" * 32,
                1,
                payload,
                "0x" + "00" * 32,
                membership,
                other_signature,
            )

    def test_database_trigger_protects_signed_identity_but_allows_delivery_updates(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "44" * 32
        payload = {"proposal_version": 1}
        signature = self.sign_event(account, event_id, 1, payload)
        with transaction.atomic():
            event = queue_signed_event(
                event_id, 1, payload, "0x" + "00" * 32, membership, signature
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            BlockchainOutboxEvent.objects.filter(pk=event.pk).update(event_type=2)
        BlockchainOutboxEvent.objects.filter(pk=event.pk).update(
            status=BlockchainOutboxEvent.Status.SUBMITTED,
            attempts=1,
            transaction_hash="0x" + "55" * 32,
        )
        event.refresh_from_db()
        self.assertEqual(event.status, BlockchainOutboxEvent.Status.SUBMITTED)

    def test_queue_rejects_non_integer_event_type(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "66" * 32
        payload = {"proposal_version": 1}
        signature = self.sign_event(account, event_id, 1, payload)

        with transaction.atomic(), self.assertRaises(ValueError):
            queue_signed_event(
                event_id, "1", payload, "0x" + "00" * 32, membership, signature
            )

    def test_queue_rejects_private_payload_fields_but_allows_hash_references(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        private_payload = {"report_text": "leak", "photo_hash": "abc"}
        event_id = "0x" + "77" * 32
        signature = self.sign_event(account, event_id, 1, private_payload)

        with transaction.atomic(), self.assertRaises(ValidationError):
            queue_signed_event(
                event_id,
                1,
                private_payload,
                "0x" + "00" * 32,
                membership,
                signature,
            )

        safe_payload = {"report_snapshot_hash": "abc", "photo_hash": "def"}
        safe_id = "0x" + "88" * 32
        safe_signature = self.sign_event(account, safe_id, 1, safe_payload)
        with transaction.atomic():
            event = queue_signed_event(
                safe_id,
                1,
                safe_payload,
                "0x" + "00" * 32,
                membership,
                safe_signature,
            )
        self.assertEqual(event.payload, safe_payload)

    def test_idempotent_lookup_does_not_bypass_membership_authorization(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "99" * 32
        payload = {"proposal_version": 1}
        signature = self.sign_event(account, event_id, 1, payload)
        with transaction.atomic():
            queue_signed_event(
                event_id, 1, payload, "0x" + "00" * 32, membership, signature
            )

        outsider = self.make_membership(suffix="duplicate-outsider")
        self.register(outsider)
        with transaction.atomic(), self.assertRaises(PermissionDenied):
            queue_signed_event(
                event_id, 1, payload, "0x" + "00" * 32, outsider, signature
            )
