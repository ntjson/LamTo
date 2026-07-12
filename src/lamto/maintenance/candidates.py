from django.contrib.postgres.search import TrigramSimilarity

from .models import IssueReport


def find_duplicate_candidates(report, limit=5):
    return (
        IssueReport.objects.filter(
            status=IssueReport.Status.OPEN, unit__building_id=report.unit.building_id
        )
        .exclude(pk=report.pk)
        .annotate(similarity=TrigramSimilarity("text", report.text))
        .filter(similarity__gte=0.2)
        .order_by("-similarity")[: max(0, min(limit, 5))]
    )
