from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import GateEvent, GatePurgeHeartbeat, PendingEnrollmentPhoto, ReviewStatus
from .photos import delete_pending_photo

PURGE_STALE_AFTER_HOURS = 2


def purge_expired_gate_events(now=None):
    now = now or timezone.now()
    deleted, _ = GateEvent.objects.filter(occurred_at__lt=now - timedelta(hours=settings.GATE_EVENT_RETENTION_HOURS)).delete()
    return deleted


def purge_expired_enrollment_photos(now=None):
    now = now or timezone.now()
    expired = list(PendingEnrollmentPhoto.objects.filter(expires_at__lte=now).select_related("enrollment"))
    for photo in expired:
        delete_pending_photo(photo.storage_key, photo.provider_version_id)
        with transaction.atomic():
            enrollment = photo.enrollment
            if enrollment.status == ReviewStatus.PENDING:
                enrollment.status = ReviewStatus.EXPIRED
                enrollment.embedding = None
                enrollment.save(update_fields=["status", "embedding"])
            photo.delete()
    return len(expired)


def record_purge_success(*, events, photos):
    heartbeat = GatePurgeHeartbeat.objects.order_by("pk").first()
    values = {"last_success_at": timezone.now(), "events_deleted": events, "photos_deleted": photos}
    if heartbeat is None:
        return GatePurgeHeartbeat.objects.create(**values)
    for field, value in values.items():
        setattr(heartbeat, field, value)
    heartbeat.save(update_fields=list(values))
    return heartbeat


def purge_is_stale(now=None):
    now = now or timezone.now()
    heartbeat = GatePurgeHeartbeat.objects.order_by("-last_success_at").first()
    return heartbeat is None or heartbeat.last_success_at < now - timedelta(hours=PURGE_STALE_AFTER_HOURS)
