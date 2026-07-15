import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    Unit,
)
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    WorkOrder,
)


@override_settings(ROOT_URLCONF="lamto.config.urls")
class ListPatternTests(TestCase):
    def _make_work(self, building, case, assignee, status):
        return WorkOrder.objects.create(
            case=case,
            assignee=assignee,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=status,
        )

    def test_work_list_renders_status_chip_and_filters(self):
        building = Building.objects.create(name="List B")
        location = BuildingLocation.objects.create(
            building=building, name="Lobby", active=True
        )
        org = Organization.objects.create(
            building=building, name="M", kind=Organization.Kind.OPERATOR
        )
        user = get_user_model().objects.create_user(
            email="m@example.test", password="secret", display_name="M"
        )
        OrganizationMembership.objects.create(
            user=user, organization=org, role=OrganizationMembership.Role.MAINTENANCE
        )
        unit = Unit.objects.create(building=building, label="A-1")
        resident = get_user_model().objects.create_user(
            email="r@example.test", password="secret", display_name="R"
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text="x",
            selected_location=location,
            location_path_snapshot="x",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=user,
            category="c",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_minutes=60,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="c",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        self._make_work(building, case, user, WorkOrder.Status.ASSIGNED)
        # Not a WorkOrder.Status member — only appears in list status chips, not filter bar.
        self._make_work(building, case, user, "COMPLETED")

        self.client.force_login(user)
        device = TOTPDevice.objects.create(
            user=user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()

        resp = self.client.get(reverse("web:work-order-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "status-chip")
        self.assertContains(resp, "filter-bar")

        filtered = self.client.get(reverse("web:work-order-list"), {"status": "ASSIGNED"})
        self.assertContains(filtered, "ASSIGNED")
        self.assertNotContains(filtered, "COMPLETED")
