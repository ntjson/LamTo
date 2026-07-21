from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from lamto.accounts.models import Building, ManagementMembership, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    TriageJob,
    WorkOrder,
    WorkUpdate,
    WorkUpdateEvidence,
)
from lamto.maintenance.triage import confirm_triage
from lamto.maintenance.workorders import complete_work_order, create_work_order, start_work_order


class WorkOrderTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Minh An Residence")
        self.location = BuildingLocation.objects.create(building=self.building, name="Lift 2")
        self.operator = get_user_model().objects.create_user(
            email="operator@example.test", password="secret", display_name="Operator"
        )
        ManagementMembership.objects.create(user=self.operator, building=self.building)
        self.assignee = get_user_model().objects.create_user(
            email="maintenance@example.test", password="secret", display_name="Maintenance"
        )
        ManagementMembership.objects.create(user=self.assignee, building=self.building)
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

    def evidence(self, kind, number, *, building=None, variant=None, scan_status=None, uploader=None):
        return DocumentVersion.objects.create(
            document=Document.objects.create(building=building or self.building, kind=kind),
            version=1,
            variant=variant or DocumentVersion.Variant.ORIGINAL,
            storage_key=f"evidence-{number}",
            provider_version_id=f"version-{number}",
            filename=f"evidence-{number}.jpg",
            content_type="image/jpeg",
            byte_size=1,
            sha256=f"{number:064d}",
            scan_status=scan_status or DocumentVersion.ScanStatus.CLEAN,
            uploader=uploader or self.assignee,
        )

    def started_work_order(self):
        return start_work_order(
            create_work_order(self.case, self.operator, self.assignee, requires_spending=False), self.assignee
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
        work_order = self.started_work_order()
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

    def test_work_order_database_check_rejects_paid_not_required_insert_and_update(self):
        fields = {
            "case": self.case,
            "assignee": self.assignee,
            "priority": self.case.urgency,
            "deadline_at": self.case.deadline_at,
            "requires_spending": True,
        }
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkOrder.objects.create(**fields)

        paid = create_work_order(self.case, self.operator, self.assignee, requires_spending=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkOrder.objects.filter(pk=paid.pk).update(
                authorization_status=WorkOrder.AuthorizationStatus.NOT_REQUIRED
            )

    def test_work_order_rejects_unaffiliated_or_cross_building_operator_and_assignee(self):
        unaffiliated = get_user_model().objects.create_user(
            email="unaffiliated@example.test", password="secret", display_name="Unaffiliated"
        )
        other_building = Building.objects.create(name="Other Residence")
        other_operator = get_user_model().objects.create_user(
            email="other-operator@example.test", password="secret", display_name="Other Operator"
        )
        ManagementMembership.objects.create(user=other_operator, building=other_building)
        other_assignee = get_user_model().objects.create_user(
            email="other-maintenance@example.test", password="secret", display_name="Other Maintenance"
        )
        ManagementMembership.objects.create(user=other_assignee, building=other_building)

        for operator in (unaffiliated, other_operator):
            with self.subTest(operator=operator.email), self.assertRaises(PermissionDenied):
                create_work_order(self.case, operator, self.assignee, requires_spending=False)
        with self.assertRaises(PermissionDenied):
            create_work_order(self.case, self.operator, other_assignee, requires_spending=False)

    def test_completion_rejects_invalid_evidence_kind_variant_scan_or_uploader(self):
        other_uploader = get_user_model().objects.create_user(
            email="other@example.test", password="secret", display_name="Other"
        )
        invalid_pairs = [
            (self.evidence(Document.Kind.REPORT_PHOTO, 10), self.evidence(Document.Kind.AFTER_PHOTO, 11)),
            (self.evidence(Document.Kind.BEFORE_PHOTO, 12), self.evidence(Document.Kind.REPORT_PHOTO, 13)),
            (
                self.evidence(Document.Kind.BEFORE_PHOTO, 14, variant=DocumentVersion.Variant.REDACTED),
                self.evidence(Document.Kind.AFTER_PHOTO, 15),
            ),
            (
                self.evidence(Document.Kind.BEFORE_PHOTO, 16),
                self.evidence(Document.Kind.AFTER_PHOTO, 17, variant=DocumentVersion.Variant.REDACTED),
            ),
            (self.evidence(Document.Kind.BEFORE_PHOTO, 18, scan_status="PENDING"), self.evidence(Document.Kind.AFTER_PHOTO, 19)),
            (self.evidence(Document.Kind.BEFORE_PHOTO, 20), self.evidence(Document.Kind.AFTER_PHOTO, 21, scan_status="PENDING")),
            (self.evidence(Document.Kind.BEFORE_PHOTO, 22, uploader=other_uploader), self.evidence(Document.Kind.AFTER_PHOTO, 23)),
            (self.evidence(Document.Kind.BEFORE_PHOTO, 24), self.evidence(Document.Kind.AFTER_PHOTO, 25, uploader=other_uploader)),
        ]

        for before, after in invalid_pairs:
            with self.subTest(before=before.pk, after=after.pk), self.assertRaises(ValidationError):
                complete_work_order(
                    self.started_work_order(),
                    self.assignee,
                    "Worn cable",
                    "Cable secured",
                    [before],
                    [after],
                )

    def test_database_rejects_work_update_and_evidence_mutation(self):
        completed = complete_work_order(
            self.started_work_order(),
            self.assignee,
            "Worn cable",
            "Cable secured",
            [self.evidence(Document.Kind.BEFORE_PHOTO, 30)],
            [self.evidence(Document.Kind.AFTER_PHOTO, 31)],
        )
        update = WorkUpdate.objects.get(work_order=completed)
        evidence = WorkUpdateEvidence.objects.filter(update=update).first()

        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkUpdate.objects.filter(pk=update.pk).update(result="Changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM maintenance_workupdateevidence WHERE id = %s", [evidence.pk])
