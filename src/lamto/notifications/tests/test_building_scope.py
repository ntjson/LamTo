from django.contrib.auth import get_user_model
from django.test import TestCase

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.maintenance.models import BuildingLocation
from lamto.maintenance.reporting import submit_report
from lamto.notifications.hooks import notify_report_receipt
from lamto.notifications.models import NotificationDelivery
from lamto.notifications.services import queue_notification


class NotificationBuildingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Notify Building")
        cls.unit = Unit.objects.create(building=cls.building, label="N-1")
        cls.user = get_user_model().objects.create_user(
            email="notify@example.test", password="x", display_name="N"
        )
        ResidentOccupancy.objects.create(user=cls.user, unit=cls.unit)
        cls.location = BuildingLocation.objects.create(
            building=cls.building, name="Notify Lobby"
        )

    def test_queue_notification_stores_building(self):
        rows = queue_notification(
            self.user,
            event_key="test:building:1",
            subject="s",
            body="b",
            building=self.building,
        )
        assert rows and all(r.building_id == self.building.pk for r in rows)

    def test_report_receipt_hook_stamps_building(self):
        # submit_report (not a bare create) so this test stays valid after
        # Task 7 makes IssueReport.building non-null.
        report = submit_report(self.user, self.unit, "TEST notify", self.location, [])
        # Hooks enqueue after commit; TestCase captures on_commit callbacks.
        with self.captureOnCommitCallbacks(execute=True):
            notify_report_receipt(report)
        deliveries = NotificationDelivery.objects.filter(recipient=self.user)
        assert deliveries.exists()
        assert all(d.building_id == self.building.pk for d in deliveries)
