"""Domain-side notification fan-out helpers (safe after commit)."""

from __future__ import annotations

from lamto.accounts.models import CapabilityGrant, OrganizationMembership
from lamto.notifications.services import (
    EVENT_CASE_STATUS,
    EVENT_DEADLINE_RISK,
    EVENT_EMERGENCY_DEADLINE,
    EVENT_EMERGENCY_OUTCOME,
    EVENT_INTEGRITY_MISMATCH,
    EVENT_PAYMENT_RECORDED,
    EVENT_PAYMENT_REJECTED,
    EVENT_PAYMENT_VERIFIED,
    EVENT_PROPOSAL_APPROVAL,
    EVENT_PROPOSAL_REJECTION,
    EVENT_PUBLICATION,
    EVENT_QUARANTINED_UPLOAD,
    EVENT_REPORT_RECEIPT,
    EVENT_TRIAGE_STATUS,
    EVENT_WORK_ACCEPTED,
    EVENT_WORK_ASSIGNED,
    EVENT_WORK_COMPLETED,
    notify_users,
)


def _users_with_capability(building_id: int, code: str):
    memberships = (
        OrganizationMembership.objects.filter(
            active=True,
            organization__building_id=building_id,
            capabilitygrant__code=code,
        )
        .select_related("user")
        .distinct()
    )
    return [m.user for m in memberships]


def _users_with_role(building_id: int, role: str):
    memberships = OrganizationMembership.objects.filter(
        active=True,
        organization__building_id=building_id,
        role=role,
    ).select_related("user")
    return [m.user for m in memberships]


def notify_report_receipt(report):
    building_id = report.unit.building_id
    recipients = [report.reporter] + _users_with_capability(building_id, "report.triage")
    notify_users(
        recipients,
        event_key=f"{EVENT_REPORT_RECEIPT}:report:{report.pk}",
        subject="Report received",
        body=f"Report #{report.pk} was submitted: {report.text[:200]}",
        event_code=EVENT_REPORT_RECEIPT,
        building=building_id,
    )


def notify_triage_confirmed(case, report):
    recipients = [report.reporter] + _users_with_capability(
        case.building_id, "report.triage"
    )
    notify_users(
        recipients,
        event_key=f"{EVENT_TRIAGE_STATUS}:case:{case.pk}",
        subject="Triage confirmed",
        body=f"Case #{case.pk} opened for report #{report.pk} ({case.category}).",
        event_code=EVENT_TRIAGE_STATUS,
        building=case.building_id,
    )


def notify_work_assigned(work_order):
    recipients = [work_order.assignee] + _users_with_capability(
        work_order.case.building_id, "work.assign"
    )
    notify_users(
        recipients,
        event_key=f"{EVENT_WORK_ASSIGNED}:work:{work_order.pk}",
        subject="Work assigned",
        body=f"Work order #{work_order.pk} assigned (deadline {work_order.deadline_at}).",
        event_code=EVENT_WORK_ASSIGNED,
        building=work_order.case.building_id,
    )


def notify_deadline_risk(work_order):
    recipients = [work_order.assignee] + _users_with_capability(
        work_order.case.building_id, "work.assign"
    )
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


def notify_proposal_decision(approval):
    version = approval.version
    proposal = version.proposal
    building_id = proposal.work_order.case.building_id
    code = (
        EVENT_PROPOSAL_APPROVAL
        if approval.decision == "APPROVE"
        else EVENT_PROPOSAL_REJECTION
    )
    recipients = (
        [proposal.creator_membership.user]
        + _users_with_capability(building_id, "proposal.approve")
        + _users_with_capability(building_id, "proposal.create")
    )
    notify_users(
        recipients,
        event_key=f"{code}:approval:{approval.pk}",
        subject="Proposal decision",
        body=f"Proposal #{proposal.pk} {approval.decision} at stage {approval.stage}.",
        event_code=code,
        building=building_id,
    )


def notify_emergency_authorized(authorization):
    building_id = authorization.work_order.case.building_id
    recipients = (
        _users_with_capability(building_id, "emergency.authorize")
        + _users_with_role(building_id, OrganizationMembership.Role.RESIDENT_REP)
        + _users_with_role(building_id, OrganizationMembership.Role.MAINTENANCE)
    )
    notify_users(
        recipients,
        event_key=f"{EVENT_EMERGENCY_DEADLINE}:auth:{authorization.pk}",
        subject="Emergency authorized — ratification deadline set",
        body=(
            f"Emergency on work order #{authorization.work_order_id} authorized. "
            f"Ratify by {authorization.ratification_deadline}."
        ),
        event_code=EVENT_EMERGENCY_DEADLINE,
        building=building_id,
    )


def notify_emergency_outcome(ratification):
    auth = ratification.authorization
    building_id = auth.work_order.case.building_id
    recipients = (
        _users_with_capability(building_id, "emergency.authorize")
        + _users_with_role(building_id, OrganizationMembership.Role.RESIDENT_REP)
        + _users_with_role(building_id, OrganizationMembership.Role.BOARD)
    )
    notify_users(
        recipients,
        event_key=f"{EVENT_EMERGENCY_OUTCOME}:ratification:{ratification.pk}",
        subject=f"Emergency outcome: {ratification.outcome}",
        body=f"Work order #{auth.work_order_id} emergency outcome {ratification.outcome}.",
        event_code=EVENT_EMERGENCY_OUTCOME,
        building=building_id,
    )


def notify_work_accepted(record):
    building_id = record.work_order.case.building_id
    recipients = (
        [record.work_order.assignee]
        + _users_with_capability(building_id, "work.accept")
        + _users_with_capability(building_id, "payment.record")
    )
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
    recipients = _users_with_capability(building_id, "payment.verify") + [
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
    recipients = (
        [payment.recorder.user]
        + _users_with_capability(building_id, "payment.record")
        + _users_with_capability(building_id, "ledger.publish")
    )
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
    # Residents in building + board
    from lamto.accounts.models import ResidentOccupancy

    residents = [
        o.user
        for o in ResidentOccupancy.objects.filter(
            unit__building_id=building_id, active=True
        ).select_related("user")
    ]
    recipients = residents + _users_with_role(
        building_id, OrganizationMembership.Role.BOARD
    )
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
    recipients = (
        _users_with_role(building_id, OrganizationMembership.Role.BOARD)
        + _users_with_role(building_id, OrganizationMembership.Role.AUDITOR)
    )
    notify_users(
        recipients,
        event_key=f"{EVENT_INTEGRITY_MISMATCH}:entry:{entry.pk}:obs:{observation.pk}",
        subject="Integrity mismatch detected",
        body=f"Published ledger entry #{entry.pk} failed integrity verification.",
        event_code=EVENT_INTEGRITY_MISMATCH,
        building=building_id,
    )


def notify_quarantined_upload(upload, building_id=None):
    recipients = [upload.uploader]
    if building_id is not None:
        recipients += _users_with_capability(building_id, "report.triage")
    notify_users(
        recipients,
        event_key=f"{EVENT_QUARANTINED_UPLOAD}:upload:{upload.pk}",
        subject="Upload quarantined",
        body=f"File {upload.filename} was quarantined: {upload.reason}",
        event_code=EVENT_QUARANTINED_UPLOAD,
        building=building_id if building_id is not None else upload.building_id,
    )
