"""Request-outcome services on the report/case pair."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.models import ResidentOccupancy
from lamto.accounts.services import require_management
from lamto.audit.services import record_audit

from .models import CaseReport, InfoRequest, IssueReport

TERMINAL_STATUSES = frozenset(
    {IssueReport.Status.DECLINED, IssueReport.Status.COMPLETED, IssueReport.Status.CLOSED}
)
RATING_WINDOW_DAYS = 14


def _locked_report(report):
    report = IssueReport.objects.select_for_update().select_related("unit").filter(
        pk=getattr(report, "pk", None)
    ).first()
    if report is None:
        raise ValidationError("Report is required.")
    return report


@transaction.atomic
def request_information(report, manager, message) -> InfoRequest:
    report = _locked_report(report)
    membership = require_management(manager, report.unit.building_id)
    if report.status in TERMINAL_STATUSES:
        raise ValidationError("Closed or declined requests cannot ask for information.")
    if not (message or "").strip():
        raise ValidationError("An information request needs a message.")
    if InfoRequest.objects.filter(report=report, resolved_at__isnull=True).exists():
        raise ValidationError("An information request is already open for this report.")
    info = InfoRequest.objects.create(report=report, message=message.strip(), created_by=manager)
    report.status = IssueReport.Status.NEEDS_INFO
    report.save(update_fields=["status"])
    record_audit(actor=manager, membership=membership, action="request.info_requested",
                 target_type="InfoRequest", target_id=str(info.pk), result="accepted",
                 metadata={"report_id": report.pk})
    try:
        from lamto.notifications.hooks import notify_info_requested
        notify_info_requested(info)
    except Exception:
        pass
    return info


@transaction.atomic
def reply_information(resident, report, text) -> InfoRequest:
    report = _locked_report(report)
    if report.reporter_id != getattr(resident, "pk", None):
        raise PermissionDenied("Only the reporter may reply to an information request.")
    info = InfoRequest.objects.select_for_update().filter(
        report=report, resolved_at__isnull=True
    ).first()
    if info is None:
        raise ValidationError("No open information request for this report.")
    if not (text or "").strip():
        raise ValidationError("A reply needs text (photos may be attached separately).")
    occupancy = ResidentOccupancy.objects.filter(
        user=resident, active=True, unit__building_id=report.unit.building_id
    ).first()
    if occupancy is None:
        raise PermissionDenied("Active occupancy in the building is required.")
    info.reply_text = text.strip()
    info.resolved_at = timezone.now()
    info.save(update_fields=["reply_text", "resolved_at"])
    report.status = IssueReport.Status.IN_REVIEW
    report.save(update_fields=["status"])
    record_audit(actor=resident, membership=None, action="request.info_replied",
                 target_type="InfoRequest", target_id=str(info.pk), result="accepted",
                 metadata={"report_id": report.pk, "occupancy_id": occupancy.pk})
    return info


@transaction.atomic
def decline_report(report, manager, reason) -> IssueReport:
    report = _locked_report(report)
    membership = require_management(manager, report.unit.building_id)
    if report.status in TERMINAL_STATUSES:
        raise ValidationError("This request is already closed.")
    if not (reason or "").strip():
        raise ValidationError("Declining a request requires a reason the resident can read.")
    now = timezone.now()
    report.status = IssueReport.Status.DECLINED
    report.declined_reason = reason.strip()
    report.declined_by = manager
    report.declined_at = now
    report.save(update_fields=["status", "declined_reason", "declined_by", "declined_at"])
    for link in CaseReport.objects.filter(report=report).select_related("case"):
        case = link.case
        if (case.active and not CaseReport.objects.filter(case=case).exclude(report=report)
                .exclude(report__status__in=TERMINAL_STATUSES).exists()):
            case.active = False
            case.closed_at = now
            case.save(update_fields=["active", "closed_at"])
    record_audit(actor=manager, membership=membership, action="request.declined",
                 target_type="IssueReport", target_id=str(report.pk), result="accepted",
                 metadata={"reason_length": len(report.declined_reason)})
    try:
        from lamto.notifications.hooks import notify_report_declined
        notify_report_declined(report)
    except Exception:
        pass
    return report
