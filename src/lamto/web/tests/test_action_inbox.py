from django.urls import reverse

from lamto.web.action_inbox import action_items_for
from lamto.web.tests.test_staff_registrations import registration, setup_building


def test_pending_registration_appears_in_building_inbox(db):
    membership, unit = setup_building("Tower A", "manager-a@example.test")
    _other_membership, other_unit = setup_building("Tower B", "manager-b@example.test")
    request = registration(unit)
    registration(other_unit, phone="0901234568", email="other@example.test")

    items = [item for item in action_items_for(membership) if item.kind == "registration"]

    assert len(items) == 1
    assert items[0].title == request.full_name
    assert items[0].url == reverse("web:staff-registration-detail", args=[request.pk])
