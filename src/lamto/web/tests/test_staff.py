from lamto.web.staff import nav_items_for


def test_registrations_appears_in_staff_navigation():
    assert "Registrations" in [str(item["label"]) for item in nav_items_for(None)]
