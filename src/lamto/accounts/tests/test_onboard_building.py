from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from lamto.accounts.models import Building, Organization, Unit
from lamto.finance.models import MaintenanceFund
from lamto.maintenance.models import BuildingLocation


class OnboardBuildingTests(TestCase):
    def test_creates_tenant_skeleton(self):
        out = StringIO()
        call_command(
            "onboard_building",
            "--name", "Onboard Tower",
            "--locations", "Lobby, Lift 1",
            "--units", "OT-101, OT-102",
            stdout=out,
        )
        building = Building.objects.get(name="Onboard Tower")
        assert building.timezone == "Asia/Ho_Chi_Minh"
        kinds = set(
            Organization.objects.filter(building=building).values_list("kind", flat=True)
        )
        assert kinds == {"OPERATOR", "BOARD", "RESIDENT_REP", "AUDITOR", "PLATFORM"}
        assert MaintenanceFund.objects.filter(building=building).exists()
        assert set(
            BuildingLocation.objects.filter(building=building).values_list("name", flat=True)
        ) == {"Lobby", "Lift 1"}
        assert set(
            Unit.objects.filter(building=building).values_list("label", flat=True)
        ) == {"OT-101", "OT-102"}
        assert "Next steps" in out.getvalue()

    def test_duplicate_name_rejected(self):
        Building.objects.create(name="Onboard Tower")
        with self.assertRaises(CommandError):
            call_command("onboard_building", "--name", "Onboard Tower")
