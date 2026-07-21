"""Assert cross-record building consistency (spec 2.3 layer 3).

Covers the edges composite FKs cannot express (multi-hop joins and columns
without a denormalized building), so a scoping bug shows up as a failing
check instead of silent cross-tenant data. Run in CI and nightly.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry
from lamto.maintenance.models import (
    CaseReport,
    IssueReport,
    MaintenanceCase,
    ReportPhoto,
    TriageDecision,
    WorkOrder,
)


def checks():
    return [
        ("issue_report_unit", IssueReport.objects.exclude(building=F("unit__building"))),
        (
            "issue_report_location",
            IssueReport.objects.exclude(building=F("selected_location__building")),
        ),
        (
            "triage_decision_location",
            TriageDecision.objects.exclude(
                location__building=F("report__unit__building")
            ),
        ),
        ("case_location", MaintenanceCase.objects.exclude(building=F("location__building"))),
        (
            "case_report",
            CaseReport.objects.exclude(case__building=F("report__unit__building")),
        ),
        (
            "work_order_decision_chain",
            WorkOrder.objects.exclude(
                case__building=F("case__decision__report__unit__building")
            ),
        ),
        (
            "fund_entry_proposal",
            MaintenanceFundEntry.objects.filter(proposal__isnull=False).exclude(
                fund__building=F("proposal__work_order__case__building")
            ),
        ),
        (
            "published_entry_case",
            PublishedLedgerEntry.objects.exclude(case=F("proposal__work_order__case")),
        ),
        (
            "outbox_signer_building",
            BlockchainOutboxEvent.objects.exclude(
                building=F("signer_wallet__membership__building")
            ),
        ),
        (
            "report_photo_document",
            ReportPhoto.objects.exclude(
                version__document__building=F("report__unit__building")
            ),
        ),
    ]


class Command(BaseCommand):
    help = "Fail when any cross-building reference is inconsistent."

    def handle(self, *args, **options):
        failures = []
        for name, queryset in checks():
            count = queryset.count()
            if count:
                sample = list(queryset.values_list("pk", flat=True)[:5])
                failures.append(f"{name}: {count} row(s), e.g. pks {sample}")
                self.stderr.write(self.style.ERROR(f"FAIL {name}: {count}"))
            else:
                self.stdout.write(f"ok {name}")
        if failures:
            raise CommandError("Tenant integrity violations:\n" + "\n".join(failures))
        self.stdout.write(self.style.SUCCESS("Tenant integrity: all checks passed."))
