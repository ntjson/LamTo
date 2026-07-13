from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from lamto.accounts.capabilities import REPORT_TRIAGE
from lamto.accounts.models import Building, Organization, OrganizationMembership, Unit
from lamto.accounts.services import grant_capability
from lamto.audit.models import AuditEvent
from lamto.maintenance.models import (
    BuildingLocation,
    CaseReport,
    IssueReport,
    MaintenanceCase,
    TriageJob,
    TriageSuggestion,
)
from lamto.maintenance.triage import confirm_triage, group_report


class CaseTests(TestCase):
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

    def make_report(self, number):
        resident = get_user_model().objects.create_user(
            email=f"resident-{number}@example.test", password="secret", display_name="Resident"
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=Unit.objects.create(building=self.building, label=f"A-{number}"),
            text="Elevator shakes",
            selected_location=self.location,
            location_path_snapshot="Minh An Residence / Lift 2",
        )
        job = TriageJob.objects.create(report=report)
        TriageSuggestion.objects.create(
            job=job,
            category="Elevator",
            interpreted_location="Lift 2",
            urgency="MEDIUM",
            confidence_percent=90,
            duplicate_report_ids=[],
            department="Maintenance",
            deadline_minutes=60,
            raw_response={},
            provider_request_id=f"request-{number}",
            elapsed_ms=1,
        )
        return report

    def test_confirmation_records_operator_difference_and_grouping_is_idempotent(self):
        first, second = self.make_report(1), self.make_report(2)

        case = confirm_triage(
            first,
            self.operator,
            category="Elevator",
            urgency="HIGH",
            location=self.location,
            department="Maintenance",
            deadline_minutes=240,
        )
        self.assertEqual(case.reports.get(), first)
        self.assertEqual(case.decision.differences["urgency"], {"suggested": "MEDIUM", "chosen": "HIGH"})
        self.assertEqual(case.decision.differences["deadline_minutes"], {"suggested": 60, "chosen": 240})
        self.assertEqual(confirm_triage(first, self.operator, "x", "LOW", self.location, "x", 1), case)

        link = group_report(case, second, self.operator)
        self.assertEqual(group_report(case, second, self.operator), link)
        self.assertEqual(set(case.reports.values_list("id", flat=True)), {first.id, second.id})
        self.assertEqual(CaseReport.objects.filter(case=case, report=second).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="case.group", result="accepted").count(), 1)

    def test_grouping_rejects_report_already_in_an_active_case(self):
        first, second, third = self.make_report(1), self.make_report(2), self.make_report(3)
        case = confirm_triage(first, self.operator, "Elevator", "HIGH", self.location, "Maintenance", 240)
        other_case = confirm_triage(third, self.operator, "Elevator", "HIGH", self.location, "Maintenance", 240)

        with self.assertRaisesMessage(ValidationError, "active case"):
            group_report(case, third, self.operator)

        self.assertEqual(other_case.reports.get(), third)
        self.assertEqual(MaintenanceCase.objects.count(), 2)
