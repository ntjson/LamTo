import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.maintenance.models import BuildingLocation, IssueReport, MaintenanceCase, TriageDecision
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
from lamto.web.forms.staff import ConfirmTriageForm


class ManagementWorkspaceTests(TestCase):
    def test_triage_department_is_labeled_management_queue(self):
        self.assertEqual(ConfirmTriageForm().fields["department"].label, "Management queue")

    def authenticate_management(self, membership):
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="test", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()

    def login_management(self):
        user = get_user_model().objects.create_user(
            email="manager@example.test", password="secret", display_name="Manager"
        )
        membership = ManagementMembership.objects.create(
            user=user, building=Building.objects.create(name="Tower")
        )
        self.authenticate_management(membership)
        return membership

    def test_management_can_open_every_navigation_area(self):
        membership = self.login_management()
        for name in (
            "staff-home",
            "action-inbox",
            "case-list",
            "proposal-list",
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
        inbox = self.client.get(reverse("web:action-inbox"))
        self.assertContains(inbox, f"Work assigned to Management at {membership.building.name}.")

    def test_resident_only_user_is_denied_management_routes(self):
        user = get_user_model().objects.create_user(
            email="resident@example.test", password="secret", display_name="Resident"
        )
        building = Building.objects.create(name="Resident Tower")
        ResidentOccupancy.objects.create(
            user=user,
            unit=Unit.objects.create(building=building, label="R-1"),
            active=True,
        )
        self.assertFalse(ManagementMembership.objects.filter(user=user).exists())
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

    def test_report_info_and_decline_actions(self):
        membership = self.login_management()
        location = BuildingLocation.objects.create(building=membership.building, name="Lobby")
        resident = get_user_model().objects.create_user(
            email="outcomes@example.test", password="secret", display_name="Resident"
        )
        unit = Unit.objects.create(building=membership.building, label="A-2")
        report = IssueReport.objects.create(
            reporter=resident, unit=unit, building=membership.building, text="Leak",
            selected_location=location, location_path_snapshot="Tower / Lobby",
            status=IssueReport.Status.IN_REVIEW,
        )
        url = reverse("web:staff-report-detail", kwargs={"pk": report.pk})
        self.client.post(url, {"action": "request_info", "message": "Which tap?"})
        report.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.NEEDS_INFO)
        report.info_requests.update(resolved_at=timezone.now())
        self.client.post(url, {"action": "decline", "reason": "Already repaired"})
        report.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.DECLINED)
        self.assertEqual(report.declined_reason, "Already repaired")

    def test_recorder_and_second_manager_can_reach_separate_payment_steps(self):
        seed = seed_pilot_world(
            building_name="Payment Tower",
            email_prefix="workspace-payment",
            create_opening_fund=False,
        )
        driver = PilotDomainDriver(seed)
        driver.confirm_triage_case()
        driver.submit_signed_proposal()
        driver.complete_assigned_work()
        payment = driver.accept_and_record_payment()
        acceptance = payment.acceptance
        recorder, verifier = seed.management_memberships

        self.authenticate_management(recorder)
        record_response = self.client.get(
            reverse("web:payment-record-detail", kwargs={"pk": acceptance.pk})
        )
        self.assertRedirects(
            record_response,
            reverse("web:payment-verify-detail", kwargs={"pk": payment.pk}),
            fetch_redirect_response=False,
        )

        self.client.logout()
        self.authenticate_management(verifier)
        verify_response = self.client.get(
            reverse("web:payment-verify-detail", kwargs={"pk": payment.pk})
        )
        self.assertEqual(verify_response.status_code, 200)
        self.assertEqual(verify_response.context["membership"], verifier)
        self.assertEqual(verify_response.context["payment"], payment)
        self.assertContains(verify_response, f"Payment #{payment.pk}")
        self.assertContains(verify_response, "Verify payment")
        self.assertContains(verify_response, f"Management · {verifier.building.name}")
        self.assertNotEqual(recorder, verifier)
