"""A report's ledger_entry_ids must only name entries GET /ledger/{id} serves.

Publication does not wait for evidence: a settlement entry can be published
while its outbox events are still PENDING, but the resident ledger only serves
entries whose evidence has settled. The report must not link to the gap, or the
app opens a spending page that 404s.
"""

import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.finance.models import PublishedLedgerEntry
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-api-report-ledger-")


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
class ReportLedgerLinkTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(
            building_name="Report Ledger Links",
            email_prefix="rll",
            create_sample_report=False,
        )
        self.seed.chain_paused = True
        self.driver = PilotDomainDriver(self.seed)
        self.report = self.driver.submit_report("Lobby lamp flickers", "Lift 2")
        self.driver.confirm_triage_case()
        self.driver.publish_proposal()
        self.driver.complete_assigned_work()
        self.driver.record_settlement()
        # Published while the evidence is still pending, as in the pilot.
        self.entry = self.driver.publish_settlement_entry()

    def _auth(self):
        _instance, token = AuthToken.objects.create(user=self.seed.residents[0])
        return {"authorization": f"Token {token}"}

    def _report_ledger_ids(self):
        response = self.client.get(
            reverse("api:report-detail", kwargs={"pk": self.report.pk}),
            headers=self._auth(),
        )
        assert response.status_code == 200, response.content
        return response.json()["ledger_entry_ids"]

    def _ledger_status(self, pk):
        return self.client.get(
            reverse("api:ledger-detail", kwargs={"pk": pk}), headers=self._auth()
        ).status_code

    def test_report_omits_entry_whose_evidence_is_pending(self):
        assert PublishedLedgerEntry.objects.filter(pk=self.entry.pk).exists()
        ids = self._report_ledger_ids()
        assert {pk: self._ledger_status(pk) for pk in ids} == {
            pk: 200 for pk in ids
        }
        assert ids == []

    def test_report_links_entry_once_evidence_settles(self):
        self.driver.confirm_all_chain_events()
        ids = self._report_ledger_ids()
        assert ids == [self.entry.pk]
        assert self._ledger_status(self.entry.pk) == 200
