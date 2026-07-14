"""Two-building adversarial isolation suite (spec 2.3 layer 4).

Building A actors request Building B objects by primary key: the answer must
always be 404 (cross-tenant), 403 (ownership), or 405 (method), never data.
List pages and exports rendered for Building A must not contain Building B
markers.

Completeness:
- Web: every <int:pk> route must appear in STAFF_CASES, RESIDENT_CASES, or EXEMPT.
- API: every registered named route must appear in exactly one of the API
  classification maps (clarification 4: public-auth / authenticated-global /
  tenant-list / tenant-object / explicitly exempt).
"""

import tempfile
import time

from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from knox.models import AuthToken

from lamto.accounts.models import ResidentOccupancy
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.fund import fund_balance
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

# ---------------------------------------------------------------------------
# API route classification (clarification 4). Completeness walks *every*
# named pattern in lamto.api.urls — not only <int:pk> routes.
# ---------------------------------------------------------------------------

# Public unauthenticated auth surface (login).
API_PUBLIC_AUTH = {
    "api:auth-login": "POST login (phone/email → knox token)",
}

# Authenticated but user-scoped, not building-tenant.
API_AUTHENTICATED_GLOBAL = {
    "api:auth-logout": "POST revoke current knox token",
    "api:auth-logout-all": "POST revoke all knox tokens for user",
    "api:me": "GET profile + occupancies",
}

# Tenant-scoped lists / aggregates (building via occupancy resolution).
API_TENANT_LIST = {
    "api:ledger-list": "GET",
    "api:fund-summary": "GET",
}

# Tenant-scoped object access by primary key.
# route -> (attribute on cls.b with the B-side pk, method, expected status)
API_TENANT_OBJECT = {
    "api:ledger-detail": ("ledger_pk", "GET", 404),
}

# Explicitly non-tenant / non-walked routes (none in Phase 0).
API_EXEMPT = {}

