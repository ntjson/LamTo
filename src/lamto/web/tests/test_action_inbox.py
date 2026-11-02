from django.urls import reverse
from django.test import override_settings

from lamto.web.action_inbox import ActionItem, action_items_for
from lamto.web.tests.test_staff_registrations import registration, setup_building
from lamto.web.templatetags.staff_extras import vnd_compact
from lamto.web.views.staff_common import prepare_action_inbox, queue_tiles


def test_pending_registration_appears_in_building_inbox(db):
    membership, unit = setup_building("Tower A", "manager-a@example.test")
    _other_membership, other_unit = setup_building("Tower B", "manager-b@example.test")
    request = registration(unit)
    registration(other_unit, phone="0901234568", email="other@example.test")

    items = [item for item in action_items_for(membership) if item.kind == "registration"]

    assert len(items) == 1
    assert items[0].title == request.full_name
    assert items[0].url == reverse("web:staff-registration-detail", args=[request.pk])


@override_settings(LANGUAGE_CODE="en")
def test_inbox_kind_filter_uses_static_label_instead_of_item_title():
    item = ActionItem(
        kind="registration",
        title="Nguyen Van A",
        summary="A-1",
        target_type="RegistrationRequest",
        target_id=1,
        url="/s/registrations/1/",
    )

    inbox = prepare_action_inbox([item])

    assert inbox["kind_filters"] == [
        {"value": "registration", "label": "Resident registration", "active": False}
    ]


def _item(kind, target_id):
    return ActionItem(
        kind=kind, title="T", summary="S", target_type="X",
        target_id=target_id, url=f"/s/x/{target_id}/",
    )


@override_settings(LANGUAGE_CODE="en")
def test_queue_tiles_count_every_open_item_whatever_the_filter():
    items = [
        _item("registration", 1),
        _item("deadline_risk", 2),
        _item("deadline_risk", 3),
        _item("failed_outbox", 4),
    ]

    tiles = queue_tiles(items, active_status="due_soon")

    assert [(t["value"], t["count"], t["active"]) for t in tiles] == [
        ("do_now", 1, False),
        ("due_soon", 2, True),
        ("exceptions", 1, False),
        ("", 4, False),
    ]


@override_settings(LANGUAGE_CODE="en", USE_THOUSAND_SEPARATOR=True)
def test_vnd_compact_shortens_amounts_for_calendar_cells():
    assert vnd_compact(950) == "950"
    assert vnd_compact(-82_000) == "82\u00a0K"
    assert vnd_compact(1_500_000) == "1.5\u00a0M"
    assert vnd_compact(26_500_000) == "26.5\u00a0M"
    assert vnd_compact(1_000_000_000) == "1\u00a0B"
    assert vnd_compact("n/a") == "n/a"
