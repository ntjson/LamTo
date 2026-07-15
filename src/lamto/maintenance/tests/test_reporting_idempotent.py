import tempfile
import uuid

from django.core.files.storage import storages
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import BuildingLocation, IssueReport
from lamto.maintenance.reporting import (
    ReportClientRefConflict,
    submit_report_idempotent,
)
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-idem-")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class IdempotentSubmitTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="Idem B", email_prefix="idem", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.unit = self.seed.unit
        self.location = self.seed.location

    def test_first_submit_creates_then_retry_returns_same(self):
        ref = uuid.uuid4()
        report, created = submit_report_idempotent(
            self.resident, self.unit, "Lift jerks", self.location, [], ref
        )
        assert created is True
        again, created2 = submit_report_idempotent(
            self.resident, self.unit, "Lift jerks", self.location, [], ref
        )
        assert created2 is False
        assert again.pk == report.pk
        assert IssueReport.objects.filter(reporter=self.resident).count() == 1

    def test_same_ref_different_text_conflicts(self):
        ref = uuid.uuid4()
        submit_report_idempotent(self.resident, self.unit, "Lift jerks", self.location, [], ref)
        try:
            submit_report_idempotent(self.resident, self.unit, "Different text", self.location, [], ref)
            assert False, "expected ReportClientRefConflict"
        except ReportClientRefConflict:
            pass
