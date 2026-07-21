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
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import Proposal, ProposalVersion
from lamto.finance.proposals import ZERO_HASH, build_proposal_evidence_payload
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import WorkOrder
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
        driver.login(None, "resident").submit_report("Lift jerks", "Lift 2")
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        self.work = self.seed.work_order
        self.operator = self.seed.roles["operator"]
        self.account = self.seed.accounts[self.operator.pk]

    def _login_operator(self):
        self.client.force_login(self.operator.user)
        device = TOTPDevice.objects.create(
            user=self.operator.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = self.operator.pk
        session.save()

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_prepare_then_sign_submits_version(self):
        self._login_operator()
        url = reverse("web:proposal-create", kwargs={"pk": self.work.pk})

        prepare = self.client.post(
            url,
            {
                "action": "prepare",
                "amount_vnd": 5_000_000,
                "contractor_name": "Acme Co",
                "quotation_original": _pdf("q.pdf", b"orig"),
                "quotation_redacted": _pdf("qr.pdf", b"redacted differs"),
            },
        )
        self.assertEqual(prepare.status_code, 200)
        self.assertContains(prepare, "data-signed-form")
        proposal = Proposal.objects.get(work_order=self.work)
        self.assertIsNone(proposal.current_version_id)
        original = DocumentVersion.objects.get(
            document__building=self.seed.building,
            document__kind=Document.Kind.QUOTATION,
            variant=DocumentVersion.Variant.ORIGINAL,
        )

        payload = build_proposal_evidence_payload(proposal, 5_000_000, "Acme Co", [original])
        event_id = "0x" + "11" * 32
        typed = build_evidence_typed_data(
            event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), ZERO_HASH
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.account.key
        ).signature.hex()

        submit = self.client.post(
            url,
            {
                "action": "submit",
                "amount_vnd": 5_000_000,
                "contractor_name": "Acme Co",
                "quotation_original_id": original.pk,
                "proposal_id": proposal.pk,
                "event_id": event_id,
                "signature": signature,
            },
        )
        self.assertRedirects(submit, reverse("web:proposal-detail", kwargs={"pk": proposal.pk}))
        version = ProposalVersion.objects.get(proposal=proposal)
        self.assertEqual(version.amount_vnd, 5_000_000)
        self.work.refresh_from_db()
        self.assertEqual(self.work.authorization_status, WorkOrder.AuthorizationStatus.AUTHORIZED)

    def test_non_operator_forbidden(self):
        self.client.force_login(self.seed.roles["maintenance"].user)
        device = TOTPDevice.objects.create(
            user=self.seed.roles["maintenance"].user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        resp = self.client.get(reverse("web:proposal-create", kwargs={"pk": self.work.pk}))
        self.assertEqual(resp.status_code, 403)
