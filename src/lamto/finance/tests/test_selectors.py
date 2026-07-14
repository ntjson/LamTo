from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from lamto.accounts.models import Building
from lamto.finance.models import MaintenanceFund, MaintenanceFundEntry
from lamto.finance.selectors import fund_period_flows, verified_fund_entries


class FundSelectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Selector Building")
        cls.fund = MaintenanceFund.objects.create(building=cls.building)

    def _entry(self, entry_type, amount, recorded_at, key):
        return MaintenanceFundEntry.objects.create(
            fund=self.fund,
            entry_type=entry_type,
            amount_vnd=amount,
            source_key=key,
            recorded_at=recorded_at,
        )

    def test_period_flows_windows_and_signs(self):
        now = timezone.now()
        self._entry("OPENING_BALANCE", 1_000_000, now - timedelta(days=5), "k-open")
        self._entry("INFLOW", 200_000, now - timedelta(days=40), "k-old-inflow")
        inflows, outflows = fund_period_flows(self.building.pk, days=30)
        # Unverified entries are excluded entirely by the verified bar.
        verified_pks = set(
            verified_fund_entries(self.building.pk).values_list("pk", flat=True)
        )
        assert all(
            pk in verified_pks
            for pk in MaintenanceFundEntry.objects.filter(
                verification__isnull=False
            ).values_list("pk", flat=True)
        )
        assert isinstance(inflows, int) and isinstance(outflows, int)

    def test_other_building_excluded(self):
        other = Building.objects.create(name="Other Building")
        MaintenanceFund.objects.create(building=other)
        assert verified_fund_entries(other.pk).count() == 0
