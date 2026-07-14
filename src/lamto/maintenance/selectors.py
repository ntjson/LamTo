"""Read selectors for resident-owned maintenance records (spec 2.3, layer 2)."""

from lamto.maintenance.models import (
    CaseReport,
    CompletionRating,
    IssueReport,
    WorkOrder,
)
from lamto.maintenance.ratings import ELIGIBLE_STATUSES


def resident_reports(user):
    """Reports the user submitted, newest first (ownership scope)."""
    return (
        IssueReport.objects.filter(reporter=user)
        .select_related("unit", "selected_location")
        .order_by("-created_at", "-pk")
    )


def rateable_work_orders(user, report):
    """Completed work on the report's cases the user has not rated yet."""
    case_ids = CaseReport.objects.filter(report=report).values_list("case_id", flat=True)
    rated = CompletionRating.objects.filter(resident=user).values_list(
        "work_order_id", flat=True
    )
    return WorkOrder.objects.filter(
        case_id__in=case_ids,
        status__in=ELIGIBLE_STATUSES,
    ).exclude(pk__in=rated)
