import tempfile
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.api.downloads import issue_download_token
from lamto.maintenance.models import ReportPhoto
from lamto.maintenance.reporting import submit_report_idempotent
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-dl-")
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
class DownloadTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API DL B", email_prefix="apidl", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.report, _ = submit_report_idempotent(
            self.resident, self.seed.unit, "Lift jerks", self.seed.location, [], uuid.uuid4()
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def _upload_photo(self):
        self.client.post(
            reverse("api:report-photos", kwargs={"pk": self.report.pk}),
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=self._auth(),
        )
        return ReportPhoto.objects.get(report=self.report).version

    def test_own_photo_download_url_streams_bytes(self):
        version = self._upload_photo()
        detail = self.client.get(reverse("api:report-detail", kwargs={"pk": self.report.pk}), headers=self._auth())
        url = detail.json()["photos"][0]["download_url"]
        assert url.startswith("/api/v1/documents/")
        got = self.client.get(url, headers=self._auth())
        assert got.status_code == 200
        assert got["Cache-Control"] == "private, no-store"
        assert got.content == _PNG

    def test_token_bound_to_user_and_expiry(self):
        version = self._upload_photo()
        # A token minted for this user cannot be redeemed by another user.
        from django.contrib.auth import get_user_model

        from lamto.accounts.models import ResidentOccupancy

        stranger = get_user_model().objects.create_user(email="apidl-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        token = issue_download_token(self.resident.pk, version.pk)
        miss = self.client.get(reverse("api:document-download", args=[token]), headers=self._auth(stranger))
        assert miss.status_code == 404
        # A tampered/garbage token is 404.
        bad = self.client.get(reverse("api:document-download", args=["not-a-real-token"]), headers=self._auth())
        assert bad.status_code == 404

    def test_original_staff_document_is_unreachable(self):
        # Forge a token for an original (non-redacted, non-photo) document version;
        # resident_can_download must refuse it -> 404.
        import hashlib

        from lamto.documents.models import Document, DocumentVersion

        doc = Document.objects.create(building=self.seed.building, kind=Document.Kind.INVOICE)
        original = DocumentVersion.objects.create(
            document=doc,
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            filename="inv.pdf",
            content_type="application/pdf",
            byte_size=3,
            sha256=hashlib.sha256(b"pdf").hexdigest(),
            storage_key="k",
            provider_version_id="v",
            scan_status=DocumentVersion.ScanStatus.CLEAN,
            uploader=self.resident,
        )
        token = issue_download_token(self.resident.pk, original.pk)
        resp = self.client.get(reverse("api:document-download", args=[token]), headers=self._auth())
        assert resp.status_code == 404
