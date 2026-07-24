import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, ManagementMembership
from lamto.documents.models import Document
from lamto.documents.services import create_document_version


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@override_settings(
    STORAGES={
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tempfile.gettempdir() + "/lamto-document-tests"},
        }
    }
)
class DocumentServiceTests(TestCase):
    def test_resident_bill_accepts_png(self):
        building = Building.objects.create(name="Tower A")
        manager = get_user_model().objects.create_user(email="m@x.test", password="pw")
        ManagementMembership.objects.create(user=manager, building=building)
        document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)

        version = create_document_version(
            document,
            SimpleUploadedFile("bill.png", _PNG, content_type="image/png"),
            manager,
            scanner=lambda _: True,
        )

        self.assertEqual(version.content_type, "image/png")
