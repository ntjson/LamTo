import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from lamto.gate.devices import issue_credential
from lamto.gate.models import GateDevice
from lamto.gate.tests.conftest import building, management  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def reader(building, management):
    device = GateDevice.objects.create(
        building=building, label="North", direction=GateDevice.Direction.ENTRY
    )
    _, token = issue_credential(device, management)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"GateDevice {token}")
    return client


def test_missing_reader_credential_is_rejected():
    response = APIClient().post(
        reverse("api:gate-recognize-plate"), {"plate": "51F12345"}, format="json"
    )
    assert response.status_code == 401
    assert response.json()["code"] == "gate_device_unauthenticated"


def test_reader_plate_endpoint_returns_unreadable_code(reader):
    response = reader.post(
        reverse("api:gate-recognize-plate"), {"plate": "!!"}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "gate_plate_unreadable"
