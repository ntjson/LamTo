from django.core.management.base import BaseCommand
from django.utils import timezone

from lamto.finance.emergencies import mark_overdue_ratifications


class Command(BaseCommand):
    help = "Append overdue emergency ratification outcomes."

    def handle(self, *args, **options):
        self.stdout.write(str(mark_overdue_ratifications(timezone.now())))
