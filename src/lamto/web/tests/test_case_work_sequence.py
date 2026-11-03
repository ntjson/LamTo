"""The case page offers work actions in the order the domain accepts them.

The page used to render Start work and the Publish progress form side by side
with nothing gating either, so a case could be completed in one click without
ever being started — and, because ``spending_proposal_cases()`` drops cases
whose reports have moved on, without any chance of ever proposing the spend.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from lamto.accounts.models import Building, ManagementMembership, Unit, User
from lamto.finance.models import Proposal, Settlement
from lamto.maintenance.cases import start_case_work
from lamto.maintenance.models import (
    BuildingLocation, CaseReport, IssueReport, MaintenanceCase, TriageDecision,
)
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world


class CaseWorkSequenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Sequence")
        cls.unit = Unit.objects.create(building=cls.building, label="A-1")
        cls.location = BuildingLocation.objects.create(building=cls.building, name="Lift")
        cls.manager = User.objects.create_user(email="seq-m@example.test", password="pw")
        cls.membership = ManagementMembership.objects.create(
            user=cls.manager, building=cls.building
        )

    def setUp(self):
        self.client.force_login(self.manager)
        session = self.client.session
        session["active_management_id"] = self.membership.pk
        session.save()

    def _case(self, suffix="a"):
        resident = User.objects.create_user(email=f"seq-{suffix}@example.test", password="pw")
        report = IssueReport.objects.create(
            reporter=resident, unit=self.unit, text="lift stuck",
            selected_location=self.location, location_path_snapshot="Sequence / Lift",
            status=IssueReport.Status.IN_REVIEW,
        )
        decision = TriageDecision.objects.create(
            report=report, operator=self.manager, category="Elevator", urgency="HIGH",
            location=self.location, management_queue="GENERAL", deadline_minutes=60,
        )
        case = MaintenanceCase.objects.create(
            decision=decision, building=self.building, category="Elevator", urgency="HIGH",
            location=self.location, management_queue="GENERAL",
            deadline_at=timezone.now() + timedelta(hours=1),
        )
        CaseReport.objects.create(case=case, report=report, grouped_by=self.manager)
        return case, report

    def _url(self, case):
        return reverse("web:case-detail", kwargs={"pk": case.pk})

    def test_unstarted_case_offers_start_work_only(self):
        case, _ = self._case("unstarted")
        body = self.client.get(self._url(case)).content.decode()
        self.assertIn('value="start_work"', body)
        self.assertNotIn('value="publish_progress"', body)
        self.assertNotIn('value="complete_work"', body)

    def test_started_case_offers_progress_and_completion(self):
        case, _ = self._case("started")
        start_case_work(case, self.manager)
        body = self.client.get(self._url(case)).content.decode()
        self.assertNotIn('value="start_work"', body)
        self.assertIn('value="publish_progress"', body)
        self.assertIn('value="complete_work"', body)

    def test_completing_an_unstarted_case_is_refused(self):
        case, report = self._case("posted")
        response = self.client.post(
            self._url(case),
            {"action": "complete_work", "cause": "worn cable", "result": "replaced"},
            follow=True,
        )
        case.refresh_from_db(); report.refresh_from_db()
        self.assertIsNone(case.completed_at)
        self.assertEqual(case.updates.count(), 0)
        self.assertEqual(report.status, IssueReport.Status.IN_REVIEW)
        self.assertContains(response, "Tạo đề xuất chi")

    def test_publishing_progress_on_an_unstarted_case_is_refused(self):
        case, _ = self._case("progress")
        self.client.post(
            self._url(case),
            {"action": "publish_progress", "cause": "looked", "result": "saw"},
            follow=True,
        )
        self.assertEqual(case.updates.count(), 0)


@override_settings(LANGUAGE_CODE="en", ROOT_URLCONF="lamto.config.urls")
class ProceedDecisionGatesWorkTests(TestCase):
    """With a published proposal, the Proceed decision is the only way work starts."""

    def setUp(self):
        self.seed = seed_pilot_world(building_name="Gate B", email_prefix="gate")
        self.driver = PilotDomainDriver(self.seed)
        self.driver.submit_report("Lift jerks", "Lift 2")
        self.driver.confirm_triage_case()
        self.driver.publish_proposal()
        self.case = self.seed.case
        self.proposal = self.seed.proposal
        membership = self.seed.management_memberships[0]
        self.client.force_login(membership.user)
        session = self.client.session
        session["active_management_id"] = membership.pk
        session.save()

    def _case_url(self):
        return reverse("web:case-detail", kwargs={"pk": self.case.pk})

    def _proposal_url(self):
        return reverse("web:proposal-detail", kwargs={"pk": self.proposal.pk})

    def _start_work(self):
        return self.client.post(self._case_url(), {"action": "start_work"})

    def _decide(self, decision, note="Because"):
        return self.client.post(
            self._proposal_url(), {"action": "decide", "decision": decision, "note": note}
        )

    def test_undecided_proposal_refuses_start_work_and_page_links_to_the_decision(self):
        page = self.client.get(self._case_url())
        self.assertNotContains(page, 'value="start_work"')
        self.assertContains(page, "needs a Proceed decision")
        self.assertContains(page, f'href="{self._proposal_url()}"')

        response = self._start_work()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "needs a Proceed decision")
        self.case.refresh_from_db()
        self.assertIsNone(self.case.started_at)

    def test_proceeding_starts_the_cases_work(self):
        self._decide("proceed")

        self.case.refresh_from_db(); self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.Status.IN_PROGRESS)
        self.assertIsNotNone(self.case.started_at)
        self.assertNotContains(self.client.get(self._case_url()), "needs a Proceed decision")

    def test_after_not_proceeding_work_can_start_without_spending(self):
        self._decide("decline")
        self.assertContains(self.client.get(self._case_url()), 'value="start_work"')

        self._start_work()

        self.case.refresh_from_db(); self.proposal.refresh_from_db()
        self.assertIsNotNone(self.case.started_at)
        self.assertEqual(self.proposal.status, Proposal.Status.NOT_PROCEEDING)

    def test_completing_after_not_proceeding_leaves_the_proposal_closed_and_unsettleable(self):
        self._decide("decline")
        self._start_work()
        self.client.post(
            self._case_url(),
            {"action": "complete_work", "cause": "worn cable", "result": "replaced"},
        )

        self.case.refresh_from_db(); self.proposal.refresh_from_db()
        self.assertIsNotNone(self.case.completed_at)
        self.assertEqual(self.proposal.status, Proposal.Status.NOT_PROCEEDING)
        self.assertIsNone(self.proposal.completed_at)
        with self.assertRaisesMessage(ValidationError, "Only completed proposals can be settled."):
            self.driver.record_settlement()
        self.assertFalse(Settlement.objects.filter(proposal=self.proposal).exists())

    def test_completing_a_proceeding_case_completes_its_proposal(self):
        self._decide("proceed")
        self.client.post(
            self._case_url(),
            {"action": "complete_work", "cause": "worn cable", "result": "replaced"},
        )

        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.Status.COMPLETED)
