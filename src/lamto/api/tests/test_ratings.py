import json
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.maintenance.models import CompletionRating, WorkOrder
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-rate-")


def problem(response):
    return json.loads(response.content)


def _accepted_work(seed):
    d = PilotDomainDriver(seed)
    d.login(None, "resident").submit_report("Lift noise", "Lift 2")
    d.login(None, "operator").confirm_triage_and_create_paid_work_order()
    d.login(None, "operator").submit_signed_proposal()
    d.login(None, "maintenance").complete_assigned_work()
    d.login(None, "board_payment_recorder").accept_and_record_payment()
    d.confirm_all_chain_events()
    return WorkOrder.objects.get(case__building=seed.building)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class WorkRatingTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Rate B", email_prefix="apirate", create_sample_report=False)
        self.resident = self.seed.residents[0]
        self.work = _accepted_work(self.seed)

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    def test_reporter_can_rate_once(self):
        url = reverse("api:work-rating", kwargs={"pk": self.work.pk})
        first = self.client.post(url, data={"score": 5, "comment": "Great"}, content_type="application/json", headers=self._auth())
        assert first.status_code == 201, first.content
        assert CompletionRating.objects.filter(work_order=self.work, resident=self.resident).count() == 1
        again = self.client.post(url, data={"score": 4}, content_type="application/json", headers=self._auth())
        assert again.status_code == 400  # already rated

    def test_non_reporter_cannot_rate(self):
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apirate-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        resp = self.client.post(
            reverse("api:work-rating", kwargs={"pk": self.work.pk}),
            data={"score": 5}, content_type="application/json", headers=self._auth(stranger),
        )
        assert resp.status_code == 404  # did not report this case -> existence not revealed
