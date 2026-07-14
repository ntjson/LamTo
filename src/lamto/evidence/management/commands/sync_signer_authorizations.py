from django.core.management.base import BaseCommand

from lamto.evidence.worker import anchoring_disabled, sync_signer_authorizations


class Command(BaseCommand):
    help = "Synchronize pending signer wallet authorizations and revocations on-chain."

    def handle(self, *args, **options):
        if anchoring_disabled():
            self.stdout.write("anchoring backend disabled; signer sync skipped")
            return
        results = sync_signer_authorizations()
        confirmed = sum(1 for item in results if item.status == item.Status.CONFIRMED)
        self.stdout.write(
            f"synchronized {len(results)} authorization request(s); confirmed={confirmed}"
        )
        for item in results:
            self.stdout.write(
                f"  id={item.pk} action={item.action} status={item.status} "
                f"tx={item.transaction_hash or '-'}"
            )
