from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from lamto.accounts.models import (
    Building,
    ManagementMembership,
    ResidentOccupancy,
    Unit,
)
from lamto.maintenance.models import (
    BuildingLocation,
    CaseReport,
    CompletionRating,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    TriageJob,
    WorkOrder,
)
from lamto.maintenance.ratings import rate_completed_work


class CompletionRatingTests(TestCase):
    def _unique(self, base):
        n = getattr(self, "_fixture_seq", 0) + 1
        self._fixture_seq = n
        return f"{base}-{n}"

    def make_context(self, *, work_status=WorkOrder.Status.ACCEPTED, own_report=True):
        tag = self._unique("rate")
        building = Building.objects.create(name=f"Rating Building {tag}")
        location = BuildingLocation.objects.create(building=building, name="Lobby")
        unit = Unit.objects.create(building=building, label="A-1")
        resident = get_user_model().objects.create_user(
            email=f"resident-{tag}@example.test",
            password="secret",
            display_name="Resident",
        )
        ResidentOccupancy.objects.create(user=resident, unit=unit)
        operator = get_user_model().objects.create_user(
            email=f"operator-{tag}@example.test",
            password="secret",
            display_name="Operator",
        )
        ManagementMembership.objects.create(user=operator, building=building)
        reporter = resident if own_report else get_user_model().objects.create_user(
            email=f"other-{tag}@example.test",
            password="secret",
            display_name="Other",
        )
        if not own_report:
            ResidentOccupancy.objects.create(
                user=reporter,
                unit=Unit.objects.create(building=building, label="B-1"),
            )
        report = IssueReport.objects.create(
            reporter=reporter,
            unit=unit if own_report else Unit.objects.get(building=building, label="B-1"),
            text="Elevator shakes",
            selected_location=location,
            location_path_snapshot="Lobby",
        )
        TriageJob.objects.create(report=report)
        decision = TriageDecision.objects.create(
            report=report,
            operator=operator,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_minutes=120,
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_at=timezone.now(),
        )
        CaseReport.objects.create(case=case, report=report, grouped_by=operator)
        work_order = WorkOrder.objects.create(
            case=case,
            assignee=operator,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=False,
            authorization_status=WorkOrder.AuthorizationStatus.NOT_REQUIRED,
            status=work_status,
        )
        return resident, work_order, report

    def test_rate_completed_work_persists_unique_rating(self):
        resident, work_order, _report = self.make_context()

        rating = rate_completed_work(resident, work_order, 5, "Solid repair")

        self.assertEqual(rating.score, 5)
        self.assertEqual(rating.comment, "Solid repair")
        self.assertEqual(rating.resident_id, resident.pk)
        self.assertEqual(rating.work_order_id, work_order.pk)
        self.assertEqual(CompletionRating.objects.count(), 1)

        with self.assertRaises(ValidationError):
            rate_completed_work(resident, work_order, 4, "Again")

    def test_rate_rejects_ineligible_status_or_non_owner(self):
        resident, open_work, _report = self.make_context(
            work_status=WorkOrder.Status.IN_PROGRESS
        )
        with self.assertRaises(ValidationError):
            rate_completed_work(resident, open_work, 3, "")

        non_owner, closed_work, _ = self.make_context(
            work_status=WorkOrder.Status.CLOSED, own_report=False
        )
        with self.assertRaises(PermissionDenied):
            rate_completed_work(non_owner, closed_work, 3, "Not mine")

    def test_score_must_be_one_to_five(self):
        resident, work_order, _report = self.make_context()
        with self.assertRaises(ValidationError):
            rate_completed_work(resident, work_order, 0, "")
        with self.assertRaises(ValidationError):
            rate_completed_work(resident, work_order, 6, "")

    def test_unique_constraint_at_database(self):
        resident, work_order, _report = self.make_context()
        rate_completed_work(resident, work_order, 4, "ok")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CompletionRating.objects.create(
                resident=resident,
                work_order=work_order,
                score=2,
                comment="",
            )
