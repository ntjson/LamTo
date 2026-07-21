import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.models import Building, ManagementMembership, Unit
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.maintenance.models import BuildingLocation, IssueReport, MaintenanceCase, TriageDecision
from lamto.web.views import payments


class ManagementWorkspaceTests(TestCase):
    def login_management(self):
        user = get_user_model().objects.create_user(
            email="manager@example.test", password="secret", display_name="Manager"
        )
        membership = ManagementMembership.objects.create(
            user=user, building=Building.objects.create(name="Tower")
        )
        self.client.force_login(user)
        device = TOTPDevice.objects.create(
            user=user, name="test", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        return membership

    def test_management_can_open_every_navigation_area(self):
        self.login_management()
        for name in (
            "staff-home",
            "action-inbox",
            "case-list",
            "proposal-list",
            "work-order-list",
            "payment-list",
            "audit-export",
            "fund-home",
            "ops-health",
            "pilot-metrics",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(reverse(f"web:{name}"), follow=True).status_code,
                    200,
                )

    def test_resident_only_user_is_denied_management_routes(self):
        user = get_user_model().objects.create_user(
            email="resident@example.test", password="secret", display_name="Resident"
        )
        self.client.force_login(user)
        for path in ("/s/", "/s/cases/", "/s/payments/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_case_detail_renders(self):
        membership = self.login_management()
        location = BuildingLocation.objects.create(
            building=membership.building, name="Lobby", active=True
        )
        resident = get_user_model().objects.create_user(
            email="reporter@example.test", password="secret", display_name="Reporter"
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=Unit.objects.create(building=membership.building, label="A-1"),
            text="Elevator shakes",
            selected_location=location,
            location_path_snapshot="Tower / Lobby",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=membership.user,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_minutes=120,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=membership.building,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )

        response = self.client.get(reverse("web:case-detail", kwargs={"pk": case.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Case #{case.pk}")

    def test_payment_record_and_second_manager_verify_paths_are_distinct(self):
        record = resolve("/s/payments/record/17/")
        verify = resolve("/s/payments/verify/17/")

        self.assertIs(record.func, payments.payment_record_detail)
        self.assertIs(verify.func, payments.payment_verify_detail)
