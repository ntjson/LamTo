"""Durable notification queue and delivery helpers.

Business services must call ``queue_notification`` via ``transaction.on_commit``
so notification failures never roll back domain state.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import NotificationDelivery, NotificationPreference


# Material event codes used by domain services and preference forms.
EVENT_REPORT_RECEIPT = "report.receipt"
EVENT_TRIAGE_STATUS = "triage.status"
EVENT_CASE_STATUS = "case.status"
EVENT_WORK_ASSIGNED = "work.assigned"
EVENT_DEADLINE_RISK = "work.deadline_risk"
EVENT_PROPOSAL_APPROVAL = "proposal.approval"
EVENT_PROPOSAL_REJECTION = "proposal.rejection"
EVENT_EMERGENCY_DEADLINE = "emergency.deadline"
EVENT_EMERGENCY_OUTCOME = "emergency.outcome"
EVENT_WORK_ACCEPTED = "work.accepted"
EVENT_PAYMENT_RECORDED = "payment.recorded"
EVENT_PAYMENT_VERIFIED = "payment.verified"
EVENT_PAYMENT_REJECTED = "payment.rejected"
EVENT_PUBLICATION = "ledger.publication"
EVENT_CORRECTION_STATUS = "correction.status"
EVENT_INTEGRITY_MISMATCH = "integrity.mismatch"
EVENT_QUARANTINED_UPLOAD = "document.quarantined"
EVENT_OUTBOX_FAILED = "outbox.failed"

# In-app notices for these codes cannot be disabled.
REQUIRED_IN_APP_EVENT_CODES = frozenset(
    {
        EVENT_REPORT_RECEIPT,
        EVENT_TRIAGE_STATUS,
        EVENT_CASE_STATUS,
        EVENT_WORK_ASSIGNED,
        EVENT_DEADLINE_RISK,
        EVENT_PROPOSAL_APPROVAL,
        EVENT_PROPOSAL_REJECTION,
        EVENT_EMERGENCY_DEADLINE,
        EVENT_EMERGENCY_OUTCOME,
        EVENT_WORK_ACCEPTED,
        EVENT_PAYMENT_RECORDED,
        EVENT_PAYMENT_VERIFIED,
        EVENT_PAYMENT_REJECTED,
        EVENT_PUBLICATION,
        EVENT_CORRECTION_STATUS,
        EVENT_INTEGRITY_MISMATCH,
        EVENT_QUARANTINED_UPLOAD,
        EVENT_OUTBOX_FAILED,
    }
)

PREFERENCE_EVENT_CHOICES = (
    (EVENT_REPORT_RECEIPT, "Report receipt"),
    (EVENT_TRIAGE_STATUS, "Triage / case status"),
    (EVENT_WORK_ASSIGNED, "Work assignment"),
    (EVENT_DEADLINE_RISK, "Deadline risk"),
    (EVENT_PROPOSAL_APPROVAL, "Proposal approval / rejection"),
    (EVENT_EMERGENCY_OUTCOME, "Emergency outcomes"),
    (EVENT_PAYMENT_RECORDED, "Payment actions"),
    (EVENT_PUBLICATION, "Ledger publication"),
    (EVENT_CORRECTION_STATUS, "Corrections"),
    (EVENT_INTEGRITY_MISMATCH, "Integrity mismatch"),
)

DEFAULT_CHANNELS = (
    NotificationDelivery.Channel.IN_APP,
    NotificationDelivery.Channel.EMAIL,
)

MAX_EMAIL_ATTEMPTS = 8
BASE_BACKOFF_SECONDS = 30


def email_enabled_for(user, event_code: str) -> bool:
    pref = NotificationPreference.objects.filter(
        user=user, event_code=event_code
    ).first()
    if pref is None:
        return True
    return bool(pref.email_enabled)


def queue_notification(
    recipient,
    event_key: str,
    subject: str,
    body: str,
    channels=None,
    *,
    event_code: str = "",
) -> list[NotificationDelivery]:
    """Idempotently enqueue delivery rows for the given channels.

    Unique on (recipient, event_key, channel). Returns existing rows on conflict.
    """
    if channels is None:
        channels = list(DEFAULT_CHANNELS)
    created: list[NotificationDelivery] = []
    for channel in channels:
        if channel == NotificationDelivery.Channel.EMAIL:
            code = event_code or _event_code_from_key(event_key)
            if not email_enabled_for(recipient, code):
                continue
        delivery, _ = NotificationDelivery.objects.get_or_create(
            recipient=recipient,
            event_key=event_key,
            channel=channel,
            defaults={
                "subject": subject,
                "body": body,
                "event_code": event_code or _event_code_from_key(event_key),
                "status": NotificationDelivery.Status.PENDING,
            },
        )
        created.append(delivery)
    return created


def queue_notification_after_commit(
    recipient,
    event_key: str,
    subject: str,
    body: str,
    channels=None,
    *,
    event_code: str = "",
):
    """Schedule queue_notification after the current transaction commits."""
    recipient_id = getattr(recipient, "pk", recipient)

    def _enqueue():
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=recipient_id).first()
        if user is None:
            return
        try:
            queue_notification(
                user,
                event_key,
                subject,
                body,
                channels,
                event_code=event_code,
            )
        except Exception:
            # Never raise into business path; failures are isolated to the worker.
            return

    transaction.on_commit(_enqueue)


def _event_code_from_key(event_key: str) -> str:
    # event_key format: "{code}:{entity}:{id}" or plain code
    if ":" in event_key:
        return event_key.split(":", 1)[0]
    return event_key


def claim_pending_deliveries(*, limit: int = 50) -> list[NotificationDelivery]:
    """Claim due pending/failed email or pending in-app rows with skip_locked."""
    now = timezone.now()
    claimed: list[NotificationDelivery] = []
    with transaction.atomic():
        qs = (
            NotificationDelivery.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=NotificationDelivery.Status.PENDING)
                | Q(
                    status=NotificationDelivery.Status.FAILED,
                    next_retry_at__lte=now,
                )
            )
            .order_by("created_at", "pk")[:limit]
        )
        for row in qs:
            claimed.append(row)
    return claimed


def process_delivery(delivery: NotificationDelivery) -> NotificationDelivery:
    """Process a single claimed delivery row."""
    with transaction.atomic():
        locked = (
            NotificationDelivery.objects.select_for_update()
            .filter(pk=delivery.pk)
            .first()
        )
        if locked is None:
            return delivery
        if locked.status in {
            NotificationDelivery.Status.SENT,
            NotificationDelivery.Status.AVAILABLE,
            NotificationDelivery.Status.DEAD,
        }:
            return locked

        if locked.channel == NotificationDelivery.Channel.IN_APP:
            locked.status = NotificationDelivery.Status.AVAILABLE
            locked.attempts += 1
            locked.last_error = ""
            locked.save(
                update_fields=["status", "attempts", "last_error", "updated_at"]
            )
            return locked

        # EMAIL
        locked.attempts += 1
        try:
            send_mail(
                locked.subject,
                locked.body,
                None,
                [locked.recipient.email],
                fail_silently=False,
            )
        except Exception as exc:
            locked.last_error = str(exc)[:2000]
            if locked.attempts >= MAX_EMAIL_ATTEMPTS:
                locked.status = NotificationDelivery.Status.DEAD
                locked.next_retry_at = None
            else:
                locked.status = NotificationDelivery.Status.FAILED
                backoff = BASE_BACKOFF_SECONDS * (2 ** min(locked.attempts - 1, 6))
                locked.next_retry_at = timezone.now() + timedelta(seconds=backoff)
            locked.save(
                update_fields=[
                    "status",
                    "attempts",
                    "last_error",
                    "next_retry_at",
                    "updated_at",
                ]
            )
            return locked

        locked.status = NotificationDelivery.Status.SENT
        locked.last_error = ""
        locked.next_retry_at = None
        locked.save(
            update_fields=[
                "status",
                "attempts",
                "last_error",
                "next_retry_at",
                "updated_at",
            ]
        )
        return locked


def process_due_notifications(*, limit: int = 50) -> list[NotificationDelivery]:
    """Claim and process a bounded batch of due notification deliveries."""
    results: list[NotificationDelivery] = []
    for delivery in claim_pending_deliveries(limit=limit):
        results.append(process_delivery(delivery))
    return results


def notify_users(
    users,
    *,
    event_key: str,
    subject: str,
    body: str,
    event_code: str,
):
    """Queue notifications for many users after commit (deduped by id)."""
    seen = set()
    for user in users:
        if user is None:
            continue
        uid = getattr(user, "pk", None)
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        queue_notification_after_commit(
            user,
            event_key=event_key,
            subject=subject,
            body=body,
            event_code=event_code,
        )
