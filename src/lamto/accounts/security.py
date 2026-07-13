"""Authentication throttle, re-auth, break-glass, and privileged-action gates."""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.audit.services import record_audit

from .models import (
    AuthThrottleBucket,
    BreakGlassRevocation,
    BreakGlassSession,
    OrganizationMembership,
)

RECENT_REAUTH_KEY = "recent_reauth_at"
DEFAULT_REAUTH_MAX_AGE = 300
THROTTLE_MAX_FAILURES = 5
THROTTLE_WINDOW_SECONDS = 15 * 60
BREAK_GLASS_MAX_MINUTES = 60
BREAK_GLASS_CONSENT_MAX_AGE = 600  # seconds; authorizer dual-control token
BREAK_GLASS_CONSENT_SALT = "lamto.break_glass.consent"


class RecentAuthRequired(PermissionDenied):
    """Recent re-authentication required; StaffSecurityMiddleware redirects to reauth."""



# Capabilities / route families blocked under break-glass and for pure tech admins.
BUSINESS_ROUTE_PREFIXES = (
    "/s/cases/",
    "/s/reports/",
    "/s/proposals/",
    "/s/work/",
    "/s/payments/",
    "/s/audit/",
    "/s/emergency/",
)
FINANCE_DOCUMENT_URL_NAMES = frozenset(
    {
        "web:case-list",
        "web:case-detail",
        "web:staff-report-detail",
        "web:proposal-list",
        "web:proposal-detail",
        "web:work-order-list",
        "web:work-order-detail",
        "web:work-accept",
        "web:emergency-authorize",
        "web:emergency-decide",
        "web:payment-list",
        "web:payment-record-detail",
        "web:payment-verify-detail",
        "web:payment-record",
        "web:audit-search",
        "web:audit-export",
    }
)


def throttle_digest(account: str, ip: str | None) -> str:
    normalized = f"{(account or '').strip().lower()}|{(ip or '').strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _now():
    return timezone.now()


@transaction.atomic
def assert_not_throttled(account: str, ip: str | None) -> None:
    digest = throttle_digest(account, ip)
    bucket = (
        AuthThrottleBucket.objects.select_for_update()
        .filter(key_digest=digest)
        .first()
    )
    if bucket is None:
        return
    now = _now()
    if bucket.locked_until and bucket.locked_until > now:
        raise PermissionDenied("Too many authentication attempts. Try again later.")
    if (
        bucket.window_started_at
        and (now - bucket.window_started_at).total_seconds() > THROTTLE_WINDOW_SECONDS
    ):
        # Window expired; caller may proceed (bucket reset happens on next failure/success).
        return


@transaction.atomic
def record_auth_failure(account: str, ip: str | None, *, kind: str = "login") -> AuthThrottleBucket:
    """Record a failed login/MFA attempt. Never stores password or OTP values."""
    digest = throttle_digest(account, ip)
    bucket, _ = AuthThrottleBucket.objects.select_for_update().get_or_create(
        key_digest=digest,
        defaults={"failure_count": 0, "window_started_at": _now()},
    )
    now = _now()
    if (
        bucket.window_started_at is None
        or (now - bucket.window_started_at).total_seconds() > THROTTLE_WINDOW_SECONDS
    ):
        bucket.failure_count = 1
        bucket.window_started_at = now
        bucket.locked_until = None
    else:
        bucket.failure_count = (bucket.failure_count or 0) + 1
    if bucket.failure_count >= THROTTLE_MAX_FAILURES:
        bucket.locked_until = now + timedelta(seconds=THROTTLE_WINDOW_SECONDS)
    bucket.save(
        update_fields=["failure_count", "window_started_at", "locked_until", "updated_at"]
    )
    return bucket


@transaction.atomic
def reset_auth_throttle(account: str, ip: str | None) -> None:
    digest = throttle_digest(account, ip)
    bucket = (
        AuthThrottleBucket.objects.select_for_update()
        .filter(key_digest=digest)
        .first()
    )
    if bucket is None:
        return
    bucket.failure_count = 0
    bucket.window_started_at = None
    bucket.locked_until = None
    bucket.save(
        update_fields=["failure_count", "window_started_at", "locked_until", "updated_at"]
    )


def user_is_otp_verified(request) -> bool:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    is_verified = getattr(user, "is_verified", None)
    if callable(is_verified):
        return bool(is_verified())
    return False


def require_otp_verified(request) -> None:
    if not user_is_otp_verified(request):
        _deny_sensitive(request, "otp_required")
        raise PermissionDenied("Verified OTP is required.")


