from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import (
    Building,
    ManagementMembership,
)
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    utc_rfc3339,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.testing.factories import new_event_id


def make_signing_membership(building, *, email):
    user = get_user_model().objects.create_user(
        email=email, password="x", display_name=email
    )
    membership = ManagementMembership.objects.create(user=user, building=building)
    account = Account.create()
    challenge = begin_wallet_registration(membership)
    proof = Account.sign_message(
        encode_typed_data(full_message=challenge), account.key
    ).signature.hex()
    register_wallet(membership, account.address, proof)
    return membership, account


def queue_event(membership, account):
    # Valid FUND_ENTRY schema (same shape as evidence/tests/test_outbox.py).
    payload = {
        "fund_entry_id": 1,
        "entry_type": "INFLOW",
        "amount_vnd": 1_000_000,
        "source_document_original_hash": "a" * 64,
        "source_document_redacted_hash": "a" * 64,
        "maker_membership_id": membership.pk,
        "checker_membership_id": membership.pk,
        "entry_timestamp": utc_rfc3339(timezone.now()),
    }
    event_id = new_event_id()
    digest = payload_hash(payload)
    typed = build_evidence_typed_data(
        event_id, EvidenceType.FUND_ENTRY, "0x" + digest, "0x" + "0" * 64
    )
    signature = Account.sign_message(
        encode_typed_data(full_message=typed), account.key
    ).signature.hex()
    with transaction.atomic():
        return queue_signed_event(
            event_id,
            EvidenceType.FUND_ENTRY,
            payload,
            "0x" + "0" * 64,
            membership,
            signature,
        )


class OutboxBuildingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Outbox Building A")
        cls.other = Building.objects.create(name="Outbox Building B")
        cls.membership, cls.account = make_signing_membership(
            cls.building, email="outbox-signer@example.test"
        )

    def test_queued_event_carries_signer_building(self):
        event = queue_event(self.membership, self.account)
        event.refresh_from_db()
        assert event.building_id == self.building.pk

    def test_building_is_immutable_at_database_level(self):
        event = queue_event(self.membership, self.account)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BlockchainOutboxEvent.objects.filter(pk=event.pk).update(
                    building=self.other
                )
