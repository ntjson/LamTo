import hashlib
import io
import tempfile
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.documents.models import Document, DocumentVersion, QuarantinedUpload
from lamto.documents.services import (
    DocumentStorageError,
    _store,
    add_redacted_copy,
    create_document_version,
)


@override_settings(
    STORAGES={
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tempfile.gettempdir() + "/lamto-document-tests"},
        }
    }
)
class DocumentVersionTests(TestCase):
    def make_operator_and_building(self):
        uploader = get_user_model().objects.create_user(
            email="operator@example.test", password="secret", display_name="Operator"
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(
            building=building, name="Operator", kind=Organization.Kind.OPERATOR
        )
        OrganizationMembership.objects.create(
            user=uploader,
            organization=organization,
            role=OrganizationMembership.Role.OPERATOR,
        )
        return uploader, building

    def test_original_and_redacted_bytes_get_distinct_immutable_hashes(self):
        uploader, building = self.make_operator_and_building()
        document = Document.objects.create(building=building, kind=Document.Kind.QUOTATION)
        original_bytes = b"%PDF-1.7\\nprivate-original"
        redacted_bytes = b"%PDF-1.7\\nresident-copy"
        original = create_document_version(
            document,
            SimpleUploadedFile("quote.pdf", original_bytes, content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            uploader,
            scanner=lambda _: True,
        )
        redacted = add_redacted_copy(
            original,
            SimpleUploadedFile("quote-redacted.pdf", redacted_bytes, content_type="application/pdf"),
            uploader,
            scanner=lambda _: True,
        )

        self.assertEqual(original.sha256, hashlib.sha256(original_bytes).hexdigest())
        self.assertNotEqual(original.sha256, redacted.sha256)
        self.assertEqual(redacted.redacts_id, original.id)
        self.assertNotEqual(original.storage_key, redacted.storage_key)
        self.assertEqual(original.provider_version_id, original.storage_key)
        original.sha256 = "0" * 64
        with self.assertRaises(ValueError):
            original.save()

    def test_redacted_copy_rejects_identical_bytes_before_persistence(self):
        uploader, building = self.make_operator_and_building()
        document = Document.objects.create(building=building, kind=Document.Kind.QUOTATION)
        payload = b"%PDF-1.7\\nprivate-original"
        original = create_document_version(
            document,
            SimpleUploadedFile("quote.pdf", payload, content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            uploader,
            scanner=lambda _: True,
        )

        with self.assertRaisesRegex(ValueError, "must differ"):
            add_redacted_copy(
                original,
                SimpleUploadedFile("quote-redacted.pdf", payload, content_type="application/pdf"),
                uploader,
                scanner=lambda _: True,
            )

        self.assertEqual(DocumentVersion.objects.count(), 1)

    def test_database_trigger_rejects_version_update_and_delete(self):
        uploader, building = self.make_operator_and_building()
        version = create_document_version(
            Document.objects.create(building=building, kind=Document.Kind.QUOTATION),
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            uploader,
            scanner=lambda _: True,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentVersion.objects.filter(pk=version.pk).update(filename="changed.pdf")
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM documents_documentversion WHERE id = %s", [version.pk])

        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.filter(pk=version.document_id).update(kind=Document.Kind.INVOICE)

    def test_database_trigger_rejects_quarantine_mutation(self):
        uploader, _ = self.make_operator_and_building()
        quarantined = QuarantinedUpload.objects.create(
            uploader=uploader,
            filename="rejected.pdf",
            content_type="application/pdf",
            byte_size=1,
            sha256="",
            reason="unsupported content type",
            retention_expires_at=timezone.now(),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            QuarantinedUpload.objects.filter(pk=quarantined.pk).update(reason="changed")


class StorageVersionTests(TestCase):
    def test_s3_write_without_version_id_fails_closed(self):
        storage = MagicMock(bucket_name="private")
        storage.connection.meta.client.put_object.return_value = {}

        with self.assertRaisesRegex(DocumentStorageError, "VersionId"):
            _store(storage, "documents/immutable-key", io.BytesIO(b"payload"), "application/pdf")
