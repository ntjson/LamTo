import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.capabilities import (
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    PROPOSAL_APPROVE,
    REPORT_TRIAGE,
)
from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    Unit,
)
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.accounts.services import grant_capability
from lamto.finance.models import AcceptanceRecord, PaymentEvidence, Proposal
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    WorkOrder,
)


@override_settings(ROOT_URLCONF="lamto.config.urls")
class ListPatternTests(TestCase):
    def _login(self, user, membership):
        self.client.force_login(user)
        device = TOTPDevice.objects.create(
            user=user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()

    def _make_work(self, building, case, assignee, status):
        return WorkOrder.objects.create(
            case=case,
            assignee=assignee,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=status,
        )

    def _case_world(self, *, email_prefix="lp", role=OrganizationMembership.Role.MAINTENANCE, org_kind=Organization.Kind.OPERATOR):
        building = Building.objects.create(name=f"List {email_prefix}")
        location = BuildingLocation.objects.create(
            building=building, name="Lobby", active=True
        )
        org = Organization.objects.create(
            building=building, name="Org", kind=org_kind
        )
        user = get_user_model().objects.create_user(
            email=f"{email_prefix}@example.test", password="secret", display_name="U"
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=org, role=role
        )
        unit = Unit.objects.create(building=building, label="A-1")
        resident = get_user_model().objects.create_user(
            email=f"{email_prefix}-r@example.test", password="secret", display_name="R"
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text="x",
            selected_location=location,
            location_path_snapshot="x",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=user,
            category="c",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_minutes=60,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="c",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        return building, location, user, membership, case

    def test_work_list_renders_status_chip_and_filters(self):
        building, _loc, user, membership, case = self._case_world(email_prefix="work")
        self._make_work(building, case, user, WorkOrder.Status.ASSIGNED)
        # Not a WorkOrder.Status member — only appears in list status chips, not filter bar.
        self._make_work(building, case, user, "COMPLETED")

        self._login(user, membership)

        resp = self.client.get(reverse("web:work-order-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "status-chip")
        self.assertContains(resp, "filter-bar")

        filtered = self.client.get(reverse("web:work-order-list"), {"status": "ASSIGNED"})
        self.assertContains(filtered, "ASSIGNED")
        self.assertNotContains(filtered, "COMPLETED")

    def test_case_list_filters_active_cases_by_urgency(self):
        building, location, user, membership, high_case = self._case_world(
            email_prefix="cases",
            role=OrganizationMembership.Role.OPERATOR,
        )
        grant_capability(membership, REPORT_TRIAGE)
        # Second case with LOW urgency (needs its own decision for OneToOne).
        unit2 = Unit.objects.create(building=building, label="B-2")
        resident2 = get_user_model().objects.create_user(
            email="cases-r2@example.test", password="secret", display_name="R2"
        )
        report2 = IssueReport.objects.create(
            reporter=resident2,
            unit=unit2,
            text="low",
            selected_location=location,
            location_path_snapshot="low",
        )
        decision2 = TriageDecision.objects.create(
            report=report2,
            operator=user,
            category="c",
            urgency="LOW",
            location=location,
            department="Ops",
            deadline_minutes=60,
            differences={},
        )
        low_case = MaintenanceCase.objects.create(
            decision=decision2,
            building=building,
            category="c",
            urgency="LOW",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        self._login(user, membership)

        all_resp = self.client.get(reverse("web:case-list"))
        self.assertEqual(all_resp.status_code, 200)
        self.assertContains(all_resp, "filter-bar")
        self.assertContains(all_resp, f"Case #{high_case.pk}")
        self.assertContains(all_resp, f"Case #{low_case.pk}")

        filtered = self.client.get(reverse("web:case-list"), {"status": "HIGH"})
        self.assertContains(filtered, f"Case #{high_case.pk}")
        self.assertNotContains(filtered, f"Case #{low_case.pk}")

        cleared = self.client.get(reverse("web:case-list"))
        self.assertContains(cleared, f"Case #{low_case.pk}")

    def test_proposal_list_filters_by_status(self):
        building, _loc, user, membership, case = self._case_world(
            email_prefix="prop",
            role=OrganizationMembership.Role.BOARD,
            org_kind=Organization.Kind.BOARD,
        )
        grant_capability(membership, PROPOSAL_APPROVE)
        work = self._make_work(building, case, user, WorkOrder.Status.ASSIGNED)
        draft = Proposal.objects.create(
            work_order=work,
            creator_membership=membership,
            mode=Proposal.Mode.NORMAL,
            status=Proposal.Status.DRAFT,
        )
        # Second work order + proposal in review
        work2 = WorkOrder.objects.create(
            case=case,
            assignee=user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.ASSIGNED,
        )
        in_review = Proposal.objects.create(
            work_order=work2,
            creator_membership=membership,
            mode=Proposal.Mode.NORMAL,
            status=Proposal.Status.IN_REVIEW,
        )
        self._login(user, membership)

        all_resp = self.client.get(reverse("web:proposal-list"))
        self.assertEqual(all_resp.status_code, 200)
        self.assertContains(all_resp, "filter-bar")
        self.assertContains(all_resp, f"Proposal #{draft.pk}")
        self.assertContains(all_resp, f"Proposal #{in_review.pk}")

        filtered = self.client.get(
            reverse("web:proposal-list"), {"status": Proposal.Status.DRAFT}
        )
        self.assertContains(filtered, f"Proposal #{draft.pk}")
        self.assertNotContains(filtered, f"Proposal #{in_review.pk}")

    def test_payment_list_filters_verify_queue_by_external_status(self):
        """Filter chips on payment list narrow verify-queue by external_status."""
        import tempfile
        from unittest.mock import patch

        from django.test import override_settings

        from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

        temp = tempfile.mkdtemp(prefix="lamto-payfilt-")
        with override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": temp},
                },
                "private": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": temp},
                },
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
        ):
            seed = seed_pilot_world(building_name="Pay Filt", email_prefix="payf")
            d = PilotDomainDriver(seed)
            d.login(None, "resident").submit_report("x", "Lift")
            d.login(None, "operator").confirm_triage_and_create_paid_work_order()
            d.login(None, "operator").submit_signed_proposal()
            d.login(None, "board_approver").approve_proposal()
            d.login(None, "resident_representative").coapprove_proposal()
            d.login(None, "maintenance").complete_assigned_work()
            d.login(None, "board_payment_recorder").accept_and_record_payment()
            d.confirm_all_chain_events()
            payment = seed.proposal.work_order.acceptance.payment
            self.assertEqual(
                payment.external_status, PaymentEvidence.ExternalStatus.COMPLETED
            )

            membership = seed.roles["board_payment_verifier"]
            self._login(membership.user, membership)

            all_resp = self.client.get(reverse("web:payment-list"))
            self.assertEqual(all_resp.status_code, 200)
            self.assertContains(all_resp, "filter-bar")
            self.assertContains(all_resp, f"Payment #{payment.pk}")

            filtered = self.client.get(
                reverse("web:payment-list"),
                {"status": PaymentEvidence.ExternalStatus.FAILED},
            )
            self.assertNotContains(filtered, f"Payment #{payment.pk}")

            filtered_ok = self.client.get(
                reverse("web:payment-list"),
                {"status": PaymentEvidence.ExternalStatus.COMPLETED},
            )
            self.assertContains(filtered_ok, f"Payment #{payment.pk}")
