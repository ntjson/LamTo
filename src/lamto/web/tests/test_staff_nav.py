import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.capabilities import FUND_RECORD, PAYMENT_VERIFY, PROPOSAL_APPROVE
from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.accounts.services import grant_capability
from lamto.web.staff import nav_items_for


class NavStructureTests(TestCase):
    def _board(self, *caps):
        building = Building.objects.create(name="Nav B")
        org = Organization.objects.create(
            building=building, name="Board", kind=Organization.Kind.BOARD
        )
        user = get_user_model().objects.create_user(
            email="b@example.test", password="secret", display_name="B"
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=org, role=OrganizationMembership.Role.BOARD
        )
        for c in caps:
            grant_capability(membership, c)
        return membership

    def test_finance_area_appears_once_for_finance_capabilities(self):
        membership = self._board(PROPOSAL_APPROVE, PAYMENT_VERIFY, FUND_RECORD)
        labels = [i["label"] for i in nav_items_for(membership)]
        self.assertEqual(labels.count("Finance"), 1)
        self.assertNotIn("Proposals", labels)
        self.assertNotIn("Payments", labels)
        self.assertIn("Inbox", labels)

    def test_finance_lands_on_fund_when_only_fund_capability(self):
        membership = self._board(FUND_RECORD)
        finance = [i for i in nav_items_for(membership) if i["label"] == "Finance"]
        self.assertEqual(finance[0]["url_name"], "web:fund-home")

    def test_ledger_area_not_present_phase0(self):
        """Six active areas only; Ledger is deferred (no nav entry)."""
        membership = self._board(PROPOSAL_APPROVE, PAYMENT_VERIFY, FUND_RECORD)
        labels = [i["label"] for i in nav_items_for(membership)]
        self.assertNotIn("Ledger", labels)
        for label in ("Inbox", "Finance"):
            self.assertIn(label, labels)


@override_settings(ROOT_URLCONF="lamto.config.urls")
class SwitchReturnsToInboxTests(TestCase):
    def test_switch_redirects_to_inbox(self):
        building = Building.objects.create(name="Switch B")
        org = Organization.objects.create(
            building=building, name="Ops", kind=Organization.Kind.OPERATOR
        )
        user = get_user_model().objects.create_user(
            email="s@example.test", password="secret", display_name="S"
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=org, role=OrganizationMembership.Role.OPERATOR
        )
        self.client.force_login(user)
        device = TOTPDevice.objects.create(user=user, name="t", confirmed=True, key=random_hex())
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        resp = self.client.post(
            reverse("web:switch-membership"),
            {"membership": membership.pk, "next": "/s/cases/"},
        )
        self.assertRedirects(resp, reverse("web:action-inbox"), target_status_code=200)
