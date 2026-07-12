from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import BuildingLocation, IssueReport, TriageJob
from lamto.maintenance.reporting import submit_report


class ReportSubmissionTests(TestCase):
    def make_resident_unit_and_location(self):
        building = Building.objects.create(name="Minh An Residence")
        resident = get_user_model().objects.create_user(
            email="resident@example.test", password="secret", display_name="Resident"
        )
        unit = Unit.objects.create(building=building, label="A-1")
        ResidentOccupancy.objects.create(user=resident, unit=unit)
        location = BuildingLocation.objects.create(building=building, name="Lift 2")
        return resident, unit, location

    def test_submission_commits_report_and_pending_triage_job(self):
        resident, unit, location = self.make_resident_unit_and_location()

        report = submit_report(resident, unit, "Elevator shakes", location, [])

        self.assertEqual(IssueReport.objects.get(id=report.id).text, "Elevator shakes")
        self.assertEqual(TriageJob.objects.get(report=report).status, TriageJob.Status.PENDING)

    def test_location_parent_must_belong_to_its_building(self):
        first = Building.objects.create(name="First Building")
        second = Building.objects.create(name="Second Building")
        parent = BuildingLocation.objects.create(building=first, name="Basement")
        child = BuildingLocation(building=second, parent=parent, name="Lift 2")

        with self.assertRaises(ValidationError):
            child.full_clean()

    def test_submission_rejects_inactive_occupancy(self):
        resident, unit, location = self.make_resident_unit_and_location()
        ResidentOccupancy.objects.filter(user=resident, unit=unit).update(active=False)

        with self.assertRaisesMessage(PermissionDenied, "Active occupancy"):
            submit_report(resident, unit, "Elevator shakes", location, [])

    def test_submission_rejects_photo_from_another_building(self):
        resident, unit, location = self.make_resident_unit_and_location()
        other_building = Building.objects.create(name="Other Building")
        photo = DocumentVersion.objects.create(
            document=Document.objects.create(
                building=other_building, kind=Document.Kind.REPORT_PHOTO
            ),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key="report-photo-other-building",
            provider_version_id="version-1",
            filename="photo.jpg",
            content_type="image/jpeg",
            byte_size=1,
            sha256="0" * 64,
            uploader=resident,
        )

        with self.assertRaises(ValidationError):
            submit_report(resident, unit, "Elevator shakes", location, [photo])
