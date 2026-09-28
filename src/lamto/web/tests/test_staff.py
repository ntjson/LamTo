from django.test import override_settings

from lamto.web.staff import nav_sections_for


def _labels(section):
    return [str(item["label"]) for item in section["items"]]


def _section(label):
    return next(s for s in nav_sections_for(None) if str(s["label"]) == label)


@override_settings(LANGUAGE_CODE="en")
def test_registrations_appears_in_building_navigation():
    assert "Resident registrations" in _labels(_section("Building"))


@override_settings(LANGUAGE_CODE="en")
def test_announcements_appears_in_building_navigation():
    assert "Announcements" in _labels(_section("Building"))


@override_settings(LANGUAGE_CODE="en")
def test_sidebar_chunks_destinations_into_four_groups():
    # One unlabelled group of daily starting points, then three labelled
    # chunks — few enough to scan without holding the whole list in mind.
    sections = nav_sections_for(None)
    assert [s["label"] and str(s["label"]) for s in sections] == [
        None,
        "Finance",
        "Building",
        "Ops",
    ]
    assert _labels(sections[0]) == ["Inbox", "Cases"]