def recent_reauth_age_seconds(request) -> float | None:
    raw = request.session.get(RECENT_REAUTH_KEY)
    if raw is None:
        return None
    try:
        return time.time() - float(raw)
    except (TypeError, ValueError):
        return None


def mark_recent_reauth(request) -> None:
    request.session[RECENT_REAUTH_KEY] = time.time()
    request.session.modified = True


def require_recent_auth(request, max_age_seconds: int = DEFAULT_REAUTH_MAX_AGE) -> None:
    """Require verified OTP and password+OTP re-auth within max_age_seconds."""
    if not getattr(request.user, "is_authenticated", False):
        raise PermissionDenied("Authentication required.")
    require_otp_verified(request)
    age = recent_reauth_age_seconds(request)
    if age is None or age > max_age_seconds:
        _deny_sensitive(request, "reauth_required", {"max_age_seconds": max_age_seconds})
        raise RecentAuthRequired("Recent re-authentication is required.")


def _deny_sensitive(request, reason: str, extra: dict | None = None) -> None:
    membership = None
    mid = request.session.get("active_membership_id")
    if mid is not None:
        membership = OrganizationMembership.objects.filter(
            pk=mid, user=request.user, active=True
        ).first()
    try:
        record_audit(
            request.user if getattr(request.user, "is_authenticated", False) else None,
            membership,
            "security.sensitive_action",
            "Session",
            str(getattr(request.user, "pk", "") or ""),
            "denied",
            {"reason": reason, **(extra or {})},
        )
    except Exception:
        # Audit attribution may fail for anonymous users; never block denial path.
        pass


def user_has_confirmed_totp(user) -> bool:
    from django_otp.plugins.otp_totp.models import TOTPDevice

    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def require_staff_mfa(request) -> None:
    """Privileged staff workspace entry requires a confirmed TOTP device + OTP session."""
    if not getattr(request.user, "is_authenticated", False):
        raise PermissionDenied("Authentication required.")
    if not user_has_confirmed_totp(request.user):
        raise PermissionDenied("TOTP enrollment is required for staff workspaces.")
    require_otp_verified(request)


def membership_is_tech_admin(membership: OrganizationMembership | None) -> bool:
    return (
        membership is not None
        and membership.role == OrganizationMembership.Role.TECH_ADMIN
    )


def deny_tech_admin_business_access(membership: OrganizationMembership | None) -> None:
    """Technical administrators never receive finance/document business access."""
    if membership_is_tech_admin(membership):
        raise PermissionDenied(
            "Technical administrators cannot access finance or document business routes."
        )


def active_break_glass_session(user) -> BreakGlassSession | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    now = _now()
    sessions = (
        BreakGlassSession.objects.select_related("membership", "authorizing_membership")
        .filter(
            membership__user=user,
            membership__active=True,
            membership__role=OrganizationMembership.Role.TECH_ADMIN,
            expires_at__gt=now,
        )
        .order_by("-started_at")
    )
    for session in sessions:
        if session.revocations.exists():
            continue
        return session
    return None


def is_break_glass_active(user) -> bool:
    return active_break_glass_session(user) is not None


def assert_break_glass_allows_path(request, path: str | None = None) -> None:
    """Every break-glass request is audited; business routes remain denied."""
    session = active_break_glass_session(request.user)
    if session is None:
        return
    path = path if path is not None else request.path
    try:
        record_audit(
            request.user,
            session.membership,
            "security.break_glass.request",
            "BreakGlassSession",
            str(session.pk),
            "observed",
            {"path": path, "method": request.method},
        )
    except Exception:
        pass
    for prefix in BUSINESS_ROUTE_PREFIXES:
        if path.startswith(prefix):
            raise PermissionDenied(
                "Break-glass sessions cannot access finance or document business routes."
            )


def issue_break_glass_consent(
    *,
    authorizing_membership: OrganizationMembership,
    tech_membership: OrganizationMembership,
) -> str:
    """Issue a short-lived signed consent token after the authorizer re-auths.

    Tech admins cannot self-nominate an arbitrary membership id: start_break_glass
    requires a token that proves the named authorizer approved this elevation.
    """
    if not authorizing_membership.active:
        raise ValidationError("Authorizing membership must be active.")
    if authorizing_membership.role == OrganizationMembership.Role.TECH_ADMIN:
        raise ValidationError("Authorizer must be an organization stakeholder, not tech admin.")
    if tech_membership.role != OrganizationMembership.Role.TECH_ADMIN:
        raise ValidationError("Consent target must be a technical administrator membership.")
    if not tech_membership.active:
        raise ValidationError("Technical administrator membership must be active.")
    payload = {
        "authorizer_id": authorizing_membership.pk,
        "authorizer_user_id": authorizing_membership.user_id,
        "tech_id": tech_membership.pk,
    }
    token = signing.dumps(payload, salt=BREAK_GLASS_CONSENT_SALT, compress=True)
    try:
        record_audit(
            authorizing_membership.user,
            authorizing_membership,
            "security.break_glass.consent",
            "OrganizationMembership",
            str(tech_membership.pk),
            "accepted",
            {"tech_membership_id": tech_membership.pk},
        )
    except Exception:
        pass
    return token


