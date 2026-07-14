"""GET /me — profile, active occupancies, notification prefs (spec 3.3)."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from knox.models import AuthToken

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.notifications.models import NotificationPreference


class MeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.resident = User.objects.create_user(
            email="me-resident@example.com",
            password="resident-pass-123",
            display_name="Me Resident",
            phone="0987654321",
        )
        building_a = Building.objects.create(name="Building Alpha")
        building_b = Building.objects.create(name="Building Beta")
        cls.occupancy_a = ResidentOccupancy.objects.create(
            user=cls.resident,
            unit=Unit.objects.create(building=building_a, label="A-101"),
            active=True,
        )
        cls.occupancy_b = ResidentOccupancy.objects.create(
            user=cls.resident,
            unit=Unit.objects.create(building=building_b, label="B-202"),
            active=True,
        )
        NotificationPreference.objects.create(
            user=cls.resident, event_code="ledger.published", email_enabled=False
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    def test_me_returns_profile_occupancies_and_prefs(self):
        response = self.client.get(reverse("api:me"), headers=self._auth())
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["display_name"] == "Me Resident"
        assert body["email"] == "me-resident@example.com"
        assert body["phone"] == "0987654321"
        occupancies = {o["id"]: o for o in body["occupancies"]}
        assert set(occupancies) == {self.occupancy_a.pk, self.occupancy_b.pk}
        assert occupancies[self.occupancy_a.pk]["unit_label"] == "A-101"
        assert occupancies[self.occupancy_a.pk]["building_name"] == "Building Alpha"
        assert body["notification_preferences"] == [
            {"event_code": "ledger.published", "email_enabled": False}
        ]

    def test_me_requires_token(self):
        response = self.client.get(reverse("api:me"))
        assert response.status_code == 401
        assert response["Content-Type"].startswith("application/problem+json")
        assert json.loads(response.content)["code"] == "not_authenticated"

    def test_me_without_active_occupancy_rejects_token(self):
        """No active occupancy → residual knox token is revoked at authenticate.

        Staff (or a former resident after bulk deactivation) never receive data.
        Auth-time cleanup turns leftover tokens into authentication_failed rather
        than leaving a live token that only fails later with 403.
        """
        staff = get_user_model().objects.create_user(
            email="me-staff@example.com",
            password="resident-pass-123",
            display_name="Me Staff",
        )
        headers = self._auth(staff)
        response = self.client.get(reverse("api:me"), headers=headers)
        assert response.status_code == 401
        assert response["Content-Type"].startswith("application/problem+json")
        assert json.loads(response.content)["code"] == "authentication_failed"
        assert not AuthToken.objects.filter(user=staff).exists()
