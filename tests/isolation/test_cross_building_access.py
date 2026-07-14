"""Two-building adversarial isolation suite (spec 2.3 layer 4).

Building A actors request Building B objects by primary key: the answer must
always be 404 (cross-tenant), 403 (ownership), or 405 (method), never data.
List pages and exports rendered for Building A must not contain Building B
markers. Every <int:pk> route must be classified here or in EXEMPT.
"""

import tempfile
import time

from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.finance.models import (
    AcceptanceRecord,
    PaymentEvidence,
    Proposal,
    PublishedLedgerEntry,
)
from lamto.finance.models.emergencies import EmergencyAuthorization
from lamto.maintenance.models import IssueReport, MaintenanceCase, WorkOrder
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-isolation-")

B_BUILDING_NAME = "Isolation Building B"
B_LEAK_MARKER = "TEST-B-LEAK-MARKER"

# route name -> (attribute on cls.b with the B-side pk, seed-A role key, method)
STAFF_CASES = {
    "web:staff-report-detail": ("report_pk", "operator", "GET"),
    "web:case-detail": ("case_pk", "operator", "GET"),
    "web:proposal-detail": ("proposal_pk", "operator", "GET"),
    "web:work-order-detail": ("work_pk", "maintenance", "GET"),
    "web:payment-record-detail": ("acceptance_pk", "board_payment_recorder", "GET"),
    "web:payment-verify-detail": ("payment_pk", "board_payment_verifier", "GET"),
    "web:work-accept": ("work_pk", "board_approver", "POST"),
    "web:emergency-authorize": ("work_pk", "board_emergency_approver", "POST"),
    "web:emergency-decide": ("emergency_pk", "resident_representative", "POST"),
}

RESIDENT_CASES = {
    "web:report-detail": ("report_pk", "GET", 404),
    "web:ledger-detail": ("ledger_pk", "GET", 404),
    "web:work-rate": ("work_pk", "POST", 403),
}

EXEMPT = {
    # Device revocation is user-scoped (own MFA devices), not tenant-scoped.
    "web:mfa-revoke": "user-scoped MFA device",
    # Break-glass sessions are platform support records for tech admins;
    # tenancy does not apply and the view enforces tech-admin capability.
    "web:break-glass-revoke": "platform-scoped support session",
}

LIST_ROUTES = [
    "web:action-inbox",
    "web:case-list",
    "web:work-order-list",
    "web:proposal-list",
    "web:payment-list",
    "web:audit-search",
]


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class CrossBuildingAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed_a = seed_pilot_world(
            building_name="Isolation Building A",
            email_prefix="isoa",
            create_sample_report=True,
        )
        cls.seed_b = seed_pilot_world(
            building_name=B_BUILDING_NAME,
            email_prefix="isob",
            create_sample_report=False,
        )
        driver = PilotDomainDriver(cls.seed_b)
        driver.login(None, "resident").submit_report(
            f"{B_LEAK_MARKER} lift noise", "Lift 2"
        )
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        driver.login(None, "operator").submit_signed_proposal()
        driver.login(None, "board_approver").approve_proposal()
        driver.login(None, "resident_representative").coapprove_proposal()
        driver.login(None, "maintenance").complete_assigned_work()
        driver.login(None, "board_payment_recorder").accept_and_record_payment()
        driver.login(None, "board_payment_verifier").verify_payment()
        driver.confirm_all_chain_events()
        driver.login(None, "eligible_publisher").sign_publication_snapshot()
        driver.confirm_all_chain_events()

        b_building = cls.seed_b.building
        report = IssueReport.objects.get(unit__building=b_building)
        case = MaintenanceCase.objects.get(building=b_building)
        work = WorkOrder.objects.get(case=case)
        proposal = Proposal.objects.get(work_order=work)
        acceptance = AcceptanceRecord.objects.get(work_order=work)
        payment = PaymentEvidence.objects.get(acceptance=acceptance)
        ledger = PublishedLedgerEntry.objects.get(case=case)

        # Main paid path already authorized work; force a fresh unpaid work order
        # for the emergency drill (factory only recreates when work_order is None).
        cls.seed_b.work_order = None
        drill_driver = PilotDomainDriver(cls.seed_b)
        drill_driver.login(None, "board_emergency_approver").authorize_emergency_drill()
        emergency = (
            EmergencyAuthorization.objects.filter(
                work_order__case__building=b_building
            )
            .order_by("-pk")
            .first()
        )

        cls.b = {
            "report_pk": report.pk,
            "case_pk": case.pk,
            "work_pk": work.pk,
            "proposal_pk": proposal.pk,
            "acceptance_pk": acceptance.pk,
            "payment_pk": payment.pk,
            "ledger_pk": ledger.pk,
            "emergency_pk": emergency.pk,
        }

    def _staff_login(self, role_key):
        membership = self.seed_a.roles[role_key]
        user = membership.user
        self.client.force_login(user)
        device = TOTPDevice.objects.create(
            user=user, name="test", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()

    def test_every_pk_route_is_classified(self):
        from lamto.web import urls as web_urls

        pk_routes = {
            f"web:{pattern.name}"
            for pattern in web_urls.urlpatterns
            if "<int:" in str(pattern.pattern)
        }
        classified = set(STAFF_CASES) | set(RESIDENT_CASES) | set(EXEMPT)
        missing = pk_routes - classified
        assert not missing, (
            f"New pk routes must be classified in the isolation suite: {missing}"
        )

    def test_staff_cannot_reach_other_building_objects(self):
        for route, (pk_attr, role_key, method) in STAFF_CASES.items():
            with self.subTest(route=route):
                self._staff_login(role_key)
                url = reverse(route, args=[self.b[pk_attr]])
                response = (
                    self.client.post(url, {}) if method == "POST" else self.client.get(url)
                )
                assert response.status_code in {403, 404, 405}, (
                    route,
                    response.status_code,
                )
                if hasattr(response, "content"):
                    assert B_LEAK_MARKER.encode() not in response.content
                self.client.logout()

    def test_resident_cannot_reach_other_building_objects(self):
        resident_a = self.seed_a.users["resident"]
        self.client.force_login(resident_a)
        for route, (pk_attr, method, expected) in RESIDENT_CASES.items():
            with self.subTest(route=route):
                url = reverse(route, args=[self.b[pk_attr]])
                response = (
                    self.client.post(url, {}) if method == "POST" else self.client.get(url)
                )
                assert response.status_code == expected, (route, response.status_code)

    def test_staff_lists_and_exports_never_leak_other_building(self):
        for role_key in ("operator", "board_approver", "auditor"):
            self._staff_login(role_key)
            for route in LIST_ROUTES:
                with self.subTest(role=role_key, route=route):
                    response = self.client.get(reverse(route))
                    if response.status_code == 200:
                        self.assertNotContains(response, B_BUILDING_NAME)
                        self.assertNotContains(response, B_LEAK_MARKER)
                    else:
                        # Role lacks this workspace: 403 is the correct in-tenant answer.
                        assert response.status_code == 403
            self.client.logout()

    def test_auditor_export_never_leaks_other_building(self):
        self._staff_login("auditor")
        response = self.client.get(reverse("web:audit-export"), {"kind": "fund"})
        assert response.status_code in {200, 400}
        if response.status_code == 200:
            body = b"".join(response.streaming_content) if response.streaming else response.content
            assert B_LEAK_MARKER.encode() not in body
            assert B_BUILDING_NAME.encode() not in body
