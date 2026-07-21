import tempfile
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.finance.models import Proposal, ProposalVersion
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import IssueReport
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-propcreate-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ProposalCreateTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="Prop Create B", email_prefix="pc")
        driver = PilotDomainDriver(self.seed)
        driver.submit_report("Lift jerks", "Lift 2")
        driver.confirm_triage_case()
        self.work = self.seed.case
        self.operator = self.seed.management_memberships[0]

    def _login_operator(self):
        self.client.force_login(self.operator.user)
        device = TOTPDevice.objects.create(
            user=self.operator.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_management_id"] = self.operator.pk
        session.save()

    @patch("lamto.web.staff_documents.scan_with_clamav", lambda _f: True)
    def test_publish_submits_platform_signed_version(self):
        self._login_operator()
        url = reverse("web:proposal-create", kwargs={"pk": self.work.pk})

        prepare = self.client.post(
            url,
            {
                "action": "prepare",
                "amount_vnd": 5_000_000,
                "contractor_name": "Acme Co",
                "fund_code": "GENERAL",
                "purpose": "Elevator noise",
                "proposed_action": "Replace bearings",
                "expected_schedule": "August 2026",
                "quotation_original": _pdf("q.pdf", b"orig"),
                "quotation_redacted": _pdf("qr.pdf", b"redacted differs"),
            },
        )
        self.assertEqual(prepare.status_code, 302)
        proposal = Proposal.objects.get(case=self.work)
        version = ProposalVersion.objects.get(proposal=proposal)
        self.assertEqual(version.amount_vnd, 5_000_000)
        self.assertTrue(version.outbox_event.signer_address)
        self.work.refresh_from_db()

    @patch("lamto.web.staff_documents.scan_with_clamav", lambda _f: True)
    def test_case_backed_proceed_decision_starts_case_work(self):
        self._login_operator()
        self.client.post(reverse("web:proposal-create", kwargs={"pk": self.work.pk}), {
            "action": "prepare", "amount_vnd": 5_000_000, "contractor_name": "Acme Co",
            "fund_code": "GENERAL", "purpose": "Lift jerks",
            "proposed_action": "Replace bearings", "expected_schedule": "August 2026",
            "quotation_original": _pdf("q.pdf", b"orig"),
            "quotation_redacted": _pdf("qr.pdf", b"redacted differs"),
        })
        proposal = Proposal.objects.get(case=self.work)

        response = self.client.post(
            reverse("web:proposal-detail", kwargs={"pk": proposal.pk}),
            {"action": "decide", "proceed": "on", "note": "Proceed"},
        )

        self.assertRedirects(response, reverse("web:proposal-detail", kwargs={"pk": proposal.pk}))
        proposal.refresh_from_db()
        self.work.decision.report.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.IN_PROGRESS)
        self.assertEqual(self.work.decision.report.status, IssueReport.Status.IN_PROGRESS)

    def test_second_manager_can_open_proposal_create(self):
        manager = self.seed.management_memberships[1]
        self.client.force_login(manager.user)
        device = TOTPDevice.objects.create(
            user=manager.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        resp = self.client.get(reverse("web:proposal-create", kwargs={"pk": self.work.pk}))
        self.assertEqual(resp.status_code, 200)
