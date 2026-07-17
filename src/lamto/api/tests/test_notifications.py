import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.notifications.models import NotificationDelivery
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-notif-")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class NotificationFeedTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Notif B", email_prefix="apin", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.delivery = NotificationDelivery.objects.create(
            recipient=self.resident, building=self.seed.building,
            channel=NotificationDelivery.Channel.IN_APP, status=NotificationDelivery.Status.AVAILABLE,
            event_key="ledger.publication:x:1", event_code="ledger.publication",
            subject="New spending published", body="A new expenditure was published.",
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    def _occ(self):
        from lamto.accounts.models import ResidentOccupancy
        occ = ResidentOccupancy.objects.get(user=self.resident, active=True)
        return {**self._auth(), "x-lamto-occupancy": str(occ.pk)}

    def test_feed_lists_available_and_mark_read(self):
        resp = self.client.get(reverse("api:notifications"), headers=self._occ())
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1 and results[0]["read_at"] is None

        read = self.client.post(reverse("api:notification-read", kwargs={"pk": self.delivery.pk}), headers=self._auth())
        assert read.status_code == 204
        self.delivery.refresh_from_db()
        assert self.delivery.read_at is not None

    def test_feed_exposes_event_key_for_deep_links(self):
        resp = self.client.get(reverse("api:notifications"), headers=self._occ())
        assert resp.status_code == 200
        row = resp.json()["results"][0]
        # Opaque deep-link reference only — not subject/body free text (A8).
        assert row["event_key"] == "ledger.publication:x:1"
        assert row["event_key"] == self.delivery.event_key
        assert self.delivery.subject not in row["event_key"]
        assert self.delivery.body not in row["event_key"]

    def test_mark_read_foreign_delivery_is_404(self):
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apin-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        resp = self.client.post(
            reverse("api:notification-read", kwargs={"pk": self.delivery.pk}), headers=self._auth(stranger)
        )
        assert resp.status_code == 404
