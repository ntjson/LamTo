import json
from datetime import timedelta
from threading import Barrier, Thread

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
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
from lamto.evidence.canonical import canonical_bytes, payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    EvidenceConflict,
    _signed_write_authorization,
    _validate_payload,
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    revoke_wallet,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.evidence.tests.test_signatures import high_s_signature


HASH = "a" * 64
OTHER_HASH = "b" * 64
TIMESTAMP = "2026-07-13T02:00:00.000000Z"
VALID_PAYLOADS = {
    EvidenceType.PROPOSAL_CREATED: {
        "proposal_id": 1, "proposal_version": 1, "record_id": 2,
        "work_order_id": 3, "case_id": 4, "report_id": 5,
        "amount_vnd": 18_500_000, "proposal_snapshot_hash": HASH,
        "work_snapshot_hash": HASH, "case_snapshot_hash": HASH,
        "report_snapshot_hash": HASH, "quotation_original_hash": HASH,
        "quotation_redacted_hash": HASH,
    },
    EvidenceType.BOARD_APPROVAL: {
        "proposal_hash": HASH, "decision": "APPROVE",
        "actor_organization_id": 1, "decision_timestamp": TIMESTAMP,
    },
    EvidenceType.REPRESENTATIVE_APPROVAL: {
        "proposal_hash": HASH, "decision": "APPROVE",
        "actor_organization_id": 1, "decision_timestamp": TIMESTAMP,
    },
    EvidenceType.EMERGENCY_AUTHORIZATION: {
        "work_order_id": 1, "reason_digest": HASH,
        "available_estimate_vnd": 1_000_000,
        "authorization_timestamp": TIMESTAMP, "drill": False,
    },
    EvidenceType.EMERGENCY_OUTCOME: {
        "decision": "RATIFY", "result": "RATIFIED", "reason_digest": HASH,
        "deadline_result": "MET", "decision_timestamp": TIMESTAMP, "drill": False,
    },
    EvidenceType.WORK_ACCEPTANCE: {
        "work_order_id": 1, "actual_cost_vnd": 1_000_000,
        "acceptance_timestamp": TIMESTAMP, "invoice_original_hash": HASH,
        "invoice_redacted_hash": HASH, "acceptance_report_original_hash": HASH,
        "acceptance_report_redacted_hash": HASH, "photo_hashes": [HASH], "drill": False,
    },
    EvidenceType.PAYMENT_RECORDED: {
        "payment_id": 1, "amount_vnd": 1_000_000,
        "bank_reference_digest": HASH, "external_status": "SETTLED",
        "external_timestamp": TIMESTAMP, "payment_proof_original_hash": HASH,
        "payment_proof_redacted_hash": HASH,
    },
    EvidenceType.PAYMENT_VERIFIED: {
        "payment_hash": HASH, "decision": "APPROVE",
        "verification_result": "MATCH", "verification_timestamp": TIMESTAMP,
    },
    EvidenceType.PUBLICATION_SNAPSHOT: {
        "publication_id": 1, "prerequisite_event_hashes": [HASH],
        "resident_payload_hash": HASH, "document_hashes": [HASH],
        "publication_timestamp": TIMESTAMP, "drill": False,
    },
    EvidenceType.FUND_ENTRY: {
        "fund_entry_id": 1, "entry_type": "INFLOW", "amount_vnd": 1_000_000,
        "source_document_original_hash": HASH,
        "source_document_redacted_hash": HASH,
        "maker_membership_id": 1, "checker_membership_id": 2,
        "entry_timestamp": TIMESTAMP,
    },
}


