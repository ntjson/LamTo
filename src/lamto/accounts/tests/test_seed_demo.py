"""The demo seed command, tested through the server's HTTP surface (spec: Seam 1).

Logins go through the resident API and the Management sign-in page, and the
seeded state is read back through the same endpoints a visitor would use.
"""

import tempfile
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from lamto.accounts.backends import normalize_phone
from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.finance.models import MaintenanceFundEntry
from lamto.maintenance.models import BuildingLocation
from lamto.testing.factories import DEMO_PASSWORD

DEMO_BUILDING_NAME = "Chung cư Mẫu LamTo"
DEMO_RESIDENT_NAME = "Cư dân Mẫu"
DEMO_MANAGER_NAME = "Ban quản lý Mẫu"
DEMO_OPENING_FUND_VND = 1_000_000_000

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-seed-demo-")
_STORAGES = {
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


def _seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out


def _row_counts():
    return {
        "buildings": Building.objects.count(),
        "users": User.objects.count(),
        "memberships": ManagementMembership.objects.count(),
        "occupancies": ResidentOccupancy.objects.count(),
        "units": Unit.objects.count(),
        "locations": BuildingLocation.objects.count(),
        "fund_entries": MaintenanceFundEntry.objects.count(),
    }


@override_settings(STORAGES=_STORAGES)
class SeedDemoTests(TestCase):
    @override_settings(PILOT_ALLOW_FIXTURES=False)
    def test_refuses_without_fixture_opt_in(self):
        with self.assertRaisesMessage(CommandError, "PILOT_ALLOW_FIXTURES"):
            call_command("seed_demo", stdout=StringIO())
        self.assertFalse(Building.objects.exists())

    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_creates_named_building_with_management_and_resident(self):
        _seed()

        building = Building.objects.get(name=DEMO_BUILDING_NAME)
        manager = ManagementMembership.objects.get(building=building).user
        self.assertEqual(manager.display_name, DEMO_MANAGER_NAME)
        resident = User.objects.get(
            residentoccupancy__unit__building=building, residentoccupancy__active=True
        )
        self.assertEqual(resident.display_name, DEMO_RESIDENT_NAME)

    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_resident_has_synthetic_vietnamese_mobile_phone(self):
        _seed()
        resident = User.objects.get(display_name=DEMO_RESIDENT_NAME)

        self.assertRegex(resident.phone, r"^0(3|5|7|8|9)\d{8}$")
        self.assertEqual(normalize_phone(resident.phone), resident.phone)

    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_prints_both_logins_and_the_password(self):
        out = _seed()
        manager = ManagementMembership.objects.get(building__name=DEMO_BUILDING_NAME).user
        resident = User.objects.get(display_name=DEMO_RESIDENT_NAME)

        text = out.getvalue()

        self.assertIn(manager.email, text)
        self.assertIn(resident.phone, text)
        self.assertIn(DEMO_PASSWORD, text)


@override_settings(STORAGES=_STORAGES)
class SeedDemoLoginTests(TestCase):
    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_resident_signs_in_to_resident_api_with_synthetic_phone(self):
        _seed()
        resident = User.objects.get(display_name=DEMO_RESIDENT_NAME)

        response = self.client.post(
            reverse("api:auth-login"),
            {"identifier": resident.phone, "password": DEMO_PASSWORD},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())

    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_management_signs_in_by_email_and_sees_building(self):
        _seed()
        manager = ManagementMembership.objects.get(building__name=DEMO_BUILDING_NAME).user

        response = self.client.post(
            reverse("login"),
            {"username": manager.email, "password": DEMO_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get("/s/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse("web:action-inbox"))
        self.assertContains(response, DEMO_BUILDING_NAME)


@override_settings(STORAGES=_STORAGES)
class SeedDemoStructureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with override_settings(PILOT_ALLOW_FIXTURES=True):
            _seed()

    def _resident_headers(self):
        resident = User.objects.get(display_name=DEMO_RESIDENT_NAME)
        login = self.client.post(
            reverse("api:auth-login"),
            {"identifier": resident.phone, "password": DEMO_PASSWORD},
            content_type="application/json",
        )
        return {"authorization": f"Token {login.json()['token']}"}

    def _manager_login(self):
        manager = ManagementMembership.objects.get(building__name=DEMO_BUILDING_NAME).user
        self.client.post(
            reverse("login"), {"username": manager.email, "password": DEMO_PASSWORD}
        )

    def test_resident_has_one_unit_in_demo_building(self):
        response = self.client.get(reverse("api:me"), headers=self._resident_headers())

        self.assertEqual(response.status_code, 200)
        occupancies = response.json()["occupancies"]
        self.assertEqual(len(occupancies), 1)
        self.assertEqual(occupancies[0]["building_name"], DEMO_BUILDING_NAME)

    def test_location_tree_has_eight_areas_and_thirty_one_places(self):
        response = self.client.get(reverse("api:locations"), headers=self._resident_headers())

        self.assertEqual(response.status_code, 200)
        rows = response.json()
        areas = [row for row in rows if row["parent_id"] is None]
        places = [row for row in rows if row["parent_id"] is not None]
        self.assertEqual(len(areas), 8)
        self.assertEqual(len(places), 31)

    def test_opening_fund_is_verified_and_shown_to_resident(self):
        response = self.client.get(
            reverse("api:fund-summary"), headers=self._resident_headers()
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance_vnd"], DEMO_OPENING_FUND_VND)

    def test_action_inbox_and_cases_list_are_empty(self):
        self._manager_login()

        inbox = self.client.get(reverse("web:action-inbox"))
        cases = self.client.get(reverse("web:case-list"))

        self.assertEqual(inbox.status_code, 200)
        self.assertEqual(list(inbox.context["action_page"].object_list), [])
        self.assertEqual(cases.status_code, 200)
        self.assertEqual(list(cases.context["case_list"]["page"].object_list), [])


@override_settings(STORAGES=_STORAGES)
class SeedDemoRefusalTests(TestCase):
    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_rerun_with_existing_building_name_is_refused_without_partial_rows(self):
        _seed()
        before = _row_counts()

        with self.assertRaisesMessage(CommandError, DEMO_BUILDING_NAME):
            _seed()

        self.assertEqual(_row_counts(), before)

    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_reused_login_prefix_is_refused_without_partial_rows(self):
        _seed()
        before = _row_counts()

        with self.assertRaisesMessage(CommandError, "Login prefix 'demo' is already in use"):
            _seed("--building-name", "Chung cư Mẫu Ba")

        self.assertEqual(_row_counts(), before)


@override_settings(STORAGES=_STORAGES)
class SeedDemoParameterTests(TestCase):
    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_second_building_with_other_name_and_prefix_sits_beside_the_first(self):
        _seed()
        _seed(
            "--building-name", "Chung cư Mẫu Hai",
            "--login-prefix", "visitorb",
            "--password", "other-demo-secret",
        )

        self.assertEqual(Building.objects.count(), 2)
        second = Building.objects.get(name="Chung cư Mẫu Hai")
        manager = ManagementMembership.objects.get(building=second).user
        self.assertEqual(manager.email, "visitorb-management-1@demo.lamto.test")
        self.assertTrue(manager.check_password("other-demo-secret"))
