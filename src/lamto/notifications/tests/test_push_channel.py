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

    def test_work_rateable_notifies_reporting_resident(self):
        from lamto.notifications.hooks import notify_work_rateable
        from lamto.notifications.services import EVENT_WORK_COMPLETED
        from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
        from lamto.maintenance.models import WorkOrder
        import tempfile
        from django.test import override_settings

        with override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tempfile.mkdtemp()}},
                "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tempfile.mkdtemp()}},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            }
        ):
            seed = seed_pilot_world(building_name="Rate B", email_prefix="rate", create_sample_report=False)
            d = PilotDomainDriver(seed)
            d.login(None, "resident").submit_report("Lift noise", "Lift 2")
            d.login(None, "operator").confirm_triage_and_create_paid_work_order()
            d.login(None, "operator").submit_signed_proposal()
            d.login(None, "maintenance").complete_assigned_work()
            d.login(None, "board_payment_recorder").accept_and_record_payment()
            d.confirm_all_chain_events()
            work = WorkOrder.objects.get(case__building=seed.building)
            from lamto.finance.models import AcceptanceRecord
            record = AcceptanceRecord.objects.get(work_order=work)
            # notify_users queues via transaction.on_commit; fire it in-test.
            with self.captureOnCommitCallbacks(execute=True):
                notify_work_rateable(record)
            assert NotificationDelivery.objects.filter(
                recipient=seed.users["resident"], event_code=EVENT_WORK_COMPLETED,
            ).exists()
