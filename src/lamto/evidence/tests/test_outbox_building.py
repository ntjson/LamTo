from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import Building, ManagementMembership
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_platform_event,
    queue_signed_event,
    register_wallet,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.testing.factories import new_event_id


ZERO_HASH = "0x" + "0" * 64
DEV_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def proposal_payload():
    return {
        "proposal_id": 1,
        "proposal_version": 1,
        "record_id": 1,
        "case_id": 1,
        "report_id": 1,
        "amount_vnd": 1_000_000,
        "proposal_snapshot_hash": "a" * 64,
        "case_snapshot_hash": "a" * 64,
        "report_snapshot_hash": "a" * 64,
        "quotation_original_hash": "a" * 64,
        "quotation_redacted_hash": "a" * 64,
    }


@override_settings(PLATFORM_SIGNER_PRIVATE_KEY=DEV_KEY)
class OutboxBuildingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Outbox Building A")
        cls.other = Building.objects.create(name="Outbox Building B")
        user = get_user_model().objects.create_user(
            email="outbox-signer@example.test", password="x", display_name="Signer"
        )
        cls.membership = ManagementMembership.objects.create(
            user=user, building=cls.building
        )
        cls.account = Account.create()
        challenge = begin_wallet_registration(cls.membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), cls.account.key
        ).signature.hex()
        register_wallet(cls.membership, cls.account.address, proof)

    def queue_signed_proposal(self):
        payload = proposal_payload()
        event_id = new_event_id()
        typed_data = build_evidence_typed_data(
            event_id,
            EvidenceType.PROPOSAL_CREATED,
            "0x" + payload_hash(payload),
            ZERO_HASH,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed_data), self.account.key
        ).signature.hex()
        with transaction.atomic():
            return queue_signed_event(
                event_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                ZERO_HASH,
                self.membership,
                signature,
            )

    def test_queued_events_carry_their_tenant_building(self):
        signed = self.queue_signed_proposal()
        platform = queue_platform_event(
            new_event_id(),
            EvidenceType.PROPOSAL_CREATED,
            proposal_payload(),
            ZERO_HASH,
            self.building,
        )

        self.assertEqual(signed.building_id, self.membership.building_id)
        self.assertEqual(platform.building_id, self.building.pk)

    def test_building_is_immutable_at_database_level(self):
        event = self.queue_signed_proposal()

        with self.assertRaises(IntegrityError), transaction.atomic():
            BlockchainOutboxEvent.objects.filter(pk=event.pk).update(
                building=self.other
            )
