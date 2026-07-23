from django.contrib.auth import get_user_model
from django.db import transaction

from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.notifications.models import Announcement, NotificationDelivery
from lamto.notifications.services import queue_notification

EVENT_ANNOUNCEMENT = "building.announcement"


def in_app_event_key(announcement_id: int) -> str:
    return f"{EVENT_ANNOUNCEMENT}:announcement:{announcement_id}"


def push_event_key(announcement_id: int, revision: int, action: str) -> str:
    return (
        f"{EVENT_ANNOUNCEMENT}:announcement:{announcement_id}:"
        f"revision:{revision}:{action}"
    )


@transaction.atomic
def publish_announcement(actor, building_id: int, title: str, body: str) -> Announcement:
    membership = require_management(actor, building_id)
    announcement = Announcement(
        building_id=building_id,
        title=title,
        body=body,
        created_by=actor,
        updated_by=actor,
    )
    announcement.full_clean()
    announcement.save()

    recipients = get_user_model().objects.filter(
        residentoccupancy__unit__building_id=building_id,
        residentoccupancy__active=True,
        is_active=True,
    ).distinct()
    for recipient in recipients:
        queue_notification(
            recipient=recipient,
            building=announcement.building,
            event_code=EVENT_ANNOUNCEMENT,
            event_key=in_app_event_key(announcement.id),
            subject=announcement.title,
            body=announcement.body,
            channels=[NotificationDelivery.Channel.IN_APP],
        )

    record_audit(
        actor=actor,
        membership=membership,
        action="announcement.published",
        target_type="Announcement",
        target_id=str(announcement.id),
        result="accepted",
        metadata={
            "announcement_id": announcement.id,
            "revision": announcement.revision,
        },
    )
    return announcement
