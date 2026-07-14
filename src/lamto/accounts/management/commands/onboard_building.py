"""Onboard a new building tenant (spec 2.5): building, organizations, fund,
locations, units. People-steps (memberships, capabilities, wallets, opening
balance) stay in the runbook — they need real humans and signed evidence.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from lamto.accounts.models import Building, Organization, Unit
from lamto.finance.models import MaintenanceFund
from lamto.maintenance.models import BuildingLocation

ORGANIZATION_KINDS = (
    (Organization.Kind.OPERATOR, "operator organization"),
    (Organization.Kind.BOARD, "management board"),
    (Organization.Kind.RESIDENT_REP, "resident representative body"),
    (Organization.Kind.AUDITOR, "auditor firm"),
    (Organization.Kind.PLATFORM, "platform provider"),
)


def _split(raw):
    return [part.strip() for part in raw.split(",") if part.strip()]


class Command(BaseCommand):
    help = "Create a building tenant with its organizations, fund, locations, and units."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Building display name.")
        parser.add_argument("--timezone", default="Asia/Ho_Chi_Minh")
        parser.add_argument("--locations", default="", help="Comma-separated root location names.")
        parser.add_argument("--units", default="", help="Comma-separated unit labels.")

    @transaction.atomic
    def handle(self, *args, **options):
        name = options["name"].strip()
        if not name:
            raise CommandError("--name is required.")
        if Building.objects.filter(name=name).exists():
            raise CommandError(f"Building {name!r} already exists.")
        building = Building.objects.create(name=name, timezone=options["timezone"])
        for kind, label in ORGANIZATION_KINDS:
            Organization.objects.create(
                building=building, name=f"{name} {label}", kind=kind
            )
        MaintenanceFund.objects.create(building=building)
        for location_name in _split(options["locations"]):
            BuildingLocation.objects.create(building=building, name=location_name)
        for unit_label in _split(options["units"]):
            Unit.objects.create(building=building, label=unit_label)

        self.stdout.write(self.style.SUCCESS(f"Building onboarded: {name} (id={building.pk})"))
        self.stdout.write(
            "Next steps (runbook): create staff users and memberships, grant "
            "capabilities, register signer wallets, add resident occupancies "
            "(set phone numbers for phone login), then record and verify the "
            "fund opening balance."
        )
