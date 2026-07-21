import secrets
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import PAYMENT_RECORD, PAYMENT_VERIFY, WORK_ACCEPT
from lamto.audit.models import AuditEvent
from lamto.documents.models import Document
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet, utc_rfc3339
from lamto.finance.acceptance import accept_work
from lamto.finance.models import PaymentEvidence, PaymentVerification
from lamto.finance.payments import (
    allocate_payment_id,
    build_payment_evidence_typed_data,
    build_payment_verification_evidence_payload,
    build_payment_verification_evidence_typed_data,
    normalize_bank_reference,
    record_payment,
    verify_payment,
)
from lamto.finance.tests.test_acceptance import WorkAcceptanceTests as _AcceptanceFixtures


class PaymentMakerCheckerTests(TestCase):
    _unique = _AcceptanceFixtures._unique
    make_signer = _AcceptanceFixtures.make_signer
    document_pair = _AcceptanceFixtures.document_pair
    photo = _AcceptanceFixtures.photo
    sign_acceptance = _AcceptanceFixtures.sign_acceptance

    def test_verified_signature_payload_preserves_approve_decision(self):
        payment = SimpleNamespace(
            outbox_event=SimpleNamespace(payload_hash="a" * 64),
            recorded_at=timezone.now(),
        )
        payload = build_payment_verification_evidence_payload(payment, "VERIFIED")
        typed = build_payment_verification_evidence_typed_data(
            payment, None, "VERIFIED", "0x" + "11" * 32
        )

        self.assertEqual(payload["decision"], "APPROVE")
        self.assertEqual(typed["message"]["payloadHash"], "0x" + payload_hash(payload))

    def make_completed_work_inputs(self):
        (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
        ) = _AcceptanceFixtures.make_completed_work_inputs(self)
        proof_original, proof_redacted = self.document_pair(
            work.case.building,
            Document.Kind.PAYMENT_PROOF,
            board.user,
            51,
            "payment-proof",
        )
        return (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            proof_original,
            proof_redacted,
        )

    def payment_time(self):
        return timezone.now()

    def make_second_board(self, building, suffix="board-verifier"):
        membership, account = self.make_signer(
            building, None, PAYMENT_VERIFY, suffix
        )
        self.accounts[membership.pk] = account
        return membership

    def accept_default(self, inputs):
        (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            proof_original,
            proof_redacted,
        ) = inputs
        signature, event_id, timestamp = self.sign_acceptance(
            work,
            board,
            invoice_original=invoice_original,
            invoice_redacted=invoice_redacted,
            acceptance_original=acceptance_original,
            acceptance_redacted=acceptance_redacted,
        )
        acceptance = accept_work(
            work,
            board,
            18_500_000,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            signature,
            event_id,
            timestamp=timestamp,
        )
        return acceptance, board, proof_original, proof_redacted

    def next_payment_id(self):
        # Reserve via nextval so sign and record share one concurrent-safe id.
        return allocate_payment_id()

    def sign_payment(
        self,
        acceptance,
        membership,
        bank_reference="BANK-2026-001",
        amount_vnd=18_500_000,
        external_status="COMPLETED",
        completed_at=None,
        proof_original=None,
        proof_redacted=None,
        event_id=None,
        payment_id=None,
    ):
        if event_id is None:
            event_id = "0x" + secrets.token_hex(32)
        completed_at = completed_at or self.payment_time()
        payment_id = payment_id or self.next_payment_id()
        typed_data = build_payment_evidence_typed_data(
            acceptance,
            membership,
            payment_id,
            bank_reference,
            amount_vnd,
            external_status,
            completed_at,
            proof_original,
            proof_redacted,
            event_id,
        )
        return (
            Account.sign_message(
                encode_typed_data(full_message=typed_data), self.accounts[membership.pk].key
            ).signature.hex(),
            event_id,
            completed_at,
            payment_id,
        )

    def sign_payment_verification(
        self, payment, membership, decision="VERIFIED", event_id=None, timestamp=None
    ):
        if event_id is None:
            event_id = "0x" + secrets.token_hex(32)
        timestamp = timestamp or payment.recorded_at
        typed_data = build_payment_verification_evidence_typed_data(
            payment, membership, decision, event_id, timestamp=timestamp
        )
        return (
            Account.sign_message(
                encode_typed_data(full_message=typed_data), self.accounts[membership.pk].key
            ).signature.hex(),
            event_id,
            timestamp,
        )

    def test_payment_recorder_cannot_verify_own_evidence(self):
        (
            work,
            board_recorder,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            proof_original,
            proof_redacted,
        ) = self.make_completed_work_inputs()
        acceptance_signature, acceptance_event, acceptance_ts = self.sign_acceptance(
            work,
            board_recorder,
            invoice_original=invoice_original,
            invoice_redacted=invoice_redacted,
            acceptance_original=acceptance_original,
            acceptance_redacted=acceptance_redacted,
        )
        acceptance = accept_work(
            work,
            board_recorder,
            18_500_000,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            acceptance_signature,
            acceptance_event,
            timestamp=acceptance_ts,
        )
        payment_signature, payment_event, completed_at, payment_id = self.sign_payment(
            acceptance,
            board_recorder,
            proof_original=proof_original,
            proof_redacted=proof_redacted,
        )
        payment = record_payment(
            acceptance,
            board_recorder,
            "BANK-2026-001",
            18_500_000,
            "COMPLETED",
            completed_at,
            proof_original,
            proof_redacted,
            payment_signature,
            payment_event,
            payment_id,
        )

        verification_signature, verification_event, _ = self.sign_payment_verification(
            payment, board_recorder
        )
        with self.assertRaises(PermissionDenied):
            verify_payment(
                payment,
                board_recorder,
                "VERIFIED",
                "Matches accepted cost",
                verification_signature,
                verification_event,
            )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="payment.verify",
                target_id=str(payment.pk),
                result="denied",
            ).exists()
        )

    def test_independent_verifier_can_verify_and_rejection_is_immutable(self):
        inputs = self.make_completed_work_inputs()
        acceptance, board_recorder, proof_original, proof_redacted = self.accept_default(inputs)
        verifier = self.make_second_board(acceptance.work_order.case.building)
        payment_signature, payment_event, completed_at, payment_id = self.sign_payment(
            acceptance,
            board_recorder,
            bank_reference="BANK-2026-002",
            proof_original=proof_original,
            proof_redacted=proof_redacted,
        )
        payment = record_payment(
            acceptance,
            board_recorder,
            "BANK-2026-002",
            18_500_000,
            "COMPLETED",
            completed_at,
            proof_original,
            proof_redacted,
            payment_signature,
            payment_event,
            payment_id,
        )
        self.assertEqual(payment.outbox_event.event_type, EvidenceType.PAYMENT_RECORDED)
        self.assertEqual(payment.outbox_event.payload["external_status"], "SETTLED")
        self.assertEqual(
            payment.outbox_event.payload["bank_reference_digest"],
            payload_hash({"bank_reference": "BANK-2026-002"}),
        )
        self.assertEqual(
            payment.outbox_event.previous_hash,
            "0x" + acceptance.outbox_event.payload_hash,
        )

        verification_signature, verification_event, timestamp = self.sign_payment_verification(
            payment, verifier, decision="REJECTED", event_id="0x" + secrets.token_hex(32)
        )
        verification = verify_payment(
            payment,
            verifier,
            "REJECTED",
            "Amount mismatch on proof",
            verification_signature,
            verification_event,
            timestamp=timestamp,
        )
        self.assertEqual(verification.decision, PaymentVerification.Decision.REJECTED)
        self.assertEqual(verification.outbox_event.payload["decision"], "REJECT")
        self.assertEqual(verification.outbox_event.payload["verification_result"], "MISMATCH")
        self.assertEqual(
            verification.outbox_event.previous_hash, "0x" + payment.outbox_event.payload_hash
        )
        verification.reason = "changed"
        with self.assertRaises(ValueError):
            verification.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentVerification.objects.filter(pk=verification.pk).update(reason="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentVerification.objects.filter(pk=verification.pk).delete()

    def test_payment_amount_must_match_and_bank_reference_is_unique(self):
        inputs = self.make_completed_work_inputs()
        acceptance, board, proof_original, proof_redacted = self.accept_default(inputs)
        wrong_signature, wrong_event, completed_at, wrong_payment_id = self.sign_payment(
            acceptance,
            board,
            bank_reference="BANK-2026-003",
            amount_vnd=18_400_000,
            proof_original=proof_original,
            proof_redacted=proof_redacted,
        )
        with self.assertRaises(ValidationError):
            record_payment(
                acceptance,
                board,
                "BANK-2026-003",
                18_400_000,
                "COMPLETED",
                completed_at,
                proof_original,
                proof_redacted,
                wrong_signature,
                wrong_event,
                wrong_payment_id,
            )
        payment_signature, payment_event, completed_at, payment_id = self.sign_payment(
            acceptance,
            board,
            bank_reference="BANK-2026-003",
            amount_vnd=18_500_000,
            proof_original=proof_original,
            proof_redacted=proof_redacted,
        )
        payment = record_payment(
            acceptance,
            board,
            "  bank-2026-003  ",
            18_500_000,
            "COMPLETED",
            completed_at,
            proof_original,
            proof_redacted,
            payment_signature,
            payment_event,
            payment_id,
        )
        self.assertEqual(payment.bank_reference, "BANK-2026-003")
        self.assertEqual(normalize_bank_reference(" bank-2026-003 "), "BANK-2026-003")

        second_inputs = self.make_completed_work_inputs()
        # Remap unique emails by creating via accept path on a fresh work order is heavy;
        # reuse uniqueness check via second payment on a second acceptance requires another work order.
        second_acceptance, second_board, second_proof_original, second_proof_redacted = (
            self.accept_default(second_inputs)
        )
        second_signature, second_event, second_completed, second_payment_id = self.sign_payment(
            second_acceptance,
            second_board,
            bank_reference="BANK-2026-003",
            proof_original=second_proof_original,
            proof_redacted=second_proof_redacted,
            event_id="0x" + secrets.token_hex(32),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            record_payment(
                second_acceptance,
                second_board,
                "BANK-2026-003",
                18_500_000,
                "COMPLETED",
                second_completed,
                second_proof_original,
                second_proof_redacted,
                second_signature,
                second_event,
                second_payment_id,
            )

    def test_payment_is_insert_only_and_db_rejects_self_verification(self):
        inputs = self.make_completed_work_inputs()
        acceptance, board, proof_original, proof_redacted = self.accept_default(inputs)
        payment_signature, payment_event, completed_at, payment_id = self.sign_payment(
            acceptance,
            board,
            bank_reference="BANK-2026-004",
            proof_original=proof_original,
            proof_redacted=proof_redacted,
        )
        payment = record_payment(
            acceptance,
            board,
            "BANK-2026-004",
            18_500_000,
            "COMPLETED",
            completed_at,
            proof_original,
            proof_redacted,
            payment_signature,
            payment_event,
            payment_id,
        )
        payment.amount_vnd = 1
        with self.assertRaises(ValueError):
            payment.save()
        with self.assertRaises(ValueError):
            payment.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentEvidence.objects.filter(pk=payment.pk).update(amount_vnd=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentEvidence.objects.filter(pk=payment.pk).delete()

        verifier = self.make_second_board(acceptance.work_order.case.building, "board-v2")
        verification_signature, verification_event, timestamp = self.sign_payment_verification(
            payment, verifier
        )
        # Application layer already blocks same user; force same-user verification row at DB.
        with self.assertRaises(IntegrityError), transaction.atomic():
            from lamto.evidence.models import BlockchainOutboxEvent
            from lamto.accounts.models import SignerWallet

            wallet = SignerWallet.objects.get(membership=board, active=True)
            event = BlockchainOutboxEvent.objects.create(
                event_id="0x" + secrets.token_hex(32),
                event_type=EvidenceType.PAYMENT_VERIFIED,
                payload={"x": 1},
                payload_hash="a" * 64,
                previous_hash="0x" + "00" * 32,
                signature="0x" + "ab" * 65,
                signer_wallet=wallet,
                status=BlockchainOutboxEvent.Status.PENDING,
            )
            # Bypass ORM path and insert verification with recorder as verifier via SQL
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO finance_paymentverification
                    (decision, reason, signature, verified_at, membership_id, outbox_event_id,
                     payment_id, wallet_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        "VERIFIED",
                        "self",
                        "0x" + "cd" * 65,
                        timezone.now().isoformat(),
                        board.pk,
                        event.pk,
                        payment.pk,
                        wallet.pk,
                    ],
                )
