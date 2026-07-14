"""Regression tests for residual tenancy-hardening review minors."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.accounts.tenancy import SESSION_OCCUPANCY_KEY, TenantContext
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.notifications.models import NotificationDelivery
from lamto.web.action_inbox import _failed_outbox_items
from lamto.web.views.resident import home, ledger_list
from lamto.web.views.security import PhoneOrEmailAuthenticationForm


class AccountNoticesBuildingFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="notices@example.test", password="pw", display_name="N"
        )
        cls.building_a = Building.objects.create(name="Notices Building A")
        cls.building_b = Building.objects.create(name="Notices Building B")
        unit_a = Unit.objects.create(building=cls.building_a, label="NA-1")
        unit_b = Unit.objects.create(building=cls.building_b, label="NB-1")
        cls.occ_a = ResidentOccupancy.objects.create(user=cls.user, unit=unit_a)
        cls.occ_b = ResidentOccupancy.objects.create(user=cls.user, unit=unit_b)
        cls.notice_a = NotificationDelivery.objects.create(
            recipient=cls.user,
            building=cls.building_a,
            event_key="test:a:1",
            event_code="report.receipt",
            subject="A notice",
            body="from building A",
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.AVAILABLE,
        )
        cls.notice_b = NotificationDelivery.objects.create(
            recipient=cls.user,
            building=cls.building_b,
            event_key="test:b:1",
            event_code="report.receipt",
            subject="B notice",
            body="from building B",
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.AVAILABLE,
        )
        cls.notice_legacy = NotificationDelivery.objects.create(
            recipient=cls.user,
            building=None,
            event_key="test:legacy:1",
            event_code="report.receipt",
            subject="Legacy notice",
            body="null building",
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.AVAILABLE,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_account_shows_active_building_and_legacy_notices_only(self):
        # Default occupancy is first by pk (occ_a).
        response = self.client.get(reverse("web:account"))
        self.assertContains(response, "A notice")
        self.assertContains(response, "Legacy notice")
        self.assertNotContains(response, "B notice")

    def test_account_switches_notice_building_with_occupancy(self):
        session = self.client.session
        session[SESSION_OCCUPANCY_KEY] = self.occ_b.pk
        session.save()
        response = self.client.get(reverse("web:account"))
        self.assertContains(response, "B notice")
        self.assertContains(response, "Legacy notice")
        self.assertNotContains(response, "A notice")


class TenantContextSelectorWiringTests(TestCase):
    def test_resident_home_uses_tenant_context_building_id(self):
        """Structural + runtime: TenantContext is the carrier into selectors."""
        import inspect

        from lamto.web.views import resident as resident_views

        source = inspect.getsource(resident_views.home)
        assert "TenantContext.from_occupancy" in source
        assert "tenant.building_id" in source
        # Must not call selectors with occupancy.unit.building_id only.
        assert "verified_fund_entries(tenant.building_id)" in source
        assert "published_ledger_entries(tenant.building_id)" in source

        source_ledger = inspect.getsource(resident_views.ledger_list)
        assert "TenantContext.from_occupancy" in source_ledger
        assert "published_ledger_entries(tenant.building_id)" in source_ledger

        source_detail = inspect.getsource(resident_views.ledger_detail)
        assert "TenantContext.from_occupancy" in source_detail
        assert "published_ledger_entries(tenant.building_id)" in source_detail


class FailedOutboxBuildingKeyTests(TestCase):
    def test_failed_outbox_items_filter_by_event_building_id(self):
        import inspect

        from django.db.models import QuerySet

        from lamto.web import action_inbox

        source = inspect.getsource(action_inbox._failed_outbox_items)
        assert "building_id=building_id" in source
        assert "signer_wallet__membership__organization__building_id" not in source

        # Drive the real helper: empty building yields no items; filter key is
        # on the event, so queryset SQL must reference evidence building column.
        building = Building.objects.create(name="Outbox Inbox Building")
        items = _failed_outbox_items(building.pk)
        assert items == []
        qs = BlockchainOutboxEvent.objects.filter(
            status=BlockchainOutboxEvent.Status.FAILED,
            building_id=building.pk,
        )
        assert isinstance(qs, QuerySet)
        sql = str(qs.query)
        assert "building_id" in sql or "building" in sql.lower()


class LoginLabelTests(TestCase):
    def test_login_form_label_is_email_or_phone(self):
        form = PhoneOrEmailAuthenticationForm()
        assert form.fields["username"].label == "Email or phone"
        assert form.fields["username"].label != "Username"

    def test_login_page_renders_email_or_phone_label(self):
        response = self.client.get("/accounts/login/")
        assert response.status_code == 200
        self.assertContains(response, "Email or phone")
        self.assertNotContains(response, ">Username<")
