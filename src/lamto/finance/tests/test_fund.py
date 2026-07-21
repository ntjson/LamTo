from django.core.exceptions import PermissionDenied
from django.test import TestCase

from lamto.documents.models import Document
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.fund import fund_balance, get_or_create_fund, record_fund_source, verify_fund_source
from lamto.finance.models import MaintenanceFundEntry
from lamto.testing.factories import seed_pilot_world


class OffchainFundTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name=f"Fund {self._testMethodName}", create_sample_report=False)
        self.recorder, self.verifier = self.seed.management_memberships[:2]
        self.original, self.redacted = self.seed.document_pair(Document.Kind.CONTRACT, self.recorder.user, "fund")
        self.fund = get_or_create_fund(self.seed.building)

    def test_record_and_verify_are_offchain_and_dual_controlled(self):
        before = BlockchainOutboxEvent.objects.count()
        balance_before = fund_balance(self.seed.building.pk)
        entry = record_fund_source(self.fund, MaintenanceFundEntry.EntryType.INFLOW, 50_000_000, self.original, self.redacted, self.recorder)
        with self.assertRaises(PermissionDenied):
            verify_fund_source(entry, self.recorder)
        verification = verify_fund_source(entry, self.verifier)
        self.assertEqual(verification.membership, self.verifier)
        self.assertEqual(BlockchainOutboxEvent.objects.count(), before)
        self.assertEqual(fund_balance(self.seed.building.pk), balance_before + 50_000_000)
