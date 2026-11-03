"""The committed demo kit goes through the Management workspace as a visitor files it.

The kit lives in ops/demo-kit/files/ and is made by ops/demo-kit/generator/generate.py.
These tests upload the committed bytes, so a kit file the upload checks (PDF
signature, size limit) would refuse fails here rather than at the venue.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from lamto.finance.models import Proposal, Settlement
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
from lamto.web.staff_documents import new_event_id

KIT_DIR = settings.BASE_DIR.parent.parent / "ops" / "demo-kit"
QUOTATION = KIT_DIR / "files" / "bao-gia-sua-thang-may-mau.pdf"
TRANSFER_PROOF = KIT_DIR / "files" / "chung-tu-thanh-toan-mau.pdf"

_TEMP = tempfile.mkdtemp(prefix="lamto-demokit-")


@functools.cache
def _kit():
    """The generator's single definition of the kit's names and amounts."""
    spec = importlib.util.spec_from_file_location(
        "demo_kit_generator", KIT_DIR / "generator" / "generate.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.KIT


def _upload(path: Path) -> SimpleUploadedFile:
    return SimpleUploadedFile(path.name, path.read_bytes(), content_type="application/pdf")


@override_settings(
    LANGUAGE_CODE="en",
    ROOT_URLCONF="lamto.config.urls",
    # The AI provider is unset, as in the demo environment.
    AI_TRIAGE_URL="",
    AI_TRIAGE_TOKEN="",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
@patch("lamto.web.staff_documents.scan_with_clamav", lambda _f: True)
class DemoKitThroughTheWorkspaceTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(
            building_name="Demo Kit B", email_prefix="dk", create_sample_report=False
        )
        self.driver = PilotDomainDriver(self.seed)
        self.driver.submit_report("Thang máy rung lắc mạnh khi chạy", "Demo Kit B / Tầng 1 / Thang máy A")
        self.case = self.driver.confirm_triage_case()
        membership = self.seed.management_memberships[0]
        self.client.force_login(membership.user)
        session = self.client.session
        session["active_management_id"] = membership.pk
        session.save()

    def _create_proposal_from_kit(self):
        return self.client.post(
            reverse("web:proposal-create", kwargs={"pk": self.case.pk}),
            {
                "action": "prepare",
                "amount_vnd": _kit().amount_vnd,
                "contractor_name": _kit().contractor_name,
                "purpose": "Thang máy rung lắc mạnh khi chạy",
                "proposed_action": "Thay ray dẫn hướng và cáp tải, cân chỉnh máy kéo",
                "expected_schedule": "Trong 10 ngày làm việc",
                "quotation": _upload(QUOTATION),
                "confirm": "on",
            },
        )

    def _download(self, version_pk: int) -> bytes:
        response = self.client.get(
            reverse("web:staff-document", kwargs={"version_id": version_pk}), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        return response.content

    def test_the_kit_is_for_560_million_vnd(self):
        self.assertEqual(_kit().amount_vnd, 560_000_000)
        self.assertEqual(_kit().contractor_name, "Công ty TNHH Thang máy Mẫu")

    def test_the_kit_quotation_is_accepted_when_creating_a_proposal_from_a_case(self):
        response = self._create_proposal_from_kit()

        proposal = Proposal.objects.get(case=self.case)
        detail_url = reverse("web:proposal-detail", kwargs={"pk": proposal.pk})
        self.assertRedirects(response, detail_url, fetch_redirect_response=False)
        detail = self.client.get(detail_url)
        self.assertContains(detail, "Công ty TNHH Thang máy Mẫu")
        self.assertContains(detail, "560,000,000")
        quotation = proposal.current_version.quotations.get()
        self.assertEqual(self._download(quotation.pk), QUOTATION.read_bytes())

    def test_the_kit_transfer_proof_is_accepted_when_settling(self):
        self._create_proposal_from_kit()
        proposal = Proposal.objects.get(case=self.case)
        self.client.post(
            reverse("web:proposal-detail", kwargs={"pk": proposal.pk}),
            {"action": "decide", "decision": "proceed", "note": "Tiến hành"},
        )
        self.driver.complete_assigned_work()

        response = self.client.post(
            reverse("web:settlement-record", kwargs={"pk": proposal.pk}),
            {"event_id": new_event_id(), "proof_upload": _upload(TRANSFER_PROOF)},
        )

        settlement = Settlement.objects.get(proposal=proposal)
        self.assertRedirects(
            response,
            reverse("web:settlement-detail", kwargs={"pk": settlement.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self._download(settlement.transfer.pk), TRANSFER_PROOF.read_bytes())

    def test_price_comparison_at_the_kit_amount_falls_back_about_24_percent_above(self):
        response = self.client.post(
            reverse("web:proposal-price-compare", kwargs={"pk": self.case.pk}),
            data=json.dumps({"amount_vnd": _kit().amount_vnd}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_fallback"])
        self.assertEqual(data["formatted"]["reasoning"], "Dự đoán AI không khả dụng — dùng giá tham chiếu mẫu.")
        self.assertEqual(data["direction"], "above")
        self.assertEqual(data["percentage"], 24)
        self.assertIn("24% above the reference price", data["formatted"]["comparison_text"])
