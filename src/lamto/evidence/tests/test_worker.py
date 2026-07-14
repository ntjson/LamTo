from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    SignerAuthorizationRequest,
)
from lamto.audit.models import AuditEvent
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, queue_signed_event, register_wallet
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.evidence.worker import (
    process_due_outbox_events,
    process_outbox_event,
    sync_signer_authorizations,
)


HASH = "a" * 64
TIMESTAMP = "2026-07-13T02:00:00.000000Z"
PROPOSAL_PAYLOAD = {
    "proposal_id": 1,
    "proposal_version": 1,
    "record_id": 2,
    "work_order_id": 3,
    "case_id": 4,
    "report_id": 5,
    "amount_vnd": 18_500_000,
    "proposal_snapshot_hash": HASH,
    "work_snapshot_hash": HASH,
    "case_snapshot_hash": HASH,
    "report_snapshot_hash": HASH,
    "quotation_original_hash": HASH,
    "quotation_redacted_hash": HASH,
}


@dataclass
class FakeChainRecord:
    payload_hash: str
    previous_hash: str
    event_type: int
    signer: str
    recorded_at: int = 1


class FakeChainClient:
    def __init__(
        self,
        *,
        existing_hash=None,
        existing_record=None,
        submit_error=None,
        set_signer_error=None,
    ):
        self.submit_calls = 0
        self.find_calls = 0
        self.set_signer_calls = []
        self.submitted_event_ids = []
        self._records = {}
        self._submit_error = submit_error
        self._set_signer_error = set_signer_error
        self.last_receipt = None
        if existing_record is not None:
            self._seed = ("record", existing_record)
        elif existing_hash is not None:
            self._seed = ("hash", existing_hash)
        else:
            self._seed = None

    def _ensure_seed(self, event):
        if self._seed is None or event.event_id in self._records:
            return
        kind, value = self._seed
        if kind == "record":
            self._records[event.event_id] = value
        else:
            self._records[event.event_id] = FakeChainRecord(
                payload_hash="0x" + value if not str(value).startswith("0x") else value,
                previous_hash=event.previous_hash,
                event_type=event.event_type,
                signer=event.signer_wallet.address,
                recorded_at=1,
            )

    def find(self, event):
        self.find_calls += 1
        self._ensure_seed(event)
        return self._records.get(event.event_id)

    def submit(self, event) -> str:
        self.submit_calls += 1
        self.submitted_event_ids.append(event.event_id)
        if self._submit_error is not None:
            raise self._submit_error
        tx_hash = "0x" + f"{self.submit_calls:064x}"
        self._records[event.event_id] = FakeChainRecord(
            payload_hash="0x" + event.payload_hash,
            previous_hash=event.previous_hash,
            event_type=event.event_type,
            signer=event.signer_wallet.address,
            recorded_at=1,
        )
        self.last_receipt = {
            "transactionHash": tx_hash,
            "status": 1,
            "blockNumber": 10 + self.submit_calls,
            "blockHash": "0x" + "bb" * 32,
        }
        return tx_hash

    def set_signer(self, address, authorized) -> str:
        self.set_signer_calls.append((address, authorized))
        if self._set_signer_error is not None:
            raise self._set_signer_error
        return "0x" + "cc" * 32


class OutboxEventFactoryMixin:
    """Wallet + signed-event setup shared by worker test variants."""

    def make_membership(self, role=OrganizationMembership.Role.OPERATOR, suffix="worker"):
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

    def make_pending_outbox_event(self, suffix="pending", event_byte="11"):
        membership = self.make_membership(suffix=suffix)
        account, wallet = self.register(membership)
        event_id = "0x" + event_byte * 32
        payload = dict(PROPOSAL_PAYLOAD)
        signature = self.sign_event(account, event_id, EvidenceType.PROPOSAL_CREATED, payload)
        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                "0x" + "00" * 32,
                membership,
                signature,
            )
        return event

    def fake_chain_client(self, **kwargs):
        return FakeChainClient(**kwargs)


