"""Read selectors for resident-owned maintenance records (spec 2.3, layer 2)."""

from lamto.maintenance.models import (
    BuildingLocation,
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


def resident_report_timeline(report):
    """Ownership timeline for one report (spec 3.3): triage -> case -> work -> acceptance."""
    triage_job = getattr(report, "triage_job", None)
    decision = getattr(report, "triage_decision", None)
    rated_ids = set(
        CompletionRating.objects.filter(resident_id=report.reporter_id).values_list(
            "work_order_id", flat=True
        )
    )
    cases = []
    for link in CaseReport.objects.filter(report=report).select_related("case").order_by(
        "case_id"
    ):
        case = link.case
        work_orders = []
        for wo in case.work_orders.select_related("acceptance").order_by("pk"):
            acceptance = getattr(wo, "acceptance", None)
            work_orders.append(
                {
                    "id": wo.pk,
                    "status": wo.status,
                    "deadline_at": wo.deadline_at,
                    "completed_at": wo.completed_at,
                    "accepted_at": getattr(acceptance, "accepted_at", None),
                    "can_rate": wo.status in ELIGIBLE_STATUSES and wo.pk not in rated_ids,
                }
            )
        cases.append(
            {
                "id": case.pk,
                "category": case.category,
                "urgency": case.urgency,
                "deadline_at": case.deadline_at,
                "active": case.active,
                "work_orders": work_orders,
            }
        )
    info = report.info_requests.filter(resolved_at__isnull=True).first()
    return {
        "id": report.pk,
        "text": report.text,
        "status": report.status,
        "declined_reason": report.declined_reason or None,
        "is_private": report.is_private,
        "open_info_request": (
            {"id": info.pk, "message": info.message, "created_at": info.created_at}
            if info else None
        ),
        "location_path_snapshot": report.location_path_snapshot,
        "unit_label": report.unit.label,
        "created_at": report.created_at,
        "triage_status": triage_job.status if triage_job is not None else None,
        "category": decision.category if decision is not None else None,
        "photos": [
            {
                "id": rp.version.pk,
                "filename": rp.version.filename,
                "sha256": rp.version.sha256,
            }
            for rp in report.photos.select_related("version").order_by("pk")
        ],
        "cases": cases,
    }


def active_location_tree(building_id):
    """Active locations for one building, ordered so parents precede siblings (spec 3.3)."""
    return (
        BuildingLocation.objects.filter(building_id=building_id, active=True)
        .order_by("parent_id", "name", "pk")
    )
