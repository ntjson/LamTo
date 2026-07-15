"""Shared staff routes: action inbox and membership switcher."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from lamto.accounts.security import require_staff_mfa
from lamto.web.action_inbox import action_items_for
from lamto.web.staff import (
    SESSION_MEMBERSHIP_KEY,
    resolve_active_membership,
    staff_context,
    user_memberships,
)


@login_required
@require_GET
def action_inbox(request):
    if not user_memberships(request.user).exists():
        raise PermissionDenied("An active staff membership is required.")
    require_staff_mfa(request)
    membership, memberships = resolve_active_membership(request)
    items = action_items_for(membership)
    return render(
        request,
        "web/staff/action_inbox.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="inbox",
            action_items=items,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def switch_membership(request):
    membership_id = request.POST.get("membership") or request.GET.get("membership")
    if membership_id is None:
        raise PermissionDenied("membership is required")
    membership, _ = resolve_active_membership(request, membership_id=membership_id)
    request.session[SESSION_MEMBERSHIP_KEY] = membership.pk
    return redirect("web:action-inbox")


@login_required
@require_GET
def staff_home(request):
    return redirect("web:action-inbox")
