import tempfile
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.maintenance.models import IssueReport, ReportPhoto
from lamto.maintenance.reporting import submit_report_idempotent
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-photos-")
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class ReportPhotoUploadTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Photos B", email_prefix="apip", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.report, _ = submit_report_idempotent(
            self.resident, self.seed.unit, "Lift jerks", self.seed.location, [], uuid.uuid4()
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def test_upload_attaches_photo_to_own_report(self):
        resp = self.client.post(
            reverse("api:report-photos", kwargs={"pk": self.report.pk}),
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=self._auth(),
        )
        assert resp.status_code == 201, resp.content
        assert ReportPhoto.objects.filter(report=self.report).count() == 1
        assert resp.json()["sha256"]

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def test_same_bytes_replay_returns_200_without_duplicate(self):
        """Amendment 10: lost-response retry with identical content is idempotent."""
        url = reverse("api:report-photos", kwargs={"pk": self.report.pk})
        auth = self._auth()
        first = self.client.post(
            url,
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=auth,
        )
        assert first.status_code == 201, first.content
        second = self.client.post(
            url,
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=auth,
        )
        assert second.status_code == 200, second.content
        assert ReportPhoto.objects.filter(report=self.report).count() == 1
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["sha256"] == first.json()["sha256"]

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def test_upload_to_foreign_report_is_404(self):
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apip-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        resp = self.client.post(
            reverse("api:report-photos", kwargs={"pk": self.report.pk}),
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=self._auth(stranger),
        )
        assert resp.status_code == 404
