from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from lamto.accounts.capabilities import REPORT_TRIAGE, WORK_ASSIGN
from lamto.accounts.models import Building, Organization, OrganizationMembership, Unit
from lamto.accounts.services import grant_capability
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import BuildingLocation, IssueReport, TriageJob, WorkOrder, WorkUpdate
from lamto.maintenance.triage import confirm_triage
from lamto.maintenance.workorders import complete_work_order, create_work_order, start_work_order


class WorkOrderTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Minh An Residence")
        self.location = BuildingLocation.objects.create(building=self.building, name="Lift 2")
        self.operator = get_user_model().objects.create_user(
            email="operator@example.test", password="secret", display_name="Operator"
        )
        organization = Organization.objects.create(
            building=self.building, name="Operator", kind=Organization.Kind.OPERATOR
        )
        membership = OrganizationMembership.objects.create(
            user=self.operator,
            organization=organization,
            role=OrganizationMembership.Role.OPERATOR,
        )
        grant_capability(membership, REPORT_TRIAGE)
        grant_capability(membership, WORK_ASSIGN)
        self.assignee = get_user_model().objects.create_user(
            email="maintenance@example.test", password="secret", display_name="Maintenance"
        )
        OrganizationMembership.objects.create(
            user=self.assignee,
            organization=organization,
            role=OrganizationMembership.Role.MAINTENANCE,
        )
        report = IssueReport.objects.create(
            reporter=get_user_model().objects.create_user(
                email="resident@example.test", password="secret", display_name="Resident"
            ),
            unit=Unit.objects.create(building=self.building, label="A-1"),
            text="Elevator shakes",
            selected_location=self.location,
            location_path_snapshot="Minh An Residence / Lift 2",
        )
        TriageJob.objects.create(report=report)
        self.case = confirm_triage(
            report, self.operator, "Elevator", "HIGH", self.location, "Maintenance", 240
        )

    def evidence(self, kind, number):
        return DocumentVersion.objects.create(
            document=Document.objects.create(building=self.building, kind=kind),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key=f"evidence-{number}",
            provider_version_id=f"version-{number}",
            filename=f"evidence-{number}.jpg",
            content_type="image/jpeg",
            byte_size=1,
            sha256=str(number) * 64,
            uploader=self.assignee,
        )

    def test_paid_work_needs_authorization_but_diagnostic_work_can_start(self):
        paid = create_work_order(self.case, self.operator, self.assignee, requires_spending=True)
        self.assertEqual(paid.authorization_status, WorkOrder.AuthorizationStatus.PENDING)
        with self.assertRaises(PermissionDenied):
            start_work_order(paid, self.assignee)

        diagnostic = create_work_order(self.case, self.operator, self.assignee, requires_spending=False)
        started = start_work_order(diagnostic, self.assignee)
        self.assertEqual(started.authorization_status, WorkOrder.AuthorizationStatus.NOT_REQUIRED)
        self.assertEqual(started.status, WorkOrder.Status.IN_PROGRESS)
        self.assertIsNotNone(started.started_at)

    def test_completion_requires_valid_before_and_after_evidence_and_creates_immutable_update(self):
        work_order = start_work_order(
            create_work_order(self.case, self.operator, self.assignee, requires_spending=False), self.assignee
        )
        before = self.evidence(Document.Kind.BEFORE_PHOTO, 1)
        after = self.evidence(Document.Kind.AFTER_PHOTO, 2)

        with self.assertRaises(ValidationError):
            complete_work_order(work_order, self.assignee, " ", "Fixed", [before], [after])

        completed = complete_work_order(work_order, self.assignee, "Worn cable", "Cable secured", [before], [after])
        update = WorkUpdate.objects.get(work_order=completed)
        self.assertEqual(completed.status, WorkOrder.Status.AWAITING_ACCEPTANCE)
        self.assertEqual(set(update.evidence.values_list("id", flat=True)), {before.id, after.id})
        update.result = "Changed"
        with self.assertRaises(ValueError):
            update.save()
