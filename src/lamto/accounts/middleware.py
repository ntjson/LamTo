"""Staff workspace security: MFA gate, break-glass request audit, reauth redirect."""

from __future__ import annotations

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from lamto.accounts.security import (
    RecentAuthRequired,
    assert_break_glass_allows_path,
    require_staff_mfa,
)

# MFA enrollment/verify must remain reachable before OTP is confirmed.
_MFA_EXEMPT_PREFIXES = (
    "/s/security/mfa/setup/",
    "/s/security/mfa/verify/",
)


class StaffSecurityMiddleware:
    """Enforce staff MFA and break-glass controls on every /s/ request.

    - Confirmed TOTP + OTP-verified session required for all /s/ routes
      except MFA setup/verify (so users can enroll and step up).
    - Every request under an active break-glass session is audited and
      business route prefixes remain denied.
    - RecentAuthRequired → redirect to reauth with next=.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        path = request.path or ""
        if not path.startswith("/s/"):
            return None

        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None

        exempt = any(path.startswith(prefix) for prefix in _MFA_EXEMPT_PREFIXES)
        if not exempt:
            require_staff_mfa(request)

        # Audit every break-glass request (including MFA-exempt security paths).
        assert_break_glass_allows_path(request, path=path)
        return None

    def process_exception(self, request, exception):
        if isinstance(exception, RecentAuthRequired):
            next_url = request.get_full_path()
            return redirect(
                f"{reverse('web:reauth')}?{urlencode({'next': next_url})}"
            )
        return None
