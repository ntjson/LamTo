"""Resident API views (spec 3). Resident-only; staff stay on the /s/ web surface."""

from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from drf_spectacular.utils import extend_schema
from knox.models import AuthToken
from knox.views import LogoutAllView as KnoxLogoutAllView
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import exceptions, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from lamto.accounts.security import (
    assert_not_throttled,
    client_ip,
    record_auth_failure,
    reset_auth_throttle,
)
from lamto.accounts.tenancy import active_occupancies
from lamto.api.serializers import LoginSerializer, TokenResponseSerializer
from lamto.api.services import (
    INVALID_CREDENTIALS_DETAIL,
    canonicalize_login_identifier,
    log_auth_outcome,
    revoke_tokens_if_no_active_occupancy,
)

TOKEN_CAP_PER_USER = 5  # spec 3.2: 5 concurrent tokens; oldest evicted at login


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def get_authenticate_header(self, request):
        # DRF coerces AuthenticationFailed → 403 when no authenticators provide a
        # WWW-Authenticate header. Keep login failures as 401 (clarification 2).
        return 'Token'

    @extend_schema(request=LoginSerializer, responses={200: TokenResponseSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_identifier = serializer.validated_data["identifier"]
        identifier = canonicalize_login_identifier(raw_identifier)
        ip = client_ip(request)
        try:
            assert_not_throttled(identifier, ip)
        except DjangoPermissionDenied:
            raise exceptions.Throttled(
                detail="Too many authentication attempts. Try again later."
            )
        user = authenticate(
            request,
            username=identifier,
            password=serializer.validated_data["password"],
        )
        if user is None:
            record_auth_failure(identifier, ip, kind="login")
            log_auth_outcome(
                reason="invalid_credentials",
                identifier=identifier,
                ip=ip,
            )
            raise exceptions.AuthenticationFailed(INVALID_CREDENTIALS_DETAIL)
        if not active_occupancies(user).exists():
            # Unified external 401 (clarification 2); distinct internal reason.
            # Count toward the same login throttle as wrong-password failures so
            # correct-password / ineligible accounts cannot oracle around lockout.
            # Revoke any leftover knox tokens (bulk occupancy deactivation bypasses
            # post_save signals; login is the defensive cleanup path).
            record_auth_failure(identifier, ip, kind="login")
            revoke_tokens_if_no_active_occupancy(user)
            log_auth_outcome(
                reason="no_active_occupancy",
                identifier=identifier,
                user_id=user.pk,
                ip=ip,
            )
            raise exceptions.AuthenticationFailed(INVALID_CREDENTIALS_DETAIL)
        reset_auth_throttle(identifier, ip)
        stale = list(AuthToken.objects.filter(user=user).order_by("-created"))[
            TOKEN_CAP_PER_USER - 1 :
        ]
        for old_token in stale:
            old_token.delete()
        instance, token = AuthToken.objects.create(user=user)
        log_auth_outcome(
            reason="success",
            identifier=identifier,
            user_id=user.pk,
            ip=ip,
        )
        return Response(
            TokenResponseSerializer({"token": token, "expiry": instance.expiry}).data
        )


class LogoutView(KnoxLogoutView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, format=None):
        return super().post(request, format)


class LogoutAllView(KnoxLogoutAllView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, format=None):
        return super().post(request, format)
