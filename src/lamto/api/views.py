"""Resident API views (spec 3). Resident-only; staff stay on the /s/ web surface."""

from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from drf_spectacular.utils import extend_schema, extend_schema_view
from knox.models import AuthToken
from knox.views import LogoutAllView as KnoxLogoutAllView
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import exceptions, generics, pagination, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from lamto.accounts.security import (
    assert_not_throttled,
    client_ip,
    record_auth_failure,
    reset_auth_throttle,
)
from lamto.accounts.tenancy import active_occupancies
from lamto.api.authentication import ResidentTokenAuthentication
from lamto.api.occupancy import OCCUPANCY_HEADER_PARAMETER, resolve_api_occupancy
from lamto.api.problems import problem_responses
from lamto.api.serializers import (
    FundSummarySerializer,
    LedgerEntryDetailSerializer,
    LedgerEntryListSerializer,
    LedgerFilterSerializer,
    LoginSerializer,
    MeSerializer,
    TokenResponseSerializer,
)
from lamto.api.services import (
    INVALID_CREDENTIALS_DETAIL,
    canonicalize_login_identifier,
    log_auth_outcome,
    revoke_tokens_if_no_active_occupancy,
)
from lamto.evidence.models import evidence_level
from lamto.finance.fund import fund_balance
from lamto.finance.selectors import (
    fund_period_flows,
    ledger_entry_proof,
    published_ledger_entries,
    published_ledger_entry_for_proof,
)

TOKEN_CAP_PER_USER = 5  # spec 3.2: 5 concurrent tokens; oldest evicted at login


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def get_authenticate_header(self, request):
        # DRF coerces AuthenticationFailed → 403 when no authenticators provide a
        # WWW-Authenticate header. Keep login failures as 401 (clarification 2).
        return 'Token'

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: TokenResponseSerializer,
            **problem_responses(400, 401, 429),
        },
    )
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
    # Use the resident auth class so spectacular sees one knox scheme only.
    authentication_classes = [ResidentTokenAuthentication]

    @extend_schema(
        request=None,
        responses={204: None, **problem_responses(401)},
    )
    def post(self, request, format=None):
        return super().post(request, format)


class LogoutAllView(KnoxLogoutAllView):
    authentication_classes = [ResidentTokenAuthentication]

    @extend_schema(
        request=None,
        responses={204: None, **problem_responses(401)},
    )
    def post(self, request, format=None):
        return super().post(request, format)


class MeView(APIView):
    @extend_schema(responses={200: MeSerializer, **problem_responses(401, 403)})
    def get(self, request):
        occupancies = list(active_occupancies(request.user))
        if not occupancies:
            raise exceptions.PermissionDenied(
                "An active resident occupancy is required."
            )
        preferences = list(
            request.user.notification_preferences.order_by("event_code").values(
                "event_code", "email_enabled"
            )
        )
        data = {
            "display_name": request.user.display_name,
            "email": request.user.email,
            "phone": request.user.phone,
            "occupancies": [
                {
                    "id": occupancy.pk,
                    "unit_label": occupancy.unit.label,
                    "building_name": occupancy.unit.building.name,
                }
                for occupancy in occupancies
            ],
            "notification_preferences": preferences,
        }
        return Response(MeSerializer(data).data)


class LedgerCursorPagination(pagination.CursorPagination):
    page_size = 20  # spec 3.1
    ordering = ("-published_at", "-pk")


@extend_schema_view(
    get=extend_schema(
        parameters=[LedgerFilterSerializer, OCCUPANCY_HEADER_PARAMETER],
        responses={
            200: LedgerEntryListSerializer,
            **problem_responses(400, 401, 403, 404, 422),
        },
    ),
)
class LedgerListView(generics.ListAPIView):
    serializer_class = LedgerEntryListSerializer
    pagination_class = LedgerCursorPagination

    def get_queryset(self):
        filters = LedgerFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        _occupancy, tenant = resolve_api_occupancy(self.request)
        entries = published_ledger_entries(tenant.building_id)
        year = filters.validated_data.get("year")
        month = filters.validated_data.get("month")
        if year is not None:
            entries = entries.filter(published_at__year=year)
        if month is not None:
            entries = entries.filter(published_at__month=month)
        return entries


class LedgerDetailView(APIView):
    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={
            200: LedgerEntryDetailSerializer,
            **problem_responses(401, 403, 404, 422),
        },
    )
    def get(self, request, pk):
        _occupancy, tenant = resolve_api_occupancy(request)
        entry = published_ledger_entry_for_proof(tenant.building_id, pk)
        if entry is None:
            raise exceptions.NotFound("Published ledger entry not found.")
        detail = ledger_entry_proof(entry)
        verification = detail["verification"]
        data = {
            "id": entry.pk,
            "contractor_name": entry.contractor_name,
            "actual_cost_vnd": entry.actual_cost_vnd,
            "published_at": entry.published_at,
            "proposed_amount_vnd": detail["proposed_amount"],
            "integrity_status": entry.effective_integrity_status,
            "payload": detail["payload"],
            "verification": (
                {
                    "decision": verification.decision,
                    "verified_by": verification.membership.user.display_name,
                    "verified_at": verification.verified_at,
                }
                if verification is not None
                else None
            ),
            "redacted_documents": detail["redacted_docs"],
            "corrections": [
                {
                    "id": correction.pk,
                    "status": correction.status,
                    "reason": correction.reason,
                }
                for correction in detail["corrections"]
            ],
            "proof": {
                "evidence_level": detail["evidence_level"],
                "anchoring_backend": entry.snapshot.anchoring_backend,
                "payload_hash": entry.snapshot.resident_payload_hash,
                "events": [
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "status": event.status,
                        "evidence_level": evidence_level(event.status),
                        "transaction_hash": event.transaction_hash,
                    }
                    for event in detail["events"]
                ],
            },
        }
        return Response(LedgerEntryDetailSerializer(data).data)


class FundSummaryView(APIView):
    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={
            200: FundSummarySerializer,
            **problem_responses(401, 403, 404, 422),
        },
    )
    def get(self, request):
        _occupancy, tenant = resolve_api_occupancy(request)
        inflows, outflows = fund_period_flows(tenant.building_id)
        data = {
            "balance_vnd": fund_balance(tenant.building_id, verified_only=True),
            "period_days": 30,
            "period_inflows_vnd": inflows,
            "period_outflows_vnd": outflows,
        }
        return Response(FundSummarySerializer(data).data)
