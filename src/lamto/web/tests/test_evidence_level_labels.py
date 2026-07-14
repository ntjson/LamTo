"""LOCAL_SIGNED never borrows CHAIN_CONFIRMED presentation (spec 5.1/5.2)."""

import tempfile

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.approvals import (
    ANCHORED_LABEL,
    LOCAL_SIGNED_LABEL,
    PENDING_ANCHORING_LABEL,
    proposal_verification_label,
)
from lamto.finance.models import PublishedLedgerEntry
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
from lamto.web.views.exports import _outbox_rows
from lamto.web.views.health import collect_health_snapshot

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-evidence-labels-")


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
class EvidenceLevelLabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="Label Building", create_sample_report=False
        )
        driver = PilotDomainDriver(cls.seed)
        driver.prepare_locally_approved_normal_work(None)
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()
        driver.sign_publication_snapshot()
        driver.confirm_all_chain_events()
        cls.entry = PublishedLedgerEntry.objects.get(case__building=cls.seed.building)

    def _proposal_event_ids(self):
        version = self.entry.proposal.current_version
        ids = [version.outbox_event_id]
        ids.extend(
            BlockchainOutboxEvent.objects.filter(
                approval_decision__version=version
            ).values_list("pk", flat=True)
        )
        return ids

    def test_staff_label_is_three_way(self):
        version = self.entry.proposal.current_version
        self.assertEqual(proposal_verification_label(version), ANCHORED_LABEL)

        BlockchainOutboxEvent.objects.filter(pk__in=self._proposal_event_ids()).update(
            status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None
        )
        self.assertEqual(proposal_verification_label(version), LOCAL_SIGNED_LABEL)

        BlockchainOutboxEvent.objects.filter(pk=version.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.PENDING
        )
        self.assertEqual(proposal_verification_label(version), PENDING_ANCHORING_LABEL)

    def test_resident_detail_shows_offchain_label_for_local(self):
        BlockchainOutboxEvent.objects.filter(
            pk=self.entry.snapshot.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None)
        client = Client()
        client.force_login(self.seed.users["resident"])

        response = client.get(
            reverse("web:ledger-detail", kwargs={"pk": self.entry.pk})
        )

        self.assertContains(response, "anchoring is off for this deployment")
        self.assertNotContains(response, "Blockchain anchored")

    def test_resident_detail_shows_anchored_for_confirmed(self):
        client = Client()
        client.force_login(self.seed.users["resident"])

        response = client.get(
            reverse("web:ledger-detail", kwargs={"pk": self.entry.pk})
        )

        self.assertContains(response, "Blockchain anchored")
        self.assertNotContains(response, "anchoring is off for this deployment")

    def test_outbox_export_carries_evidence_level_verbatim(self):
        BlockchainOutboxEvent.objects.filter(
            pk=self.entry.snapshot.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None)

        header, rows = _outbox_rows(self.seed.building.pk)

        self.assertIn("evidence_level", header)
        level_by_event = {
            row[header.index("event_id")]: row[header.index("evidence_level")]
            for row in rows
        }
        snapshot_event = self.entry.snapshot.outbox_event
        self.assertEqual(level_by_event[snapshot_event.event_id], "LOCAL_SIGNED")
        self.assertIn("CHAIN_CONFIRMED", set(level_by_event.values()))

    def test_health_snapshot_reports_anchoring_backend(self):
        self.assertEqual(collect_health_snapshot()["anchoring_backend"], "besu")
        with override_settings(EVIDENCE_ANCHORING_BACKEND="disabled"):
            self.assertEqual(
                collect_health_snapshot()["anchoring_backend"], "disabled"
            )
