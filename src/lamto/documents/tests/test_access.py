import hashlib
import io
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import storages
from django.test import TestCase, override_settings
from PIL import Image

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    ResidentOccupancy,
    Unit,
)
from lamto.audit.models import AuditEvent
from lamto.documents.access import DocumentIntegrityError, authorize_download
from lamto.documents.models import Document, DocumentVersion
from lamto.documents.services import add_redacted_copy, create_document_version


def jpeg_bytes():
    data = io.BytesIO()
    Image.new("RGB", (1, 1)).save(data, format="JPEG")
    return data.getvalue()


@override_settings(
    STORAGES={
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tempfile.gettempdir() + "/lamto-document-tests"},
        }
    }
)
class DocumentAccessTests(TestCase):
    def make_membership(self, role, building=None):
        building = building or Building.objects.create(name="Minh An Residence")
        user = get_user_model().objects.create_user(
            email=f"{role.lower()}-{get_user_model().objects.count()}@example.test",
            password="secret",
            display_name=role,
        )
        organization = Organization.objects.create(
            building=building,
            name=role,
            kind=OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role],
        )
        return user, OrganizationMembership.objects.create(user=user, organization=organization, role=role)

    def test_operator_can_read_same_building_bytes_and_audit(self):
        operator, membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        payload = b"%PDF-1.7\\nprivate"
        version = create_document_version(
            Document.objects.create(building=membership.organization.building, kind=Document.Kind.QUOTATION),
            SimpleUploadedFile("quote.pdf", payload, content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )

        self.assertEqual(authorize_download(operator, membership.id, version), payload)
        self.assertEqual(AuditEvent.objects.last().result, "allowed")

    def test_cross_building_denial_and_hash_mismatch_are_audited(self):
        operator, membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        other_user, other_membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        version = create_document_version(
            Document.objects.create(building=membership.organization.building, kind=Document.Kind.QUOTATION),
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )

        with self.assertRaises(PermissionDenied):
            authorize_download(other_user, other_membership.id, version)
        with storages["private"].open(version.storage_key, "wb") as file_obj:
            file_obj.write(b"tampered")
        with self.assertRaises(DocumentIntegrityError):
            authorize_download(operator, membership.id, version)

        self.assertEqual(AuditEvent.objects.filter(action="document.download").count(), 2)
        self.assertEqual(AuditEvent.objects.last().result, "integrity_mismatch")

    @patch("lamto.documents.access.storages")
    def test_download_reads_the_exact_provider_version(self, private_storages):
        operator, membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        payload = b"%PDF-1.7\\nprivate"
        version = DocumentVersion.objects.create(
            document=Document.objects.create(
                building=membership.organization.building, kind=Document.Kind.QUOTATION
            ),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key="documents/immutable-key",
            provider_version_id="provider-version-42",
            filename="quote.pdf",
            content_type="application/pdf",
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            uploader=operator,
        )
        storage = MagicMock(bucket_name="private")
        storage.connection.meta.client.get_object.return_value = {"Body": io.BytesIO(payload)}
        private_storages.__getitem__.return_value = storage

        self.assertEqual(authorize_download(operator, membership.id, version), payload)
        storage.connection.meta.client.get_object.assert_called_once_with(
            Bucket="private", Key=version.storage_key, VersionId="provider-version-42"
        )

    def test_representative_can_read_original_attached_to_reviewed_proposal(self):
        operator, operator_membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        representative, membership = self.make_membership(
            OrganizationMembership.Role.RESIDENT_REP,
            operator_membership.organization.building,
        )
        document = Document.objects.create(
            building=membership.organization.building, kind=Document.Kind.QUOTATION
        )
        version = create_document_version(
            document,
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )
        version.proposal = SimpleNamespace(reviewer_membership_id=membership.id)

        self.assertEqual(authorize_download(representative, membership.id, version), b"%PDF-1.7\\nprivate")

    def test_maintenance_can_read_only_assigned_report_photos(self):
        operator, operator_membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        maintenance, membership = self.make_membership(
            OrganizationMembership.Role.MAINTENANCE,
            operator_membership.organization.building,
        )
        document = Document.objects.create(
            building=membership.organization.building, kind=Document.Kind.REPORT_PHOTO
        )
        version = create_document_version(
            document,
            SimpleUploadedFile(
                "photo.jpg", jpeg_bytes(), content_type="image/jpeg"
            ),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )
        version.work_order = SimpleNamespace(assignee_id=maintenance.id)
        self.assertEqual(authorize_download(maintenance, membership.id, version), jpeg_bytes())

        invoice = Document.objects.create(
            building=membership.organization.building, kind=Document.Kind.INVOICE
        )
        invoice_version = create_document_version(
            invoice,
            SimpleUploadedFile("invoice.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )
        invoice_version.work_order = SimpleNamespace(assignee_id=maintenance.id)
        with self.assertRaises(PermissionDenied):
            authorize_download(maintenance, membership.id, invoice_version)

    def test_resident_can_read_published_redacted_copy(self):
        building = Building.objects.create(name="Resident Building")
        operator, _ = self.make_membership(OrganizationMembership.Role.OPERATOR, building)
        resident = get_user_model().objects.create_user(
            email="resident@example.test", password="secret", display_name="Resident"
        )
        unit = Unit.objects.create(building=building, label="A-1")
        ResidentOccupancy.objects.create(user=resident, unit=unit)
        document = Document.objects.create(building=building, kind=Document.Kind.QUOTATION)
        original = create_document_version(
            document,
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )
        redacted = add_redacted_copy(
            original,
            SimpleUploadedFile("quote-redacted.pdf", b"%PDF-1.7\\npublic", content_type="application/pdf"),
            operator,
            scanner=lambda _: True,
        )
        redacted.published = True

        self.assertEqual(authorize_download(resident, None, redacted), b"%PDF-1.7\\npublic")
        audit = AuditEvent.objects.last()
        self.assertEqual(audit.result, "allowed")
        self.assertIsNone(audit.membership_id)
        self.assertEqual(audit.metadata["occupancy_id"], ResidentOccupancy.objects.get(user=resident).id)
