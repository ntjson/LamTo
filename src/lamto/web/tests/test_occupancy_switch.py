from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.accounts.tenancy import SESSION_OCCUPANCY_KEY


class OccupancySwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="switcher@example.test", password="pw", display_name="S"
        )
        cls.building_a = Building.objects.create(name="Switch Building A")
        cls.building_b = Building.objects.create(name="Switch Building B")
        unit_a = Unit.objects.create(building=cls.building_a, label="A-1")
        unit_b = Unit.objects.create(building=cls.building_b, label="B-1")
        cls.occ_a = ResidentOccupancy.objects.create(user=cls.user, unit=unit_a)
        cls.occ_b = ResidentOccupancy.objects.create(user=cls.user, unit=unit_b)

    def setUp(self):
        self.client.force_login(self.user)

    def test_switch_pins_session_and_redirects_home(self):
        response = self.client.post(
            reverse("web:switch-occupancy"), {"occupancy": self.occ_b.pk}
        )
        assert response.status_code == 302
        assert self.client.session[SESSION_OCCUPANCY_KEY] == self.occ_b.pk

    def test_foreign_occupancy_is_404(self):
        other = get_user_model().objects.create_user(
            email="other2@example.test", password="pw", display_name="O"
        )
        foreign = ResidentOccupancy.objects.create(
            user=other, unit=Unit.objects.create(building=self.building_a, label="A-2")
        )
        response = self.client.post(
            reverse("web:switch-occupancy"), {"occupancy": foreign.pk}
        )
        assert response.status_code == 404

    def test_get_not_allowed(self):
        assert self.client.get(reverse("web:switch-occupancy")).status_code == 405

    def test_account_lists_switcher_only_for_multi_occupancy(self):
        response = self.client.get(reverse("web:account"))
        self.assertContains(response, "Switch unit")
        self.assertContains(response, "Switch Building B")

    def test_unsafe_next_is_ignored(self):
        response = self.client.post(
            reverse("web:switch-occupancy"),
            {"occupancy": self.occ_a.pk, "next": "https://evil.example/"},
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("web:resident-home")
