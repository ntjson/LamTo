from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.audit.services import record_audit
from lamto.accounts.models import ResidentOccupancy

from .models import CaseReport, CompletionRating, WorkOrder


ELIGIBLE_STATUSES = frozenset(
    {
        WorkOrder.Status.ACCEPTED,
        WorkOrder.Status.CLOSED,
    }
)


@transaction.atomic
def rate_completed_work(resident, work_order, score, comment="") -> CompletionRating:
    work_order = (
        WorkOrder.objects.select_for_update()
        .select_related("case")
        .filter(pk=getattr(work_order, "pk", None))
        .first()
    )
    if work_order is None:
        raise ValidationError("Work order is required.")
    if work_order.status not in ELIGIBLE_STATUSES:
        raise ValidationError("Only accepted or closed work can be rated.")
    if type(score) is not int or score < 1 or score > 5:
        raise ValidationError("Rating score must be an integer from 1 to 5.")
    if comment is None:
        comment = ""
    if not isinstance(comment, str):
        raise ValidationError("Rating comment must be text.")
    comment = comment.strip()
    if len(comment) > 500:
        raise ValidationError("Rating comment must be at most 500 characters.")

    owns_report = CaseReport.objects.filter(
        case_id=work_order.case_id,
        report__reporter_id=getattr(resident, "pk", None),
    ).exists()
    if not owns_report:
        raise PermissionDenied("Only residents who reported this case may rate the work.")

    occupancy = ResidentOccupancy.objects.filter(
        user=resident, active=True, unit__building_id=work_order.case.building_id
    ).first()
    if occupancy is None:
        raise PermissionDenied("Active occupancy in the building is required to rate work.")

    if CompletionRating.objects.filter(resident=resident, work_order=work_order).exists():
        raise ValidationError("This work order has already been rated by this resident.")

    rating = CompletionRating.objects.create(
        resident=resident,
        work_order=work_order,
        score=score,
        comment=comment,
        created_at=timezone.now(),
    )
    record_audit(
        actor=resident,
        membership=None,
        action="work.rate",
        target_type="CompletionRating",
        target_id=str(rating.pk),
        result="accepted",
        metadata={"occupancy_id": occupancy.pk, "work_order_id": work_order.pk},
    )
    return rating
