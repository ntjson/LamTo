from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse

from lamto.gate.models import GateDevice
from lamto.gate.tests.conftest import building, clean_scanner, gate_storage, management, occupancy, use_fake_embedder  # noqa: F401
from lamto.gate.tests.test_review import _enrol
from lamto.web.views.gate import gate_devices


def test_device_credential_actions_require_recent_reauthentication():
    request = RequestFactory().post("/s/gate/devices", {"action": "rotate", "device": "1"})
    with patch("lamto.web.views.gate.require_management_context", return_value=(Mock(), [])), patch("lamto.web.views.gate.require_recent_auth", side_effect=PermissionDenied), pytest.raises(PermissionDenied):
        gate_devices(request)


@pytest.mark.django_db
def test_pending_face_photo_is_never_cached(client, occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    enrollment = _enrol(occupancy, clean_scanner)
    client.force_login(management.user)
    with patch("lamto.accounts.middleware.require_staff_mfa"), patch("lamto.web.staff.require_staff_mfa"):
        response = client.get(reverse("web:gate-face-photo", args=[enrollment.pk]))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["Pragma"] == "no-cache"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("label", "direction"),
    [("", GateDevice.Direction.ENTRY), ("   ", GateDevice.Direction.ENTRY), ("North", "entry"), ("North", "SIDEWAYS"), ("North", "")],
)
def test_invalid_reader_is_not_created_and_reports_error(client, management, label, direction):
    client.force_login(management.user)
    with patch("lamto.accounts.middleware.require_staff_mfa"), patch("lamto.web.staff.require_staff_mfa"), patch("lamto.web.views.gate.require_recent_auth"):
        response = client.post(reverse("web:gate-devices"), {"action": "create", "label": label, "direction": direction})
    assert response.status_code == 200
    assert GateDevice.objects.count() == 0
    assert b'role="alert"' in response.content
