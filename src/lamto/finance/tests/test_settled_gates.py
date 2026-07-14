"""LOCAL-settled evidence passes every settlement gate (spec 5.2)."""

import tempfile

from django.test import TestCase, override_settings

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry
from lamto.finance.publication import finalize_publication
from lamto.finance.selectors import published_ledger_entries
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
from lamto.web.action_inbox import _pending_publication_items

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-settled-gates-")


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class SettledGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="Settled Gates Building", create_sample_report=False
        )
        driver = PilotDomainDriver(cls.seed)
        driver.pause_chain()  # suppress the driver's fake CONFIRMED updates
        driver.prepare_locally_approved_normal_work(None)
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        # Settle every pending flow event off-chain.
        BlockchainOutboxEvent.objects.filter(
            status=BlockchainOutboxEvent.Status.PENDING
        ).update(status=BlockchainOutboxEvent.Status.LOCAL)
        # Signing requires settled prerequisites; with LOCAL they must pass.
        cls.snapshot = driver.sign_publication_snapshot()
        BlockchainOutboxEvent.objects.filter(pk=cls.snapshot.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.LOCAL
        )

    def test_local_settled_snapshot_finalizes_and_posts_outflow(self):
        entry = finalize_publication(self.snapshot.pk)
        self.assertIsInstance(entry, PublishedLedgerEntry)
        outflow = MaintenanceFundEntry.objects.get(
            entry_type=MaintenanceFundEntry.EntryType.OUTFLOW,
            proposal=entry.proposal,
        )
        self.assertEqual(outflow.amount_vnd, -entry.actual_cost_vnd)

    def test_local_settled_entry_is_resident_visible(self):
        entry = finalize_publication(self.snapshot.pk)
        listed = published_ledger_entries(self.seed.building.pk)
        self.assertIn(entry.pk, [row.pk for row in listed])

    def test_pending_snapshot_still_blocks_finalization(self):
        BlockchainOutboxEvent.objects.filter(pk=self.snapshot.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.PENDING
        )
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            finalize_publication(self.snapshot.pk)

    def test_local_settled_snapshot_appears_in_finalize_inbox(self):
        items = _pending_publication_items(self.seed.building.pk)
        targets = [(item.target_type, item.target_id) for item in items]
        self.assertIn(("PublicationSnapshot", self.snapshot.pk), targets)
