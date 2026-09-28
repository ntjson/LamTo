
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse

from lamto.accounts.models import Building, ManagementMembership
from lamto.web.staff import gate_nav_items_for, nav_sections_for


@override_settings(LANGUAGE_CODE="en", ROOT_URLCONF="lamto.config.urls")
class ManagementShellTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Nav Building")
        self.user = get_user_model().objects.create_user(
            email="manager@example.test", password="secret", display_name="Manager"
        )
        self.membership = ManagementMembership.objects.create(
            user=self.user, building=self.building
        )

    def _login(self, user):
        self.client.force_login(user)

    def test_management_user_sees_staff_areas(self):
        sections = nav_sections_for(self.membership)
        labels = [str(item["label"]) for section in sections for item in section["items"]]
        # Every destination sits in the one sidebar; actions such as
        # "New proposal" are page buttons, not places, so they are absent.
        self.assertEqual(
            labels,
            [
                "Inbox",
                "Cases",
                "Proposals",
                "Settlements",
                "Maintenance fund",
                "Gate",
                "Resident registrations",
                "Announcements",
                "Bills",
                "Health",
                "Exceptions",
                "Metrics",
                "Exports",
            ],
        )
        self.assertNotIn("New proposal", labels)
        self.assertEqual(
            [str(item["label"]) for item in gate_nav_items_for(self.membership)],
            ["Review", "Registrations", "Readers", "Activity"],
        )

    def test_sidebar_marks_the_current_destination(self):
        self._login(self.user)
        response = self.client.get(reverse("web:fund-home"))

        html = response.content.decode()
        self.assertIn(
            f'class="nav-link is-active" aria-current="page" href="{reverse("web:fund-home")}"',
            html,
        )
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_proposal_list_offers_new_proposal_as_an_action(self):
        self._login(self.user)
        response = self.client.get(reverse("web:proposal-list"))

        self.assertContains(
            response,
            f'<a class="button button-primary" href="{reverse("web:standalone-proposal-create")}">',
        )

    def test_base_template_uses_the_product_identity(self):
        html = render_to_string("web/base.html")

        self.assertIn('rel="icon"', html)
        self.assertIn('lamto-mark.png', html)
        self.assertIn('alt=""', html)
        # One brand on both sides of sign-in: "Làm Tổ Management" / "Làm Tổ Quản lý".
        self.assertIn('Làm Tổ', html)
        self.assertNotIn('LÀM TỔ', html)

    def test_public_shell_template_carries_brand_and_stylesheet_without_authenticated_chrome(self):
        html = render_to_string("web/public/shell.html")

        self.assertIn('rel="icon"', html)
        self.assertIn('web/app.css', html)
        self.assertIn('lamto-mark.png', html)
        self.assertIn('Làm Tổ', html)
        self.assertIn('<main id="main" class="site-main"', html)
        self.assertIn('class="public"', html)

        # No authenticated chrome
        self.assertNotIn('logout', html)
        self.assertNotIn('membership-switcher', html)
        self.assertNotIn('staff-nav', html)
        self.assertNotIn('Sign out', html)
        self.assertNotIn('Đăng xuất', html)

    def test_non_management_user_is_denied_staff_home(self):
        resident = get_user_model().objects.create_user(
            email="resident@example.test", password="secret", display_name="Resident"
        )
        self._login(resident)
        self.assertEqual(self.client.get(reverse("web:staff-home")).status_code, 403)

    def test_switch_building_returns_to_inbox(self):
        other = Building.objects.create(name="Other Building")
        selected = ManagementMembership.objects.create(user=self.user, building=other)
        self._login(self.user)
        response = self.client.post(
            reverse("web:switch-building"), {"building": selected.pk}
        )
        self.assertRedirects(response, reverse("web:action-inbox"))
        self.assertEqual(self.client.session["active_management_id"], selected.pk)
