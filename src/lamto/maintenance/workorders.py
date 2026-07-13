from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.capabilities import WORK_ASSIGN
from lamto.accounts.models import OrganizationMembership
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion

from .models import MaintenanceCase, WorkOrder, WorkUpdate, WorkUpdateEvidence


def _operator_membership(operator, building_id):
    membership = (
        OrganizationMembership.objects.select_related("organization")
        .filter(
            user=operator,
            active=True,
            organization__building_id=building_id,
            capabilitygrant__code=WORK_ASSIGN,
        )
        .first()
    )
    if membership is None:
        raise PermissionDenied(WORK_ASSIGN)
    return require_capability(operator, membership.pk, WORK_ASSIGN)


def _maintenance_membership(user, building_id):
    membership = (
        OrganizationMembership.objects.select_related("organization")
        .filter(
            user=user,
            active=True,
            role=OrganizationMembership.Role.MAINTENANCE,
            organization__building_id=building_id,
        )
        .first()
    )
    if membership is None:
        raise PermissionDenied("Active maintenance assignment is required.")
    return membership


def _evidence_versions(versions, kind, building_id, uploader):
    versions = list(versions)
    ids = [getattr(version, "pk", None) for version in versions]
    if not ids or None in ids or len(ids) != len(set(ids)):
        raise ValidationError("Completion requires distinct evidence versions.")
    valid = list(
        DocumentVersion.objects.select_for_update()
        .select_related("document")
        .filter(
            pk__in=ids,
            document__building_id=building_id,
            document__kind=kind,
            variant=DocumentVersion.Variant.ORIGINAL,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
            uploader=uploader,
        )
    )
    if len(valid) != len(ids) or any(not version.content_type.lower().startswith("image/") for version in valid):
        raise ValidationError("Completion evidence must be clean original images from the work-order building.")
    return valid


@transaction.atomic
def create_work_order(case, operator, assignee, requires_spending):
    case = MaintenanceCase.objects.select_for_update().filter(pk=getattr(case, "pk", None), active=True).first()
    if case is None:
        raise ValidationError("An active case is required.")
    membership = _operator_membership(operator, case.building_id)
    _maintenance_membership(assignee, case.building_id)
    if type(requires_spending) is not bool:
        raise ValidationError("requires_spending must be a boolean.")
    work_order = WorkOrder.objects.create(
        case=case,
        assignee=assignee,
        priority=case.urgency,
        deadline_at=case.deadline_at,
        requires_spending=requires_spending,
        authorization_status=(
            WorkOrder.AuthorizationStatus.PENDING
            if requires_spending
            else WorkOrder.AuthorizationStatus.NOT_REQUIRED
        ),
    )
    record_audit(
        actor=operator,
        membership=membership,
        action="work.create",
        target_type="WorkOrder",
        target_id=str(work_order.pk),
        result="accepted",
        metadata={"case_id": case.pk, "assignee_id": assignee.pk, "requires_spending": requires_spending},
    )
    return work_order


@transaction.atomic
def start_work_order(work_order, maintenance_user):
    work_order = (
        WorkOrder.objects.select_for_update()
        .select_related("case")
        .filter(pk=getattr(work_order, "pk", None))
        .first()
    )
    if work_order is None or work_order.assignee_id != getattr(maintenance_user, "pk", None):
        raise PermissionDenied("Only the assigned maintenance user may start this work order.")
    membership = _maintenance_membership(maintenance_user, work_order.case.building_id)
    if work_order.authorization_status == WorkOrder.AuthorizationStatus.PENDING:
        raise PermissionDenied("Work spending authorization is pending.")
    if work_order.authorization_status not in {
        WorkOrder.AuthorizationStatus.NOT_REQUIRED,
        WorkOrder.AuthorizationStatus.AUTHORIZED,
    } or work_order.status != WorkOrder.Status.ASSIGNED:
        raise ValidationError("Work order cannot be started.")
    work_order.status = WorkOrder.Status.IN_PROGRESS
    work_order.started_at = timezone.now()
    work_order.save(update_fields=["status", "started_at"])
    record_audit(
        actor=maintenance_user,
        membership=membership,
        action="work.start",
        target_type="WorkOrder",
        target_id=str(work_order.pk),
        result="accepted",
    )
    return work_order


@transaction.atomic
def complete_work_order(work_order, maintenance_user, cause, result, before_versions, after_versions):
    work_order = (
        WorkOrder.objects.select_for_update()
        .select_related("case")
        .filter(pk=getattr(work_order, "pk", None))
        .first()
    )
    if work_order is None or work_order.assignee_id != getattr(maintenance_user, "pk", None):
        raise PermissionDenied("Only the assigned maintenance user may complete this work order.")
    membership = _maintenance_membership(maintenance_user, work_order.case.building_id)
    if work_order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError("Work order is not in progress.")
    if not isinstance(cause, str) or not (cause := cause.strip()):
        raise ValidationError("Completion cause is required.")
    if not isinstance(result, str) or not (result := result.strip()):
        raise ValidationError("Completion result is required.")
    before = _evidence_versions(before_versions, Document.Kind.BEFORE_PHOTO, work_order.case.building_id, maintenance_user)
    after = _evidence_versions(after_versions, Document.Kind.AFTER_PHOTO, work_order.case.building_id, maintenance_user)
    update = WorkUpdate.objects.create(work_order=work_order, cause=cause, result=result)
    WorkUpdateEvidence.objects.bulk_create(
        [
            *[WorkUpdateEvidence(update=update, version=version, kind=WorkUpdateEvidence.Kind.BEFORE) for version in before],
            *[WorkUpdateEvidence(update=update, version=version, kind=WorkUpdateEvidence.Kind.AFTER) for version in after],
        ]
    )
    work_order.status = WorkOrder.Status.AWAITING_ACCEPTANCE
    work_order.cause = cause
    work_order.result = result
    work_order.completed_at = timezone.now()
    work_order.save(update_fields=["status", "cause", "result", "completed_at"])
    record_audit(
        actor=maintenance_user,
        membership=membership,
        action="work.complete",
        target_type="WorkOrder",
        target_id=str(work_order.pk),
        result="accepted",
        metadata={"work_update_id": update.pk},
    )
    return work_order
