import json
import tempfile
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.accounts.models import ResidentOccupancy
from lamto.maintenance.models import IssueReport
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-reports-")


def problem(response):
    return json.loads(response.content)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class ReportCreateTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(
            building_name="API Reports B",
            email_prefix="apir",
            create_sample_report=False,
        )
        self.resident = self.seed.users["resident"]
        self.occupancy = ResidentOccupancy.objects.get(user=self.resident, active=True)

    def _auth(self):
        _instance, token = AuthToken.objects.create(user=self.resident)
        return {"authorization": f"Token {token}"}

    def _body(self, **over):
        base = {
            "client_ref": str(uuid.uuid4()),
            "text": "Lift jerks",
            "location_id": self.seed.location.pk,
        }
        base.update(over)
        return base

    def test_first_create_is_201_and_retry_is_200(self):
        body = self._body()
        first = self.client.post(
            reverse("api:reports"),
            data=body,
            content_type="application/json",
            headers=self._auth(),
        )
        assert first.status_code == 201, first.content
        again = self.client.post(
            reverse("api:reports"),
            data=body,
            content_type="application/json",
            headers=self._auth(),
        )
        assert again.status_code == 200, again.content
        assert IssueReport.objects.filter(reporter=self.resident).count() == 1

    def test_same_ref_different_text_is_409(self):
        ref = str(uuid.uuid4())
        self.client.post(
            reverse("api:reports"),
            data=self._body(client_ref=ref),
            content_type="application/json",
            headers=self._auth(),
        )
        conflict = self.client.post(
            reverse("api:reports"),
            data=self._body(client_ref=ref, text="Different"),
            content_type="application/json",
            headers=self._auth(),
        )
        assert conflict.status_code == 409
        assert problem(conflict)["code"] == "client_ref_conflict"

    def test_foreign_location_is_400(self):
        from lamto.accounts.models import Building
        from lamto.maintenance.models import BuildingLocation

        other = BuildingLocation.objects.create(
            building=Building.objects.create(name="Other"), name="Elsewhere"
        )
        resp = self.client.post(
            reverse("api:reports"),
            data=self._body(location_id=other.pk),
            content_type="application/json",
            headers=self._auth(),
        )
        assert resp.status_code == 400
        assert problem(resp)["code"] == "validation_failed"

    def test_list_returns_only_own_reports(self):
        self.client.post(
            reverse("api:reports"),
            data=self._body(),
            content_type="application/json",
            headers=self._auth(),
        )
        resp = self.client.get(reverse("api:reports"), headers=self._auth())
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["text"] == "Lift jerks"

    def test_detail_timeline_and_foreign_report_404(self):
        create = self.client.post(
            reverse("api:reports"),
            data=self._body(),
            content_type="application/json",
            headers=self._auth(),
        )
        report_id = create.json()["id"]
        detail = self.client.get(
            reverse("api:report-detail", kwargs={"pk": report_id}),
            headers=self._auth(),
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["triage_status"] == "PENDING"
        assert body["cases"] == []
        # A stranger's report id is 404 for this resident.
        from django.contrib.auth import get_user_model

        stranger = get_user_model().objects.create_user(
            email="apir-x@example.com", password="x", display_name="X"
        )
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        other = IssueReport.objects.create(
            reporter=stranger,
            unit=self.seed.unit,
            text="theirs",
            selected_location=self.seed.location,
            location_path_snapshot="x",
        )
        miss = self.client.get(
            reverse("api:report-detail", kwargs={"pk": other.pk}),
            headers=self._auth(),
        )
        assert miss.status_code == 404