@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
)
class EvidenceOutboxTests(TestCase):
    def valid_payload(self, event_type=EvidenceType.PROPOSAL_CREATED, **changes):
        return {**VALID_PAYLOADS[event_type], **changes}

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

    def test_wallet_registration_rejects_high_s_proof(self):
        membership = self.make_membership(suffix="high-s-proof")
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature

        with self.assertRaises(ValidationError):
            register_wallet(membership, account.address, high_s_signature(proof))
        self.assertFalse(SignerWallet.objects.filter(membership=membership).exists())

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
        payload = self.valid_payload()
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
        self.assertEqual(event.signature, "0x" + bytes.fromhex(signature.removeprefix("0x")).hex())
        self.assertTrue(AuditEvent.objects.filter(action="evidence.queue", target_id=event.event_id).exists())

    def test_duplicate_validates_signature_and_all_immutable_fields_before_lookup(self):
        membership = self.make_membership(suffix="duplicate-fields")
        account, _ = self.register(membership)
        event_id = "0x" + "21" * 32
        payload = self.valid_payload()
        zero_hash = "0x" + "00" * 32
        signature = self.sign_event(account, event_id, 1, payload)
        with transaction.atomic():
            queue_signed_event(event_id, 1, payload, zero_hash, membership, signature)

        with transaction.atomic(), self.assertRaises(ValidationError):
            queue_signed_event(event_id, 1, payload, zero_hash, membership, "0x00")

        changed_previous = "0x" + "01" * 32
        changed_previous_signature = self.sign_event(
            account, event_id, 1, payload, changed_previous
        )
        with transaction.atomic(), self.assertRaises(EvidenceConflict):
            queue_signed_event(
                event_id,
                1,
                payload,
                changed_previous,
                membership,
                changed_previous_signature,
            )

        changed_type_payload = self.valid_payload(EvidenceType.BOARD_APPROVAL)
        changed_type_signature = self.sign_event(account, event_id, 2, changed_type_payload)
        with transaction.atomic(), self.assertRaises(EvidenceConflict):
            queue_signed_event(
                event_id, 2, changed_type_payload, zero_hash, membership, changed_type_signature
            )

        replacement_account, _ = self.register(membership)
        replacement_signature = self.sign_event(replacement_account, event_id, 1, payload)
        with transaction.atomic(), self.assertRaises(EvidenceConflict):
            queue_signed_event(
                event_id, 1, payload, zero_hash, membership, replacement_signature
            )

    def test_queue_rejects_conflict_wallet_mismatch_and_missing_caller_transaction(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "22" * 32
        payload = self.valid_payload()
        signature = self.sign_event(account, event_id, 1, payload)
        with self.assertRaises(RuntimeError):
            queue_signed_event(event_id, 1, payload, "0x" + "00" * 32, membership, signature)
        with transaction.atomic():
            queue_signed_event(event_id, 1, payload, "0x" + "00" * 32, membership, signature)
        changed_payload = self.valid_payload(proposal_version=2)
        changed_signature = self.sign_event(account, event_id, 1, changed_payload)
        with transaction.atomic(), self.assertRaises(EvidenceConflict):
            queue_signed_event(
                event_id,
                1,
                changed_payload,
                "0x" + "00" * 32,
                membership,
                changed_signature,
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
        payload = self.valid_payload()
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

    def test_wallet_database_boundary_rejects_orm_queryset_and_raw_bypasses(self):
        maintenance = self.make_membership(
            OrganizationMembership.Role.MAINTENANCE, "direct-wallet"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignerWallet.objects.create(membership=maintenance, address=Account.create().address)

        membership = self.make_membership(suffix="direct-revoke")
        _, wallet = self.register(membership)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignerWallet.objects.filter(pk=wallet.pk).update(
                active=False, revoked_at=timezone.now()
            )
        self.assertFalse(
            SignerAuthorizationRequest.objects.filter(
                wallet=wallet, action=SignerAuthorizationRequest.Action.REVOKE
            ).exists()
        )
        self.assertFalse(
            AuditEvent.objects.filter(action="wallet.revoke", target_id=str(wallet.pk)).exists()
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignerWallet.objects.filter(pk=wallet.pk).delete()

        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO accounts_signerwallet
                    (membership_id, address, active, registered_at, revoked_at)
                VALUES (%s, %s, TRUE, NOW(), NULL)
                """,
                [maintenance.pk, Account.create().address],
            )

    def test_application_role_cannot_enable_the_old_guc_bypass(self):
        membership = self.make_membership(suffix="app-role-guc")
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT set_config('lamto.wallet_transition', 'on', true)")
            cursor.execute(
                """
                INSERT INTO accounts_signerwallet
                    (membership_id, address, active, registered_at, revoked_at)
                VALUES (%s, %s, TRUE, NOW(), NULL)
                """,
                [membership.pk, Account.create().address],
            )

    def test_runtime_role_cannot_call_privileged_write_procedures_without_proof(self):
        membership = self.make_membership(suffix="runtime-procedure-boundary")
        account, wallet = self.register(membership)
        event_id = "0x" + "77" * 32
        payload = self.valid_payload()
        previous_hash = "0x" + "00" * 32
        signature = self.sign_event(account, event_id, 1, payload, previous_hash)
        canonical_payload = canonical_bytes(payload).decode("utf-8")
        registration_address = Account.create().address
        registration_authorization = _signed_write_authorization(
            "wallet-register", membership.pk, registration_address
        )
        queue_authorization = _signed_write_authorization(
            "evidence-queue", event_id, 1, payload_hash(payload), previous_hash,
            signature, wallet.pk, membership.pk, canonical_payload
        )

        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE lamto_app")
            cursor.execute(
                "SELECT has_function_privilege(current_user, "
                "'lamto_security.accounts_register_signer_wallet(bigint,text,text)', 'EXECUTE')"
            )
            self.assertFalse(cursor.fetchone()[0])
            cursor.execute(
                "SELECT has_function_privilege(current_user, "
                "'lamto_security.evidence_insert_outbox_event(text,smallint,jsonb,text,text,text,bigint,bigint,text,text)', 'EXECUTE')"
            )
            self.assertFalse(cursor.fetchone()[0])
            cursor.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class "
                "WHERE oid = 'accounts_signerwallet'::regclass"
            )
            self.assertNotEqual(cursor.fetchone()[0], "lamto_app")
            cursor.execute(
                "SELECT lamto_security.accounts_register_signer_wallet(%s, %s, %s)",
                [membership.pk, registration_address, registration_authorization],
            )

        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE lamto_app")
            cursor.execute(
                """SELECT lamto_security.evidence_insert_outbox_event(
                    %s, 1, %s::jsonb, %s, %s, %s, %s, %s, %s, %s
                )""",
                [
                    event_id,
                    canonical_payload,
                    payload_hash(payload),
                    previous_hash,
                    signature,
                    wallet.pk,
                    membership.pk,
                    canonical_payload,
                    queue_authorization,
                ],
            )

        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("ALTER TABLE accounts_signerwallet DISABLE TRIGGER signer_wallet_history")

        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE evidence_blockchainoutboxevent")

    def test_trusted_executor_runs_the_signed_service_path(self):
        membership = self.make_membership(suffix="trusted-executor")
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        event_id = "0x" + "88" * 32
        payload = self.valid_payload()

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL ROLE lamto_writer")
            wallet = register_wallet(membership, account.address.lower(), proof)
            event = queue_signed_event(
                event_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                "0x" + "00" * 32,
                membership,
                self.sign_event(account, event_id, EvidenceType.PROPOSAL_CREATED, payload),
            )

        self.assertTrue(wallet.active)
        self.assertEqual(event.signer_wallet_id, wallet.pk)

    def test_outbox_database_boundary_rejects_direct_rows_and_raw_truncate(self):
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE evidence_blockchainoutboxevent")

        membership = self.make_membership(suffix="direct-outbox")
        account, wallet = self.register(membership)
        event_id = "0x" + "45" * 32
        payload = self.valid_payload()
        signature = self.sign_event(account, event_id, 1, payload)

        with self.assertRaises(IntegrityError), transaction.atomic():
            BlockchainOutboxEvent.objects.create(
                event_id=event_id,
                event_type=1,
                payload=payload,
                payload_hash="0" * 64,
                previous_hash="0x" + "00" * 32,
                signature=signature,
                signer_wallet=wallet,
            )
        self.assertFalse(AuditEvent.objects.filter(action="evidence.queue", target_id=event_id).exists())

        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO evidence_blockchainoutboxevent
                    (event_id, event_type, payload, payload_hash, previous_hash, signature,
                     signer_wallet_id, status, attempts, transaction_hash, receipt, last_error,
                     created_at, updated_at)
                VALUES (%s, 1, %s::jsonb, %s, %s, %s, %s, 'PENDING', 0, '', '{}'::jsonb,
                        '', NOW(), NOW())
                """,
                [
                    "0x" + "46" * 32,
                    '{"proposal_version":1}',
                    "0" * 64,
                    "0x" + "00" * 32,
                    signature,
                    wallet.pk,
                ],
            )

    def test_all_evidence_types_have_complete_payload_schemas(self):
        self.assertEqual(
            set(VALID_PAYLOADS), set(EvidenceType) - {EvidenceType.RESERVED_10}
        )
        for event_type, payload in VALID_PAYLOADS.items():
            with self.subTest(event_type=event_type):
                _validate_payload(event_type, payload)

    def test_payload_schemas_reject_missing_fields_and_value_slot_smuggling(self):
        for event_type, payload in VALID_PAYLOADS.items():
            incomplete = dict(payload)
            incomplete.pop(next(iter(incomplete)))
            with self.subTest(event_type=event_type), self.assertRaises(ValidationError):
                _validate_payload(event_type, incomplete)

        for field, value in (
            ("record_id", "private bank account 1234"),
            ("proposal_version", True),
            ("amount_vnd", True),
            ("proposal_id", [1]),
            ("proposal_snapshot_hash", {"digest": HASH}),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                _validate_payload(
                    EvidenceType.PROPOSAL_CREATED,
                    self.valid_payload(**{field: value}),
                )

    def test_payload_schemas_reject_bad_enums_timestamps_and_digest_lists(self):
        cases = (
            (EvidenceType.BOARD_APPROVAL, {"decision": "private approval reason"}),
            (EvidenceType.BOARD_APPROVAL, {"decision_timestamp": "not-a-timestamp"}),
            (EvidenceType.EMERGENCY_AUTHORIZATION, {"drill": 0}),
            (EvidenceType.WORK_ACCEPTANCE, {"photo_hashes": []}),
            (EvidenceType.WORK_ACCEPTANCE, {"photo_hashes": [HASH, 1]}),
            (EvidenceType.PUBLICATION_SNAPSHOT, {"document_hashes": "not-a-list"}),
            (EvidenceType.FUND_ENTRY, {"entry_type": "BANK_ACCOUNT_DETAILS"}),
        )
        for event_type, changes in cases:
            with self.subTest(event_type=event_type, changes=changes), self.assertRaises(
                ValidationError
            ):
                _validate_payload(event_type, self.valid_payload(event_type, **changes))


    def test_queue_rejects_non_integer_event_type(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "66" * 32
        payload = self.valid_payload()
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

        safe_payload = self.valid_payload(photo_hash=OTHER_HASH)
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

    def test_queue_rejects_unknown_alternate_and_nested_sensitive_payload_keys(self):
        membership = self.make_membership(suffix="payload-schema")
        account, _ = self.register(membership)
        for index, payload in enumerate(
            (
                {"account_number": "123"},
                {"identity_number": "ABC"},
                {"full_name": "Private Person"},
                {"report_body": "private"},
                {"evidence": {"accountNumber": "123"}},
                {"report_snapshot_hash": "raw report body"},
                {"proposal_version": 1, "unexpected": "value"},
            ),
            start=1,
        ):
            event_id = "0x" + f"{index + 128:02x}" * 32
            signature = self.sign_event(account, event_id, 1, payload)
            with self.subTest(payload=payload), transaction.atomic(), self.assertRaises(
                ValidationError
            ):
                queue_signed_event(
                    event_id,
                    1,
                    payload,
                    "0x" + "00" * 32,
                    membership,
                    signature,
                )

    def test_idempotent_lookup_does_not_bypass_membership_authorization(self):
        membership = self.make_membership()
        account, _ = self.register(membership)
        event_id = "0x" + "99" * 32
        payload = self.valid_payload()
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


@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
)
class ConcurrentOutboxTests(TransactionTestCase):
    def _fixture_teardown(self):
        # The database trigger suite intentionally rejects Django's DELETE-based
        # flush. This class has one test and the whole test database is dropped
        # by the runner, so no trigger-bypassing cleanup is needed here.
        pass

    def make_membership(self, suffix):
        building = Building.objects.create(name=f"Building {suffix}")
        organization = Organization.objects.create(
            building=building,
            name=f"Organization {suffix}",
            kind=Organization.Kind.OPERATOR,
        )
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        return OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.OPERATOR
        )

    def register(self, membership, account):
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        return register_wallet(membership, account.address, proof)

    def sign_event(self, account, event_id, payload):
        typed = build_evidence_typed_data(
            event_id,
            EvidenceType.PROPOSAL_CREATED,
            "0x" + payload_hash(payload),
            "0x" + "00" * 32,
        )
        return Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()

    def test_concurrent_conflicting_event_id_raises_evidence_conflict_without_poisoning_transaction(self):
        first_membership = self.make_membership("race-first")
        second_membership = self.make_membership("race-second")
        first_account = Account.create()
        second_account = Account.create()
        self.register(first_membership, first_account)
        self.register(second_membership, second_account)
        event_id = "0x" + "aa" * 32
        payload = VALID_PAYLOADS[EvidenceType.PROPOSAL_CREATED]
        signatures = (
            self.sign_event(first_account, event_id, payload),
            self.sign_event(second_account, event_id, payload),
        )
        memberships = (first_membership.pk, second_membership.pk)
        barrier = Barrier(2)
        outcomes = [None, None]

        def submit(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                membership = OrganizationMembership.objects.get(pk=memberships[index])
                with transaction.atomic():
                    outcomes[index] = queue_signed_event(
                        event_id,
                        EvidenceType.PROPOSAL_CREATED,
                        payload,
                        "0x" + "00" * 32,
                        membership,
                        signatures[index],
                    )
            except BaseException as exc:  # surface thread failures in the assertion below
                outcomes[index] = exc
            finally:
                close_old_connections()

        threads = [Thread(target=submit, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(
            sum(isinstance(outcome, BlockchainOutboxEvent) for outcome in outcomes), 1
        )
        self.assertEqual(
            sum(isinstance(outcome, EvidenceConflict) for outcome in outcomes), 1
        )
        self.assertEqual(
            BlockchainOutboxEvent.objects.filter(event_id=event_id).count(), 1
        )