# Back-compat aliases used by walk helpers (brief Step 1 names).
API_RESIDENT_CASES = API_TENANT_OBJECT
API_LIST_ROUTES = list(API_TENANT_LIST)


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
        """Web <int:pk> routes + every registered API route must be classified."""
        from lamto.api import urls as api_urls
        from lamto.web import urls as web_urls

        pk_routes = {
            f"web:{pattern.name}"
            for pattern in web_urls.urlpatterns
            if "<int:" in str(pattern.pattern)
        }
        web_classified = set(STAFF_CASES) | set(RESIDENT_CASES) | set(EXEMPT)
        missing_web = pk_routes - web_classified
        assert not missing_web, (
            f"New web pk routes must be classified in the isolation suite: "
            f"{missing_web}"
        )

        # Clarification 4: every registered API route, not only <int:pk>.
        api_routes = {
            f"api:{pattern.name}"
            for pattern in api_urls.urlpatterns
            if getattr(pattern, "name", None)
        }
        api_classified = (
            set(API_PUBLIC_AUTH)
            | set(API_AUTHENTICATED_GLOBAL)
            | set(API_TENANT_LIST)
            | set(API_TENANT_OBJECT)
            | set(API_EXEMPT)
        )
        missing_api = api_routes - api_classified
        extra_api = api_classified - api_routes
        assert not missing_api, (
            f"New API routes must be classified in the isolation suite "
            f"(public-auth / authenticated-global / tenant-list / "
            f"tenant-object / explicitly exempt): {missing_api}"
        )
        assert not extra_api, (
            f"Isolation suite classifies unknown API routes: {extra_api}"
        )

        # Classification maps must be disjoint so a route has one category.
        maps = [
            set(API_PUBLIC_AUTH),
            set(API_AUTHENTICATED_GLOBAL),
            set(API_TENANT_LIST),
            set(API_TENANT_OBJECT),
            set(API_EXEMPT),
        ]
        seen: set[str] = set()
        for bucket in maps:
            overlap = seen & bucket
            assert not overlap, f"API route classified more than once: {overlap}"
            seen |= bucket

    def test_staff_cannot_reach_other_building_objects(self):
        for route, (pk_attr, role_key, method) in STAFF_CASES.items():
            with self.subTest(route=route):
                self._staff_login(role_key)
                url = reverse(route, args=[self.b[pk_attr]])
                response = (
                    self.client.post(url, {}) if method == "POST" else self.client.get(url)
                )
                # Design §2.3: pure cross-tenant object access is 404 (not 403).
                # Roles here already hold the capability for the route inside
                # their own building, so the only failure mode is wrong tenant.
                assert response.status_code == 404, (route, response.status_code)
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

    def _api_auth(self, user):
        _instance, token = AuthToken.objects.create(user=user)
        return {"authorization": f"Token {token}"}

    def test_api_resident_cannot_reach_other_building_objects(self):
        """Cross-building tenant-object access is 404 with no leak markers."""
        auth = self._api_auth(self.seed_a.users["resident"])
        for route, (pk_attr, method, expected) in API_TENANT_OBJECT.items():
            with self.subTest(route=route):
                url = reverse(route, args=[self.b[pk_attr]])
                assert method == "GET"
                response = self.client.get(url, headers=auth)
                # Design §2.3: cross-tenant object access is 404, never data.
                assert response.status_code == expected, (route, response.status_code)
                assert B_LEAK_MARKER.encode() not in response.content
                assert B_BUILDING_NAME.encode() not in response.content

    def test_api_rejects_foreign_occupancy_header(self):
        """Foreign occupancy header must not resolve to another building's data."""
        auth = self._api_auth(self.seed_a.users["resident"])
        b_occupancy = ResidentOccupancy.objects.get(
            user=self.seed_b.users["resident"], active=True
        )
        for route in API_TENANT_LIST:
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(route),
                    headers={**auth, "x-lamto-occupancy": str(b_occupancy.pk)},
                )
                assert response.status_code == 404, (route, response.status_code)
                assert B_LEAK_MARKER.encode() not in response.content
                assert B_BUILDING_NAME.encode() not in response.content

    def test_api_lists_never_leak_other_building(self):
        """Tenant lists/aggregates for A omit Building B data and markers."""
        auth = self._api_auth(self.seed_a.users["resident"])

        list_response = self.client.get(reverse("api:ledger-list"), headers=auth)
        assert list_response.status_code == 200
        listed_ids = [row["id"] for row in list_response.json()["results"]]
        assert self.b["ledger_pk"] not in listed_ids
        assert B_LEAK_MARKER.encode() not in list_response.content
        assert B_BUILDING_NAME.encode() not in list_response.content

        fund_response = self.client.get(reverse("api:fund-summary"), headers=auth)
        assert fund_response.status_code == 200
        expected_balance = fund_balance(self.seed_a.building.pk, verified_only=True)
        assert fund_response.json()["balance_vnd"] == expected_balance
        # Building B has a paid work-order path; its balance must not be returned.
        b_balance = fund_balance(self.seed_b.building.pk, verified_only=True)
        if b_balance != expected_balance:
            assert fund_response.json()["balance_vnd"] != b_balance
        assert B_LEAK_MARKER.encode() not in fund_response.content
        assert B_BUILDING_NAME.encode() not in fund_response.content

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
        b_event_ids = list(
            BlockchainOutboxEvent.objects.filter(
                building_id=self.seed_b.building.pk
            ).values_list("event_id", flat=True)
        )
        for kind in ("fund_entries", "outbox", "audit_events", "documents"):
            with self.subTest(kind=kind):
                response = self.client.get(reverse("web:audit-export"), {"kind": kind})
                assert response.status_code in {200, 400}
                if response.status_code != 200:
                    continue
                body = (
                    b"".join(response.streaming_content)
                    if getattr(response, "streaming", False)
                    else response.content
                )
                assert B_LEAK_MARKER.encode() not in body
                assert B_BUILDING_NAME.encode() not in body
                for event_id in b_event_ids:
                    assert event_id.encode() not in body
