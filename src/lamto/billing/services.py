from django.contrib.auth import get_user_model
from django.db import transaction

from lamto.accounts.models import ResidentOccupancy
from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.billing.models import Bill
from lamto.documents.models import Document
from lamto.notifications.models import NotificationDelivery
from lamto.notifications.services import EVENT_BILL_ISSUED, queue_notification


class BillError(Exception):
    pass


def in_app_event_key(bill_id: int) -> str:
    return f"{EVENT_BILL_ISSUED}:bill:{bill_id}"


def push_event_key(bill_id: int) -> str:
    return f"{EVENT_BILL_ISSUED}:bill:{bill_id}:issued"


@transaction.atomic
def issue_bill(
    actor,
    building_id,
    resident_id,
    *,
    title,
    amount_vnd,
    document,
    note="",
    period="",
    due_date=None,
) -> Bill:
    membership = require_management(actor, building_id)
    resident = get_user_model().objects.filter(pk=resident_id).first()
    if resident is None:
        raise BillError("Resident does not exist.")
    if not ResidentOccupancy.objects.filter(
        user_id=resident_id,
        active=True,
        unit__building_id=building_id,
    ).exists():
        raise BillError("Resident has no active occupancy in this building.")
    if document.document.kind != Document.Kind.RESIDENT_BILL:
        raise BillError("Document must be a resident bill.")
    if document.document.building_id != building_id:
        raise BillError("Document must belong to the target building.")

    bill = Bill.objects.create(
        building_id=building_id,
        resident=resident,
        title=title,
        note=note,
        period=period,
        due_date=due_date,
        amount_vnd=amount_vnd,
        document=document,
        issued_by=actor,
    )
    subject = f"{title} — {amount_vnd:,}đ"
    queue_notification(
        recipient=resident,
        building=bill.building,
        event_code=EVENT_BILL_ISSUED,
        event_key=in_app_event_key(bill.pk),
        subject=subject,
        body=note,
        channels=[NotificationDelivery.Channel.IN_APP],
    )
    queue_notification(
        recipient=resident,
        building=bill.building,
        event_code=EVENT_BILL_ISSUED,
        event_key=push_event_key(bill.pk),
        subject=subject,
        body=note,
        channels=[NotificationDelivery.Channel.PUSH],
    )
    NotificationDelivery.objects.filter(
        event_key=in_app_event_key(bill.pk),
        channel=NotificationDelivery.Channel.IN_APP,
    ).update(status=NotificationDelivery.Status.AVAILABLE)
    record_audit(
        actor=actor,
        membership=membership,
        action="bill.issued",
        target_type="Bill",
        target_id=str(bill.pk),
        result="accepted",
        metadata={"bill_id": bill.pk, "amount_vnd": amount_vnd},
    )
    return bill
