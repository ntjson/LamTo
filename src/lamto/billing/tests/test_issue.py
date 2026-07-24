import pytest
from django.test import override_settings
from django.utils import timezone

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    ResidentOccupancy,
    Unit,
    User,
)
from lamto.audit.models import AuditEvent
from lamto.billing.models import Bill
from lamto.billing.services import EVENT_BILL_ISSUED, in_app_event_key, issue_bill
from lamto.documents.models import Document, DocumentVersion
from lamto.notifications.models import Device, NotificationDelivery


pytestmark = pytest.mark.django_db


def _doc(building, uploader):
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    return DocumentVersion.objects.create(
        document=document,
        version=1,
        storage_key=f"k/{document.pk}",
        provider_version_id="v",
        filename="bill.pdf",
        content_type="application/pdf",
        byte_size=10,
        sha256="0" * 64,
        uploader=uploader,
    )


@override_settings(PUSH_ENABLED=True)
def test_issue_bill_targets_only_the_named_resident():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    co_resident = User.objects.create_user(email="c@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    ResidentOccupancy.objects.create(user=co_resident, unit=unit)
    Device.objects.create(
        user=resident,
        install_id="i",
        fcm_token="t",
        platform=Device.Platform.ANDROID,
        last_seen_at=timezone.now(),
    )

    bill = issue_bill(
        manager,
        building.pk,
        resident.pk,
        title="Phí 07/2026",
        amount_vnd=250000,
        document=_doc(building, manager),
    )

    assert bill.status == Bill.Status.ISSUED
    in_app = NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.IN_APP,
        event_key=in_app_event_key(bill.pk),
    )
    assert list(in_app.values_list("recipient_id", flat=True)) == [resident.pk]
    assert in_app.get().status == NotificationDelivery.Status.AVAILABLE
    push = NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.PUSH,
        event_code=EVENT_BILL_ISSUED,
    )
    assert list(push.values_list("recipient_id", flat=True)) == [resident.pk]
    assert not NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.EMAIL,
        event_code=EVENT_BILL_ISSUED,
    ).exists()
    assert AuditEvent.objects.filter(
        target_type="Bill",
        target_id=str(bill.pk),
        action="bill.issued",
    ).exists()


def test_issue_bill_rejects_resident_without_active_occupancy():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    stranger = User.objects.create_user(email="s@x.test", password="pw")
    with pytest.raises(Exception):
        issue_bill(
            manager,
            building.pk,
            stranger.pk,
            title="x",
            amount_vnd=1000,
            document=_doc(building, manager),
        )
