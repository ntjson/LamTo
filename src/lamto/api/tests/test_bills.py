from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from knox.models import AuthToken

from lamto.api.downloads import issue_download_token
from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.billing.models import Bill
from lamto.billing.services import issue_bill, void_bill
from lamto.documents.models import Document, DocumentVersion


pytestmark = pytest.mark.django_db


def _world():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    version = DocumentVersion.objects.create(
        document=document,
        version=1,
        storage_key=f"k/{document.pk}",
        provider_version_id="v",
        filename="b.pdf",
        content_type="application/pdf",
        byte_size=1,
        sha256="0" * 64,
        uploader=manager,
    )
    bill = issue_bill(
        manager,
        building.pk,
        resident.pk,
        title="Phí 07",
        amount_vnd=250000,
        document=version,
    )
    return manager, resident, bill


def _auth(user):
    _inst, token = AuthToken.objects.create(user=user)
    return {"authorization": f"Token {token}"}


def test_list_shows_only_own_non_void_bills():
    manager, resident, bill = _world()
    other = User.objects.create_user(email="o@x.test", password="pw")
    unit = ResidentOccupancy.objects.get(user=resident).unit
    ResidentOccupancy.objects.create(user=other, unit=unit)
    voided = issue_bill(
        manager,
        bill.building_id,
        resident.pk,
        title="Void me",
        amount_vnd=1,
        document=bill.document,
    )
    void_bill(manager, voided.pk, reason="oops")
    newest = issue_bill(
        manager,
        bill.building_id,
        resident.pk,
        title="Newest",
        amount_vnd=2,
        document=bill.document,
    )

    client = Client()
    res = client.get(reverse("api:bills-list"), headers=_auth(resident))
    ids = [row["id"] for row in res.json()["results"]]
    assert res.status_code == 200 and ids == [newest.pk, bill.pk]

    # A co-resident sees none of this resident's bills.
    assert client.get(reverse("api:bills-list"), headers=_auth(other)).json()["results"] == []


def test_detail_denied_for_other_resident_and_carries_download_url():
    _manager, resident, bill = _world()
    stranger = User.objects.create_user(email="s@x.test", password="pw")
    other_building = Building.objects.create(name="Tower B")
    other_unit = Unit.objects.create(building=other_building, label="201")
    ResidentOccupancy.objects.create(user=stranger, unit=other_unit)
    client = Client()
    ok = client.get(reverse("api:bills-detail", args=[bill.pk]), headers=_auth(resident))
    assert ok.status_code == 200
    assert "/api/v1/documents/" in ok.json()["document_download_url"]
    denied = client.get(reverse("api:bills-detail", args=[bill.pk]), headers=_auth(stranger))
    assert denied.status_code == 404


def _redeem(client, user, document_id):
    token = issue_download_token(user.pk, document_id)
    return client.get(reverse("api:document-download", args=[token]), headers=_auth(user))


def test_bill_download_token_owner_succeeds():
    _manager, resident, bill = _world()
    with patch("lamto.api.views.read_version_bytes", return_value=b"bill"):
        response = _redeem(Client(), resident, bill.document_id)

    assert response.status_code == 200
    assert response.content == b"bill"


def test_bill_download_token_denies_co_resident():
    _manager, resident, bill = _world()
    co_resident = User.objects.create_user(email="co@x.test", password="pw")
    ResidentOccupancy.objects.create(
        user=co_resident,
        unit=ResidentOccupancy.objects.get(user=resident).unit,
    )
    with patch("lamto.api.views.read_version_bytes", return_value=b"bill"):
        response = _redeem(Client(), co_resident, bill.document_id)

    assert response.status_code == 404


def test_bill_download_token_denies_void_bill():
    manager, resident, bill = _world()
    void_bill(manager, bill.pk, reason="cancelled")
    with patch("lamto.api.views.read_version_bytes", return_value=b"bill"):
        response = _redeem(Client(), resident, bill.document_id)

    assert response.status_code == 404
