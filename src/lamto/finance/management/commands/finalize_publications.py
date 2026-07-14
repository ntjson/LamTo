from django.core.management.base import BaseCommand

from lamto.evidence.models import SETTLED_STATUSES
from lamto.finance.models import PublicationSnapshot, PublishedLedgerEntry
from lamto.finance.publication import finalize_publication


class Command(BaseCommand):
    help = "Finalize settled publication snapshots into ledger and fund postings."

    def handle(self, *args, **options):
        pending = (
            PublicationSnapshot.objects.filter(
                outbox_event__status__in=SETTLED_STATUSES,
            )
            .exclude(pk__in=PublishedLedgerEntry.objects.values("snapshot_id"))
            .order_by("pk")
        )
        finalized = 0
        for snapshot in pending.iterator():
            finalize_publication(snapshot.pk)
            finalized += 1
        self.stdout.write(str(finalized))
