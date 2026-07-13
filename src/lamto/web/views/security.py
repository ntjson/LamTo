"""MFA enrollment/verification, re-authentication, and break-glass support views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from lamto.accounts.mfa import (
    begin_totp_enrollment,
    confirm_totp_enrollment,
    confirmed_totp_devices,
    pending_totp_device,
    provisioning_uri,
    reauthenticate,
    revoke_totp_device,
    verify_totp_for_session,
)
from lamto.accounts.models import OrganizationMembership
from lamto.accounts.security import (
    active_break_glass_session,
    assert_not_throttled,
    client_ip,
    record_auth_failure,
    reset_auth_throttle,
    revoke_break_glass,
    revoke_session,
    rotate_session,
    start_break_glass,
    user_has_confirmed_totp,
    user_is_otp_verified,
)
from lamto.audit.services import record_audit


class SecureLoginView(LoginView):
    template_name = "web/resident/login.html"

    def form_valid(self, form):
        username = form.cleaned_data.get("username") or form.cleaned_data.get("email") or ""
        ip = client_ip(self.request)
        try:
            assert_not_throttled(username, ip)
        except PermissionDenied:
            form.add_error(None, "Too many authentication attempts. Try again later.")
            return self.form_invalid(form)

        user = form.get_user()
        login(self.request, user)
        rotate_session(self.request)
        reset_auth_throttle(username, ip)

        if user_has_confirmed_totp(user):
            self.request.session["mfa_pending_user_id"] = user.pk
            return redirect("web:mfa-verify")
        if OrganizationMembership.objects.filter(user=user, active=True).exists():
            return redirect("web:mfa-setup")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        username = self.request.POST.get("username") or self.request.POST.get("email") or ""
        ip = client_ip(self.request)
        record_auth_failure(username, ip, kind="login")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(email__iexact=username.strip()).first() if username else None
        if user is not None:
            membership = user.organizationmembership_set.filter(active=True).first()
            if membership is not None:
                try:
                    record_audit(
                        user,
                        membership,
                        "security.login.suspicious",
                        "User",
                        str(user.pk),
                        "denied",
                        {"reason": "bad_password"},
                    )
                except Exception:
                    pass
        return super().form_invalid(form)


@login_required
@require_http_methods(["GET", "POST"])
def mfa_setup(request):
    if confirmed_totp_devices(request.user).exists() and user_is_otp_verified(request):
        messages.info(request, "MFA is already configured.")
        return redirect("web:staff-home")

    device = pending_totp_device(request.user)
    if request.method == "GET" and device is None:
        device = begin_totp_enrollment(request.user)

    if request.method == "POST":
        action = request.POST.get("action") or "confirm"
        if action == "restart":
            device = begin_totp_enrollment(request.user)
        else:
            token = request.POST.get("token", "")
            try:
                confirm_totp_enrollment(request.user, token, request=request)
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages) if hasattr(error, "messages") else str(error))
            else:
                messages.success(request, "Authenticator enrolled.")
                next_url = request.POST.get("next") or request.GET.get("next") or reverse("web:staff-home")
                return redirect(next_url)
        device = pending_totp_device(request.user) or device

    return render(
        request,
        "web/security/mfa_setup.html",
        {
            "device": device,
            "config_url": provisioning_uri(device, request.user.email) if device else "",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def mfa_verify(request):
    if user_is_otp_verified(request):
        return redirect(request.GET.get("next") or reverse("web:staff-home"))
    if not confirmed_totp_devices(request.user).exists():
        return redirect("web:mfa-setup")

    if request.method == "POST":
        token = request.POST.get("token", "")
        try:
            assert_not_throttled(request.user.email, client_ip(request))
            verify_totp_for_session(request.user, token, request=request)
        except PermissionDenied as error:
            messages.error(request, str(error))
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages) if hasattr(error, "messages") else str(error))
        else:
            messages.success(request, "MFA verified.")
            next_url = request.POST.get("next") or request.GET.get("next") or reverse("web:staff-home")
            return redirect(next_url)

    return render(request, "web/security/mfa_setup.html", {"verify_only": True})


@login_required
@require_http_methods(["GET", "POST"])
def reauth(request):
    next_url = request.GET.get("next") or request.POST.get("next") or reverse("web:staff-home")
    if request.method == "POST":
        password = request.POST.get("password", "")
        token = request.POST.get("token", "")
        try:
            assert_not_throttled(request.user.email, client_ip(request))
            reauthenticate(request.user, password, token, request=request)
        except PermissionDenied as error:
            messages.error(request, str(error))
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages) if hasattr(error, "messages") else str(error))
        else:
            messages.success(request, "Re-authentication successful.")
            return redirect(next_url)
    return render(request, "web/security/reauth.html", {"next": next_url})


@login_required
@require_POST
def mfa_revoke_device(request, device_id: int):
    try:
        revoke_totp_device(request.user, device_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Authenticator device revoked.")
        revoke_session(request)
        return redirect("login")
    return redirect("web:mfa-setup")


@login_required
@require_http_methods(["GET", "POST"])
def break_glass_start_view(request):
    tech = (
        OrganizationMembership.objects.filter(
            user=request.user,
            active=True,
            role=OrganizationMembership.Role.TECH_ADMIN,
        )
        .select_related("organization")
        .first()
    )
    if tech is None:
        raise PermissionDenied("Technical administrator membership required.")
    if request.method == "POST":
        reason = request.POST.get("reason", "")
        authorizer_id = request.POST.get("authorizing_membership_id")
        try:
            authorizer = OrganizationMembership.objects.get(pk=int(authorizer_id), active=True)
            start_break_glass(
                tech_membership=tech,
                authorizing_membership=authorizer,
                reason=reason,
                duration_minutes=int(request.POST.get("duration_minutes") or 60),
            )
        except (ValidationError, OrganizationMembership.DoesNotExist, TypeError, ValueError) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Break-glass session started.")
            return redirect("web:ops-health")
    authorizers = OrganizationMembership.objects.filter(active=True).exclude(
        role=OrganizationMembership.Role.TECH_ADMIN
    )[:100]
    return render(
        request,
        "web/security/reauth.html",
        {
            "break_glass": True,
            "authorizers": authorizers,
            "active_session": active_break_glass_session(request.user),
        },
    )


@login_required
@require_POST
def break_glass_revoke_view(request, session_id: int):
    from lamto.accounts.models import BreakGlassSession

    session = BreakGlassSession.objects.filter(pk=session_id).first()
    if session is None or session.membership.user_id != request.user.pk:
        raise PermissionDenied("Unknown break-glass session.")
    try:
        revoke_break_glass(session, revoked_by=request.user, reason=request.POST.get("reason", ""))
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Break-glass session revoked.")
    return redirect("web:ops-health")


@require_POST
def secure_logout(request):
    if request.user.is_authenticated:
        membership = request.user.organizationmembership_set.filter(active=True).first()
        if membership is not None:
            try:
                record_audit(
                    request.user,
                    membership,
                    "security.logout",
                    "Session",
                    str(request.user.pk),
                    "accepted",
                    {},
                )
            except Exception:
                pass
    logout(request)
    revoke_session(request)
    return redirect("login")