def validate_break_glass_consent(
    token: str,
    *,
    tech_membership: OrganizationMembership,
    authorizing_membership: OrganizationMembership,
) -> dict:
    """Validate authorizer dual-control consent; fail closed on missing/forged/expired tokens."""
    if not (token or "").strip():
        raise ValidationError(
            "Authorizer consent token is required; cannot accept bare authorizing_membership_id."
        )
    try:
        data = signing.loads(
            token.strip(),
            salt=BREAK_GLASS_CONSENT_SALT,
            max_age=BREAK_GLASS_CONSENT_MAX_AGE,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError("Authorizer consent token has expired.") from exc
    except signing.BadSignature as exc:
        raise ValidationError("Invalid authorizer consent token.") from exc
    if not isinstance(data, dict):
        raise ValidationError("Invalid authorizer consent token.")
    if int(data.get("authorizer_id", -1)) != authorizing_membership.pk:
        raise ValidationError("Consent token does not match authorizing membership.")
    if int(data.get("authorizer_user_id", -1)) != authorizing_membership.user_id:
        raise ValidationError("Consent token does not match authorizer user.")
    if int(data.get("tech_id", -1)) != tech_membership.pk:
        raise ValidationError("Consent token does not match technical administrator membership.")
    return data


def start_break_glass(
    *,
    tech_membership: OrganizationMembership,
    authorizing_membership: OrganizationMembership,
    reason: str,
    consent_token: str,
    duration_minutes: int = BREAK_GLASS_MAX_MINUTES,
) -> BreakGlassSession:
    if tech_membership.role != OrganizationMembership.Role.TECH_ADMIN:
        raise ValidationError("Break-glass requires a technical administrator membership.")
    if not tech_membership.active or not authorizing_membership.active:
        raise ValidationError("Memberships must be active.")
    if authorizing_membership.role == OrganizationMembership.Role.TECH_ADMIN:
        raise ValidationError("Authorizer must be an organization stakeholder, not tech admin.")
    if not (reason or "").strip():
        raise ValidationError("A mandatory reason is required.")
    # Dual-control: refuse free-typed authorizer ids without proof of consent.
    validate_break_glass_consent(
        consent_token,
        tech_membership=tech_membership,
        authorizing_membership=authorizing_membership,
    )
    minutes = min(max(int(duration_minutes), 1), BREAK_GLASS_MAX_MINUTES)
    now = _now()
    session = BreakGlassSession.objects.create(
        membership=tech_membership,
        reason=reason.strip(),
        authorizing_membership=authorizing_membership,
        started_at=now,
        expires_at=now + timedelta(minutes=minutes),
    )
    record_audit(
        tech_membership.user,
        tech_membership,
        "security.break_glass.start",
        "BreakGlassSession",
        str(session.pk),
        "accepted",
        {
            "authorizer_membership_id": authorizing_membership.pk,
            "expires_at": session.expires_at.isoformat(),
            "duration_minutes": minutes,
            "consent_validated": True,
        },
    )
    return session


def revoke_break_glass(
    session: BreakGlassSession,
    *,
    revoked_by,
    reason: str = "",
) -> BreakGlassRevocation:
    if session.revocations.exists():
        raise ValidationError("Break-glass session already revoked.")
    now = _now()
    if session.expires_at <= now:
        raise ValidationError("Break-glass session already expired.")
    rev = BreakGlassRevocation.objects.create(
        session=session,
        revoked_by=revoked_by,
        reason=(reason or "").strip(),
        revoked_at=now,
    )
    record_audit(
        revoked_by,
        session.membership,
        "security.break_glass.revoke",
        "BreakGlassSession",
        str(session.pk),
        "accepted",
        {"revocation_id": rev.pk},
    )
    return rev


def rotate_session(request) -> None:
    """Rotate the session key (login / MFA / reauth) without losing data."""
    try:
        request.session.cycle_key()
    except Exception:
        # Empty session edge case in tests.
        request.session.create()


def revoke_session(request) -> None:
    """Flush session (logout / explicit revocation)."""
    request.session.flush()
