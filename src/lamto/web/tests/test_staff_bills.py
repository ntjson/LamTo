import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    ResidentOccupancy,
    Unit,
    User,
)
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.billing.models import Bill
from lamto.notifications.models import NotificationDelivery


pytestmark = pytest.mark.django_db


def setup_manager(client, name="Tower A"):
    building = Building.objects.create(name=name)
    manager = User.objects.create_user(email="manager@x.test", password="secret")
    ManagementMembership.objects.create(user=manager, building=building)
    client.force_login(manager)
    device = TOTPDevice.objects.create(
        user=manager, name="t", confirmed=True, key=random_hex()
    )
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session[RECENT_REAUTH_KEY] = time.time()
    session.save()
    return building, manager


def _pdf():
    return SimpleUploadedFile(
        "bill.pdf", b"%PDF-1.4\n" + b"0" * 32, content_type="application/pdf"
    )


@override_settings(PUSH_ENABLED=False)
def test_issue_creates_bill_and_delivery(client):
    building, _manager = setup_manager(client)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)

    response = client.post(
        reverse("web:staff-bill-create"),
        {
            "resident": resident.pk,
            "title": "Phí 07/2026",
            "amount_vnd": "250000",
            "note": "Hạn 25/07",
            "document": _pdf(),
        },
    )

    assert response.status_code == 302
    bill = Bill.objects.get()
    assert (bill.resident_id, bill.amount_vnd, bill.status) == (
        resident.pk,
        250000,
        Bill.Status.ISSUED,
    )
    assert (
        NotificationDelivery.objects.filter(
            recipient=resident, channel=NotificationDelivery.Channel.IN_APP
        ).count()
        == 1
    )


def test_cross_building_resident_is_rejected(client):
    setup_manager(client)
    other = Building.objects.create(name="Tower B")
    other_unit = Unit.objects.create(building=other, label="9")
    stranger = User.objects.create_user(email="s@x.test", password="pw")
    ResidentOccupancy.objects.create(user=stranger, unit=other_unit)

    response = client.post(
        reverse("web:staff-bill-create"),
        {
            "resident": stranger.pk,
            "title": "x",
            "amount_vnd": "1000",
            "document": _pdf(),
        },
    )

    assert response.status_code == 200
    assert not Bill.objects.exists()
