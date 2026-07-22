from django.core.management.base import BaseCommand
from lamto.gate.calibration import CalibrationScores, sweep

class Command(BaseCommand):
    help = "Print the calibrated gate threshold sweep."
    def handle(self, *args, **options):
        self.stdout.write("Use reader captures and score_pairs; no threshold is a production default.")
        for row in sweep(CalibrationScores(), .30, .60, .01):
            self.stdout.write(f"| {row.threshold:.2f} | {row.fmr:.4f} | {row.fnmr:.4f} |")
