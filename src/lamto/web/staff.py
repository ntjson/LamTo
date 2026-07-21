"""Management session helpers: active building membership + workspace nav."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from lamto.accounts.models import ManagementMembership
from lamto.accounts.security import require_staff_mfa

SESSION_MANAGEMENT_KEY = "active_management_id"


def user_memberships(user):
    return (
        ManagementMembership.objects.select_related("building")
        .filter(user=user, active=True)
        .order_by("building__name", "pk")
    )


def resolve_active_management(request, *, building_id=None):
    memberships = list(user_memberships(request.user))
    if not memberships:
        raise PermissionDenied("An active management membership is required.")

    candidate = building_id
    if candidate is None:
        candidate = request.GET.get("building") or request.POST.get("building")
    if candidate is None:
        candidate = request.session.get(SESSION_MANAGEMENT_KEY)

    selected = None
    if candidate is not None:
        try:
            cid = int(candidate)
        except (TypeError, ValueError):
            cid = None
        if cid is not None:
            selected = next((m for m in memberships if m.pk == cid), None)
    if selected is None:
        selected = memberships[0]

    request.session[SESSION_MANAGEMENT_KEY] = selected.pk
    return selected, memberships


def require_management_context(request):
    require_staff_mfa(request)
    return resolve_active_management(request)


def nav_items_for(membership) -> list[dict]:
    return [
        {"label": _("Inbox"), "url_name": "web:action-inbox", "active_key": "inbox"},
        {"label": _("Cases"), "url_name": "web:case-list", "active_key": "cases"},
        {"label": _("Finance"), "url_name": "web:proposal-list", "active_key": "finance"},
        {"label": _("Exports"), "url_name": "web:audit-export", "active_key": "exports"},
        {"label": _("Ops"), "url_name": "web:ops-health", "active_key": "ops"},
    ]


def finance_nav_items_for(membership) -> list[dict[str, str]]:
    return [
        {"label": _("Proposals"), "url_name": "web:proposal-list", "active_key": "proposals"},
        {"label": _("Settlements"), "url_name": "web:settlement-list", "active_key": "settlements"},
        {"label": _("Fund"), "url_name": "web:fund-home", "active_key": "fund"},
    ]


def staff_context(request, membership, memberships, *, nav_active=None, **extra):
    from lamto.web.views.staff_common import pop_sign_confirmation

    nav_items = nav_items_for(membership)
    for item in nav_items:
        item["is_active"] = bool(nav_active) and item.get("active_key") == nav_active
    return {
        "membership": membership,
        "memberships": memberships,
        "membership_count": len(memberships) if memberships is not None else 0,
        "nav_items": nav_items,
        "nav_active": nav_active,
        "finance_nav_items": finance_nav_items_for(membership),
        "sign_confirmation": pop_sign_confirmation(request),
        **extra,
    }


def switch_building_redirect(request):
    building = request.POST.get("building") or request.GET.get("building")
    membership, _memberships = resolve_active_management(request, building_id=building)
    request.session[SESSION_MANAGEMENT_KEY] = membership.pk
    return redirect("web:action-inbox")
