from django.test import override_settings

from lamto.web.staff import nav_items_for


@override_settings(LANGUAGE_CODE="en")
def test_registrations_appears_in_staff_navigation():
    assert "Registrations" in [str(item["label"]) for item in nav_items_for(None)]


def test_announcements_appears_in_staff_navigation():
    assert "Announcements" in [str(item["label"]) for item in nav_items_for(None)]
