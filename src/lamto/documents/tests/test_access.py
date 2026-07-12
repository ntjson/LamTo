import hashlib
import io
import tempfile
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

    def test_operator_without_persisted_workflow_is_denied_and_audited(self):
        operator, membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        payload = b"%PDF-1.7\\nprivate"
        version = create_document_version(
            Document.objects.create(building=membership.organization.building, kind=Document.Kind.QUOTATION),
            SimpleUploadedFile("quote.pdf", payload, content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )

        with self.assertRaises(PermissionDenied):
            authorize_download(operator, membership.id, version)
        self.assertEqual(AuditEvent.objects.last().result, "denied")

    def test_invalid_staff_membership_denial_uses_own_membership_for_audit(self):
        operator, membership = self.make_membership(OrganizationMembership.Role.OPERATOR)
        _, other_membership = self.make_membership(
            OrganizationMembership.Role.AUDITOR, membership.organization.building
        )
        version = create_document_version(
            Document.objects.create(
                building=membership.organization.building, kind=Document.Kind.QUOTATION
            ),
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )

        with self.assertRaises(PermissionDenied):
            authorize_download(operator, other_membership.id, version)

        audit = AuditEvent.objects.filter(action="document.download").last()
        self.assertEqual(audit.result, "denied")
        self.assertEqual(audit.membership_id, membership.id)

    def test_unaffiliated_denial_with_occupancy_in_another_building_is_audited(self):
        document_building = Building.objects.create(name="Document Building")
        occupancy_building = Building.objects.create(name="Occupancy Building")
        operator, _ = self.make_membership(OrganizationMembership.Role.OPERATOR, document_building)
        resident = get_user_model().objects.create_user(
            email="unaffiliated@example.test", password="secret", display_name="Resident"
        )
        occupancy = ResidentOccupancy.objects.create(
            user=resident,
            unit=Unit.objects.create(building=occupancy_building, label="A-1"),
        )
        version = create_document_version(
            Document.objects.create(building=document_building, kind=Document.Kind.QUOTATION),
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            DocumentVersion.Variant.ORIGINAL,
            operator,
            scanner=lambda _: True,
        )

        with self.assertRaises(PermissionDenied):
            authorize_download(resident, None, version)

        audit = AuditEvent.objects.filter(action="document.download").last()
        self.assertEqual(audit.result, "denied")
        self.assertIsNone(audit.membership_id)
        self.assertEqual(audit.metadata["occupancy_id"], occupancy.id)

    def test_cross_building_denial_and_hash_mismatch_are_audited(self):
        auditor, membership = self.make_membership(OrganizationMembership.Role.AUDITOR)
        operator, operator_membership = self.make_membership(
            OrganizationMembership.Role.OPERATOR, membership.organization.building
        )
        other_user, other_membership = self.make_membership(OrganizationMembership.Role.AUDITOR)
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
            authorize_download(auditor, membership.id, version)

        self.assertEqual(AuditEvent.objects.filter(action="document.download").count(), 2)
        self.assertEqual(AuditEvent.objects.last().result, "integrity_mismatch")

    @patch("lamto.documents.access.storages")
    def test_download_reads_the_exact_provider_version(self, private_storages):
        operator, membership = self.make_membership(OrganizationMembership.Role.AUDITOR)
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

    @patch("lamto.documents.access.storages")
    def test_s3_read_without_provider_version_id_fails_closed(self, private_storages):
        auditor, membership = self.make_membership(OrganizationMembership.Role.AUDITOR)
        payload = b"%PDF-1.7\\nprivate"
        version = DocumentVersion.objects.create(
            document=Document.objects.create(
                building=membership.organization.building, kind=Document.Kind.QUOTATION
            ),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key="documents/missing-version-id",
            provider_version_id="",
            filename="quote.pdf",
            content_type="application/pdf",
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            uploader=auditor,
        )
        storage = MagicMock(bucket_name="private")
        private_storages.__getitem__.return_value = storage

        with self.assertRaises(DocumentIntegrityError):
            authorize_download(auditor, membership.id, version)
        storage.connection.meta.client.get_object.assert_not_called()

    def test_representative_without_persisted_review_is_denied(self):
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
        with self.assertRaises(PermissionDenied):
            authorize_download(representative, membership.id, version)

    def test_maintenance_without_persisted_assignment_is_denied(self):
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
        with self.assertRaises(PermissionDenied):
            authorize_download(maintenance, membership.id, version)

    def test_resident_without_persisted_publication_is_denied_with_occupancy_audit(self):
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
        with self.assertRaises(PermissionDenied):
            authorize_download(resident, None, redacted)
        audit = AuditEvent.objects.last()
        self.assertEqual(audit.result, "denied")
        self.assertIsNone(audit.membership_id)
        self.assertEqual(audit.metadata["occupancy_id"], ResidentOccupancy.objects.get(user=resident).id)
