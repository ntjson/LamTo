import json
from unittest.mock import patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.maintenance.ai import process_triage_job
from lamto.maintenance.candidates import find_duplicate_candidates
from lamto.maintenance.models import BuildingLocation, IssueReport, TriageJob, TriageSuggestion
from lamto.maintenance.reporting import submit_report


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


@override_settings(AI_TRIAGE_URL="https://triage.example.test/v1/triage", AI_TRIAGE_TOKEN="token")
class TriageTests(TestCase):
    def submit(self, text):
        building = getattr(self, "building", None) or Building.objects.create(name="Building B")
        self.building = building
        resident = get_user_model().objects.create_user(
            email=f"resident-{IssueReport.objects.count()}@example.test",
            password="secret",
            display_name="Resident",
        )
        unit = Unit.objects.create(building=building, label=f"A-{IssueReport.objects.count()}")
        ResidentOccupancy.objects.create(user=resident, unit=unit)
        location, _ = BuildingLocation.objects.get_or_create(building=building, name="Lift 2")
        return submit_report(resident, unit, text, location, [])

    @patch("lamto.maintenance.ai.urlopen")
    def test_valid_response_creates_suggestion(self, urlopen):
        candidate = self.submit("Elevator shakes loudly")
        report = self.submit("Elevator shakes")
        urlopen.return_value = FakeResponse(
            {
                "category": "Elevator",
                "interpreted_location": "Building B / Lift 2",
                "urgency": "HIGH",
                "confidence_percent": 87,
                "requires_manual_review": False,
                "duplicate_report_ids": [candidate.id],
                "department": "Maintenance",
                "deadline_minutes": 240,
                "provider_request_id": "req-123",
            }
        )

        job = process_triage_job(report.triage_job.id)

        self.assertEqual(job.status, TriageJob.Status.SUCCEEDED)
        self.assertEqual(TriageSuggestion.objects.get(job=job).duplicate_report_ids, [candidate.id])
        request = urlopen.call_args.args[0]
        self.assertNotIn("photo", request.data.decode())

    @patch("lamto.maintenance.ai.urlopen", side_effect=URLError("offline"))
    def test_transport_failure_preserves_report_for_manual_triage(self, _urlopen):
        report = self.submit("Elevator shakes")

        job = process_triage_job(report.triage_job.id)

        self.assertEqual(job.status, TriageJob.Status.NEEDS_MANUAL)
        self.assertTrue(IssueReport.objects.filter(pk=report.pk).exists())
        self.assertIn("transport", job.failure_reason)

    @patch("lamto.maintenance.ai.urlopen")
    def test_invalid_duplicate_id_routes_to_manual_triage(self, urlopen):
        report = self.submit("Elevator shakes")
        urlopen.return_value = FakeResponse(
            {
                "category": "Elevator",
                "interpreted_location": "Building B / Lift 2",
                "urgency": "HIGH",
                "confidence_percent": 87,
                "requires_manual_review": False,
                "duplicate_report_ids": [999],
                "department": "Maintenance",
                "deadline_minutes": 240,
                "provider_request_id": "req-123",
            }
        )

        job = process_triage_job(report.triage_job.id)

        self.assertEqual(job.status, TriageJob.Status.NEEDS_MANUAL)
        self.assertEqual(TriageSuggestion.objects.count(), 0)

    @patch("lamto.maintenance.ai.urlopen")
    def test_provider_manual_request_preserves_report(self, urlopen):
        report = self.submit("Elevator shakes")
        urlopen.return_value = FakeResponse(
            {
                "category": "Elevator",
                "interpreted_location": "Building B / Lift 2",
                "urgency": "HIGH",
                "confidence_percent": 87,
                "requires_manual_review": True,
                "duplicate_report_ids": [],
                "department": "Maintenance",
                "deadline_minutes": 240,
                "provider_request_id": "req-123",
            }
        )

        job = process_triage_job(report.triage_job.id)

        self.assertEqual(job.status, TriageJob.Status.NEEDS_MANUAL)
        self.assertTrue(IssueReport.objects.filter(pk=report.pk).exists())
        self.assertIsNotNone(job.completed_at)

    def test_duplicate_candidates_are_limited_to_five(self):
        report = self.submit("Elevator shakes")
        for index in range(6):
            self.submit(f"Elevator shakes on floor {index}")

        candidates = list(find_duplicate_candidates(report))

        self.assertEqual(len(candidates), 5)
        self.assertTrue(all(candidate.similarity >= 0.2 for candidate in candidates))