@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
)
class BlockchainWorkerTests(OutboxEventFactoryMixin, TestCase):
    def test_existing_matching_chain_event_confirms_without_resubmit(self):
        event = self.make_pending_outbox_event()
        client = self.fake_chain_client(existing_hash=event.payload_hash)

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(client.submit_calls, 0)
        self.assertGreaterEqual(client.find_calls, 1)
        self.assertIsNotNone(processed.confirmed_at)

    def test_missing_chain_event_submits_once_and_confirms(self):
        event = self.make_pending_outbox_event(suffix="submit", event_byte="22")
        client = self.fake_chain_client()

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(client.submit_calls, 1)
        self.assertEqual(processed.transaction_hash, "0x" + f"{1:064x}")
        self.assertEqual(processed.receipt_status, 1)

    def test_second_process_is_idempotent_and_does_not_resubmit(self):
        event = self.make_pending_outbox_event(suffix="idempotent", event_byte="33")
        client = self.fake_chain_client()

        first = process_outbox_event(event.id, client=client)
        second = process_outbox_event(event.id, client=client)

        self.assertEqual(first.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(second.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(client.submit_calls, 1)
        self.assertEqual(first.transaction_hash, second.transaction_hash)

    def test_chain_mismatch_marks_mismatch_without_submit(self):
        event = self.make_pending_outbox_event(suffix="mismatch", event_byte="44")
        client = self.fake_chain_client(
            existing_record=FakeChainRecord(
                payload_hash="0x" + "ff" * 32,
                previous_hash=event.previous_hash,
                event_type=event.event_type,
                signer=event.signer_wallet.address,
            )
        )

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.MISMATCH)
        self.assertEqual(client.submit_calls, 0)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="evidence.chain_mismatch",
                target_id=event.event_id,
                result="FAILURE",
            ).exists()
        )

    def test_submit_failure_returns_to_pending_with_backoff(self):
        event = self.make_pending_outbox_event(suffix="retry", event_byte="55")
        client = self.fake_chain_client(submit_error=TimeoutError("rpc timeout"))

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.PENDING)
        self.assertEqual(processed.attempts, 1)
        self.assertIsNotNone(processed.next_attempt_at)
        self.assertGreater(processed.next_attempt_at, timezone.now())
        self.assertIn("rpc timeout", processed.last_error)
        self.assertEqual(client.submit_calls, 1)

    def test_expired_lease_recovers_by_querying_chain(self):
        event = self.make_pending_outbox_event(suffix="lease", event_byte="66")
        BlockchainOutboxEvent.objects.filter(pk=event.pk).update(
            status=BlockchainOutboxEvent.Status.SUBMITTED,
            lease_expires_at=timezone.now() - timedelta(seconds=5),
            submitted_at=timezone.now() - timedelta(minutes=1),
        )
        client = self.fake_chain_client(existing_hash=event.payload_hash)

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(client.submit_calls, 0)

    def test_process_never_mutates_signed_identity_fields(self):
        event = self.make_pending_outbox_event(suffix="identity", event_byte="77")
        original = (
            event.event_id,
            event.event_type,
            event.payload_hash,
            event.previous_hash,
            event.signature,
            event.signer_wallet_id,
            event.payload,
        )
        client = self.fake_chain_client()

        processed = process_outbox_event(event.id, client=client)

        processed.refresh_from_db()
        self.assertEqual(
            (
                processed.event_id,
                processed.event_type,
                processed.payload_hash,
                processed.previous_hash,
                processed.signature,
                processed.signer_wallet_id,
                processed.payload,
            ),
            original,
        )

    def test_sync_signer_authorizations_confirms_pending_requests(self):
        membership = self.make_membership(suffix="auth-sync")
        _, wallet = self.register(membership)
        request = SignerAuthorizationRequest.objects.get(wallet=wallet)
        self.assertEqual(request.status, SignerAuthorizationRequest.Status.PENDING)
        client = self.fake_chain_client()

        results = sync_signer_authorizations(client=client)

        request.refresh_from_db()
        self.assertEqual(len(results), 1)
        self.assertEqual(request.status, SignerAuthorizationRequest.Status.CONFIRMED)
        self.assertEqual(request.transaction_hash, "0x" + "cc" * 32)
        self.assertEqual(client.set_signer_calls, [(wallet.address, True)])


@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
    EVIDENCE_ANCHORING_BACKEND="disabled",
)
class DisabledAnchoringWorkerTests(OutboxEventFactoryMixin, TestCase):
    """Disabled backend settles LOCAL, honestly and terminally (spec 5.2)."""

    def test_pending_event_settles_local_without_touching_chain(self):
        event = self.make_pending_outbox_event(suffix="local", event_byte="44")
        # Pre-seed receipt fields that must not survive honest LOCAL settlement.
        BlockchainOutboxEvent.objects.filter(pk=event.pk).update(
            transaction_hash="0x" + "ab" * 32,
            confirmed_at=timezone.now(),
        )
        client = self.fake_chain_client()

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.LOCAL)
        self.assertEqual(processed.transaction_hash, "")
        self.assertIsNone(processed.confirmed_at)
        self.assertIsNone(processed.submitted_at)
        self.assertIsNone(processed.lease_expires_at)
        self.assertEqual(client.find_calls, 0)
        self.assertEqual(client.submit_calls, 0)

    def test_local_is_terminal_and_never_retro_anchored(self):
        event = self.make_pending_outbox_event(suffix="terminal", event_byte="55")
        process_outbox_event(event.id, client=self.fake_chain_client())

        # Mode switch back to besu: settled events keep their status (spec 5.2).
        with override_settings(EVIDENCE_ANCHORING_BACKEND="besu"):
            client = self.fake_chain_client()
            again = process_outbox_event(event.id, client=client)

        self.assertEqual(again.status, BlockchainOutboxEvent.Status.LOCAL)
        self.assertEqual(client.find_calls, 0)
        self.assertEqual(client.submit_calls, 0)

    def test_batch_processing_constructs_no_chain_client(self):
        self.make_pending_outbox_event(suffix="batch", event_byte="66")

        # client=None must not call default_client() in disabled mode.
        results = process_due_outbox_events()

        self.assertEqual(
            [event.status for event in results],
            [BlockchainOutboxEvent.Status.LOCAL],
        )

    def test_confirmed_event_keeps_chain_record_in_disabled_mode(self):
        event = self.make_pending_outbox_event(suffix="keepconf", event_byte="77")
        with override_settings(EVIDENCE_ANCHORING_BACKEND="besu"):
            confirmed = process_outbox_event(event.id, client=self.fake_chain_client())
        self.assertEqual(confirmed.status, BlockchainOutboxEvent.Status.CONFIRMED)

        client = self.fake_chain_client()
        again = process_outbox_event(event.id, client=client)

        self.assertEqual(again.status, BlockchainOutboxEvent.Status.CONFIRMED)
        # Disabled mode skips the chain re-check entirely.
        self.assertEqual(client.find_calls, 0)
