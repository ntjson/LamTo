import pytest
from django.test import Client
from django.urls import reverse
from knox.models import AuthToken

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

    client = Client()
    res = client.get(reverse("api:bills-list"), headers=_auth(resident))
    ids = [row["id"] for row in res.json()["results"]]
    assert res.status_code == 200 and ids == [bill.pk]

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
