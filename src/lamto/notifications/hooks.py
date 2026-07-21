"""Domain-side notification fan-out helpers (safe after commit)."""

from __future__ import annotations

from lamto.notifications.services import (
    EVENT_CASE_STATUS,
    EVENT_DEADLINE_RISK,
    EVENT_INTEGRITY_MISMATCH,
    EVENT_PAYMENT_RECORDED,
    EVENT_PAYMENT_REJECTED,
    EVENT_PAYMENT_VERIFIED,
    EVENT_PUBLICATION,
    EVENT_QUARANTINED_UPLOAD,
    EVENT_REPORT_RECEIPT,
    EVENT_TRIAGE_STATUS,
    EVENT_WORK_ACCEPTED,
    EVENT_WORK_ASSIGNED,
    EVENT_WORK_COMPLETED,
    notify_users,
)


def _management_users(building_id: int):
    from lamto.accounts.models import ManagementMembership

    return [
        membership.user
        for membership in ManagementMembership.objects.select_related("user").filter(
            building_id=building_id, active=True
        )
    ]


def notify_report_receipt(report):
    building_id = report.unit.building_id
    recipients = [report.reporter] + _management_users(building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_REPORT_RECEIPT}:report:{report.pk}",
        subject="Report received",
        body=f"Report #{report.pk} was submitted: {report.text[:200]}",
        event_code=EVENT_REPORT_RECEIPT,
        building=building_id,
    )


def notify_triage_confirmed(case, report):
    recipients = [report.reporter] + _management_users(case.building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_TRIAGE_STATUS}:case:{case.pk}",
        subject="Triage confirmed",
        body=f"Case #{case.pk} opened for report #{report.pk} ({case.category}).",
        event_code=EVENT_TRIAGE_STATUS,
        building=case.building_id,
    )


def notify_work_assigned(work_order):
    recipients = [work_order.assignee] + _management_users(work_order.case.building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_WORK_ASSIGNED}:work:{work_order.pk}",
        subject="Work assigned",
        body=f"Work order #{work_order.pk} assigned (deadline {work_order.deadline_at}).",
        event_code=EVENT_WORK_ASSIGNED,
        building=work_order.case.building_id,
    )


def notify_deadline_risk(work_order):
    recipients = [work_order.assignee] + _management_users(work_order.case.building_id)
    # Idempotent per work order + calendar day so re-queue is safe within a day
    # but can re-alert on later days if still at risk.
    day = work_order.deadline_at.date().isoformat() if work_order.deadline_at else "unknown"
    notify_users(
        recipients,
        event_key=f"{EVENT_DEADLINE_RISK}:work:{work_order.pk}:day:{day}",
        subject="Deadline risk",
        body=f"Work order #{work_order.pk} approaches deadline {work_order.deadline_at}.",
        event_code=EVENT_DEADLINE_RISK,
        building=work_order.case.building_id,
    )


def notify_work_accepted(record):
    building_id = record.work_order.case.building_id
    recipients = [record.work_order.assignee] + _management_users(building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_WORK_ACCEPTED}:acceptance:{record.pk}",
        subject="Work accepted",
        body=f"Work order #{record.work_order_id} accepted at {record.actual_cost_vnd} VND.",
        event_code=EVENT_WORK_ACCEPTED,
        building=building_id,
    )


def notify_work_rateable(record):
    """Prompt the reporting residents to rate completed work (spec 7.4)."""
    from lamto.maintenance.models import CaseReport

    work_order = record.work_order
    building_id = work_order.case.building_id
    residents = [
        link.report.reporter
        for link in CaseReport.objects.filter(case=work_order.case).select_related("report__reporter")
    ]
    notify_users(
        residents,
        event_key=f"{EVENT_WORK_COMPLETED}:work:{work_order.pk}",
        subject="Work completed",
        body=f"Work order #{work_order.pk} is complete — please rate it.",
        event_code=EVENT_WORK_COMPLETED,
        building=building_id,
    )


def notify_payment_recorded(payment):
    building_id = payment.acceptance.work_order.case.building_id
    recipients = _management_users(building_id) + [
        payment.recorder.user
    ]
    notify_users(
        recipients,
        event_key=f"{EVENT_PAYMENT_RECORDED}:payment:{payment.pk}",
        subject="Payment recorded",
        body=f"Payment #{payment.pk} for {payment.amount_vnd} VND awaiting verification.",
        event_code=EVENT_PAYMENT_RECORDED,
        building=building_id,
    )


def notify_payment_verified(verification):
    payment = verification.payment
    building_id = payment.acceptance.work_order.case.building_id
    if verification.decision == "VERIFIED":
        code = EVENT_PAYMENT_VERIFIED
        subject = "Payment verified"
    else:
        code = EVENT_PAYMENT_REJECTED
        subject = "Payment rejected"
    recipients = [payment.recorder.user] + _management_users(building_id)
    notify_users(
        recipients,
        event_key=f"{code}:verification:{verification.pk}",
        subject=subject,
        body=f"Payment #{payment.pk} {verification.decision}.",
        event_code=code,
        building=building_id,
    )


def notify_publication(entry):
    building_id = entry.case.building_id
    # Residents and management in the building.
    from lamto.accounts.models import ResidentOccupancy

    residents = [
        o.user
        for o in ResidentOccupancy.objects.filter(
            unit__building_id=building_id, active=True
        ).select_related("user")
    ]
    recipients = residents + _management_users(building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_PUBLICATION}:entry:{entry.pk}",
        subject="Ledger publication",
        body=f"Spending of {entry.actual_cost_vnd} VND published to the resident ledger.",
        event_code=EVENT_PUBLICATION,
        building=building_id,
    )


def notify_integrity_mismatch(entry, observation):
    building_id = entry.case.building_id
    recipients = _management_users(building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_INTEGRITY_MISMATCH}:entry:{entry.pk}:obs:{observation.pk}",
        subject="Integrity mismatch detected",
        body=f"Published ledger entry #{entry.pk} failed integrity verification.",
        event_code=EVENT_INTEGRITY_MISMATCH,
        building=building_id,
    )


def notify_quarantined_upload(upload, building_id=None):
    building_id = building_id or upload.building_id
    recipients = [upload.uploader] + _management_users(building_id)
    notify_users(
        recipients,
        event_key=f"{EVENT_QUARANTINED_UPLOAD}:upload:{upload.pk}",
        subject="Upload quarantined",
        body=f"File {upload.filename} was quarantined: {upload.reason}",
        event_code=EVENT_QUARANTINED_UPLOAD,
        building=building_id,
    )
