import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.documents.models import Document, DocumentVersion
from lamto.web.staff_signing import new_event_id, upload_document_pair

_TEMP = tempfile.mkdtemp(prefix="lamto-staffsign-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class UploadDocumentPairTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Signing Building")
        org = Organization.objects.create(
            building=self.building, name="Ops", kind=Organization.Kind.OPERATOR
        )
        self.user = get_user_model().objects.create_user(
            email="op@example.test", password="secret", display_name="Op"
        )
        OrganizationMembership.objects.create(
            user=self.user, organization=org, role=OrganizationMembership.Role.OPERATOR
        )

    def test_new_event_id_is_random_bytes32(self):
        a, b = new_event_id(), new_event_id()
        assert a.startswith("0x") and len(a) == 66 and a != b

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_uploads_linked_clean_pair(self):
        original, redacted = upload_document_pair(
            self.building,
            Document.Kind.QUOTATION,
            self.user,
            _pdf("q.pdf", b"original bytes"),
            _pdf("q-red.pdf", b"redacted bytes differ"),
        )
        assert original.variant == DocumentVersion.Variant.ORIGINAL
        assert original.redacts_id is None
        assert redacted.variant == DocumentVersion.Variant.REDACTED
        assert redacted.redacts_id == original.pk
        assert original.document_id == redacted.document_id
        assert original.scan_status == DocumentVersion.ScanStatus.CLEAN
        assert redacted.scan_status == DocumentVersion.ScanStatus.CLEAN
        assert original.sha256 != redacted.sha256

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_identical_bytes_rejected_as_validation_error(self):
        with self.assertRaises(ValidationError):
            upload_document_pair(
                self.building,
                Document.Kind.QUOTATION,
                self.user,
                _pdf("q.pdf", b"same"),
                _pdf("q.pdf", b"same"),
            )

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_redacted_failure_leaves_no_partial_pair(self):
        from unittest.mock import patch as _patch
        with _patch(
            "lamto.web.staff_signing.add_redacted_copy",
            side_effect=ValueError("redacted scan failed"),
        ):
            with self.assertRaises(ValidationError):
                upload_document_pair(
                    self.building,
                    Document.Kind.QUOTATION,
                    self.user,
                    _pdf("q.pdf", b"original bytes"),
                    _pdf("q-red.pdf", b"redacted bytes differ"),
                )
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)

    def test_cleanup_stale_prepared_ops_removes_old_orphans(self):
        from datetime import timedelta

        from django.db import connection
        from django.utils import timezone

        from lamto.web.staff_signing import cleanup_stale_prepared_ops

        with patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True):
            upload_document_pair(
                self.building,
                Document.Kind.QUOTATION,
                self.user,
                _pdf("old.pdf", b"old original"),
                _pdf("old-r.pdf", b"old redacted"),
            )
        # DocumentVersion is DB append-only (BEFORE UPDATE trigger). Age rows as
        # table owner by briefly disabling user triggers (same privilege cleanup uses).
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE documents_documentversion DISABLE TRIGGER USER")
        try:
            DocumentVersion.objects.all().update(
                created_at=timezone.now() - timedelta(hours=48)
            )
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE documents_documentversion ENABLE TRIGGER USER")
        result = cleanup_stale_prepared_ops(older_than_hours=24)
        self.assertGreaterEqual(result.get("documents_deleted", 0), 1)
        self.assertEqual(Document.objects.count(), 0)
