from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    ResidentOccupancy,
    Unit,
    User,
)
from lamto.audit.models import AuditEvent
from lamto.notifications.announcements import publish_announcement
from lamto.notifications.models import Announcement, NotificationDelivery
from lamto.notifications.services import process_due_notifications


class AnnouncementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Building One")
        cls.other_building = Building.objects.create(name="Building Two")
        cls.unit = Unit.objects.create(building=cls.building, label="101")
        cls.other_unit = Unit.objects.create(building=cls.other_building, label="201")
        cls.manager = User.objects.create_user(
            email="manager@example.test", password="pw", display_name="Manager"
        )
        cls.membership = ManagementMembership.objects.create(
            user=cls.manager, building=cls.building
        )

    def test_model_defaults_and_length_validation(self):
        announcement = Announcement(
            building=self.building,
            title="Notice",
            body="Details",
            created_by=self.manager,
            updated_by=self.manager,
        )

        assert announcement.revision == 1
        assert announcement.state == Announcement.State.PUBLISHED

        announcement.title = "x" * 161
        announcement.body = "x" * 2001
        with self.assertRaises(ValidationError) as error:
            announcement.full_clean()
        assert set(error.exception.message_dict) == {"title", "body"}

    def test_publish_requires_active_management_of_selected_building(self):
        with self.assertRaises(PermissionDenied):
            publish_announcement(
                self.manager, self.other_building.id, "Notice", "Details"
            )

        self.membership.active = False
        self.membership.save(update_fields=["active"])
        with self.assertRaises(PermissionDenied):
            publish_announcement(self.manager, self.building.id, "Notice", "Details")

        assert not Announcement.objects.exists()

    def test_publish_fans_out_once_to_each_distinct_active_resident(self):
        resident = User.objects.create_user(
            email="resident@example.test", password="pw", display_name="Resident"
        )
        second_unit = Unit.objects.create(building=self.building, label="102")
        ResidentOccupancy.objects.create(user=resident, unit=self.unit)
        ResidentOccupancy.objects.create(user=resident, unit=second_unit)

        inactive_occupancy = User.objects.create_user(
            email="inactive-occupancy@example.test",
            password="pw",
            display_name="Inactive occupancy",
        )
        ResidentOccupancy.objects.create(
            user=inactive_occupancy, unit=self.unit, active=False
        )
        inactive_user = User.objects.create_user(
            email="inactive-user@example.test",
            password="pw",
            display_name="Inactive user",
            is_active=False,
        )
        ResidentOccupancy.objects.create(user=inactive_user, unit=self.unit)
        other_resident = User.objects.create_user(
            email="other@example.test", password="pw", display_name="Other"
        )
        ResidentOccupancy.objects.create(user=other_resident, unit=self.other_unit)

        announcement = publish_announcement(
            self.manager, self.building.id, "Water shutdown", "From 10:00 to 12:00"
        )
        process_due_notifications(limit=10)

        delivery = NotificationDelivery.objects.get(
            recipient=resident,
            channel=NotificationDelivery.Channel.IN_APP,
        )
        assert delivery.event_key == (
            f"building.announcement:announcement:{announcement.id}"
        )
        assert delivery.event_code == "building.announcement"
        assert delivery.subject == announcement.title
        assert delivery.body == announcement.body
        assert delivery.status == NotificationDelivery.Status.AVAILABLE
        assert NotificationDelivery.objects.count() == 1
        assert not NotificationDelivery.objects.filter(
            channel=NotificationDelivery.Channel.EMAIL
        ).exists()

        event = AuditEvent.objects.get(action="announcement.published")
        assert event.actor == self.manager
        assert event.membership == self.membership
        assert event.target_type == "Announcement"
        assert event.target_id == str(announcement.id)
        assert event.metadata == {
            "announcement_id": announcement.id,
            "revision": 1,
        }
        assert "title" not in event.metadata
        assert "body" not in event.metadata
