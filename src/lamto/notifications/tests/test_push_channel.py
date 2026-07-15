import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.notifications.devices import register_device
from lamto.notifications.models import Device, NotificationDelivery, NotificationPreference
from lamto.notifications.services import EVENT_PUBLICATION, EVENT_PAYMENT_RECORDED, queue_notification


@override_settings(PUSH_ENABLED=True)
class PushQueueGatingTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Push B")
        self.unit = Unit.objects.create(building=self.building, label="A-1")
        self.resident = get_user_model().objects.create_user(email="r@example.test", password="x", display_name="R")
        ResidentOccupancy.objects.create(user=self.resident, unit=self.unit, active=True)

    def _push_rows(self):
        return NotificationDelivery.objects.filter(recipient=self.resident, channel=NotificationDelivery.Channel.PUSH)

    def test_push_row_created_only_with_active_device(self):
        # No device yet -> no PUSH row.
        queue_notification(self.resident, f"{EVENT_PUBLICATION}:entry:1", "s", "b", event_code=EVENT_PUBLICATION, building=self.building)
        assert self._push_rows().count() == 0
        # Register a device -> PUSH row is created for a resident-push event.
        register_device(self.resident, str(uuid.uuid4()), "tok", Device.Platform.ANDROID)
        queue_notification(self.resident, f"{EVENT_PUBLICATION}:entry:2", "s", "b", event_code=EVENT_PUBLICATION, building=self.building)
        assert self._push_rows().count() == 1

    def test_non_resident_event_gets_no_push(self):
        register_device(self.resident, str(uuid.uuid4()), "tok", Device.Platform.ANDROID)
        queue_notification(self.resident, f"{EVENT_PAYMENT_RECORDED}:payment:1", "s", "b", event_code=EVENT_PAYMENT_RECORDED, building=self.building)
        assert self._push_rows().count() == 0

    def test_push_preference_off_suppresses(self):
        register_device(self.resident, str(uuid.uuid4()), "tok", Device.Platform.ANDROID)
        NotificationPreference.objects.create(user=self.resident, event_code=EVENT_PUBLICATION, push_enabled=False)
        queue_notification(self.resident, f"{EVENT_PUBLICATION}:entry:3", "s", "b", event_code=EVENT_PUBLICATION, building=self.building)
        assert self._push_rows().count() == 0
