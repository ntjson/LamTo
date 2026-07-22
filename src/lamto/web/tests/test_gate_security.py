from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from lamto.web.views.gate import gate_devices


def test_device_credential_actions_require_recent_reauthentication():
    request = RequestFactory().post("/s/gate/devices", {"action": "rotate", "device": "1"})
    with patch("lamto.web.views.gate.require_management_context", return_value=(Mock(), [])), patch("lamto.web.views.gate.require_recent_auth", side_effect=PermissionDenied), pytest.raises(PermissionDenied):
        gate_devices(request)
