"""Staff session membership helpers.

Active membership is stored in the session and never combined across roles.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from lamto.accounts.models import ManagementMembership
from lamto.accounts.security import require_staff_mfa
from lamto.accounts.services import require_management


SESSION_MEMBERSHIP_KEY = "active_membership_id"


def membership_building(membership):
    return membership.building


def membership_building_id(membership):
    return membership_building(membership).pk


def user_memberships(user):
    return ManagementMembership.objects.select_related("building").filter(
        user=user, active=True
    ).order_by("building__name", "pk")


def capabilities_for(_membership) -> set[str]:
    return set()


def resolve_active_membership(request, *, membership_id=None):
    """Resolve and pin the active membership for this request.

    Priority: explicit query/form membership_id → session → sole membership.
    """
    memberships = list(user_memberships(request.user))
    if not memberships:
        raise PermissionDenied("An active staff membership is required.")

    candidate_id = membership_id
    if candidate_id is None:
        candidate_id = request.GET.get("membership") or request.POST.get("membership")
    if candidate_id is None:
        candidate_id = request.session.get(SESSION_MEMBERSHIP_KEY)

    selected = None
    if candidate_id is not None:
        try:
            cid = int(candidate_id)
        except (TypeError, ValueError):
            cid = None
        if cid is not None:
            selected = next((m for m in memberships if m.pk == cid), None)

    if selected is None:
        if len(memberships) == 1:
            selected = memberships[0]
        else:
            # Prefer session-valid; otherwise first membership and require switcher UI.
            selected = memberships[0]

    request.session[SESSION_MEMBERSHIP_KEY] = selected.pk
    return selected, memberships


def require_staff_capability(request, code: str, *, membership_id=None):
    require_staff_mfa(request)
    membership, memberships = resolve_active_membership(
        request, membership_id=membership_id
    )
    return require_management(request.user, membership.building_id), memberships


def nav_items_for(membership) -> list[dict]:
    """The six Management workspace areas."""
    return [
        {
            "label": _("Inbox"),
            "url_name": "web:action-inbox",
            "capability": None,
            "active_key": "inbox",
        },
        {
            "label": _("Cases"),
            "url_name": "web:case-list",
            "capability": None,
            "active_key": "cases",
        },
        {
            "label": _("Work"),
            "url_name": "web:work-order-list",
            "capability": None,
            "active_key": "work",
        },
        {
            "label": _("Finance"),
            "url_name": "web:proposal-list",
            "capability": None,
            "active_key": "finance",
        },
        {
            "label": _("Audit"),
            "url_name": "web:audit-search",
            "capability": None,
            "active_key": "audit",
        },
        {
            "label": _("Ops"),
            "url_name": "web:ops-health",
            "capability": None,
            "active_key": "ops",
        },
    ]

def finance_nav_items_for(membership) -> list[dict[str, str]]:
    return [
        {"label": _("Proposals"), "url_name": "web:proposal-list", "active_key": "proposals"},
        {"label": _("Payments"), "url_name": "web:payment-list", "active_key": "payments"},
        {"label": _("Fund"), "url_name": "web:fund-home", "active_key": "fund"},
    ]


def staff_context(request, membership, memberships, *, nav_active=None, **extra):
    from lamto.web.views.staff_common import pop_sign_confirmation

    nav_items = nav_items_for(membership)
    for item in nav_items:
        item["is_active"] = bool(nav_active) and item.get("active_key") == nav_active
    sign_confirmation = pop_sign_confirmation(request)
    return {
        "membership": membership,
        "memberships": memberships,
        "membership_count": len(memberships) if memberships is not None else 0,
        "nav_items": nav_items,
        "nav_active": nav_active,
        "finance_nav_items": finance_nav_items_for(membership),
        "capabilities": capabilities_for(membership),
        "sign_confirmation": sign_confirmation,
        **extra,
    }


def switch_membership_redirect(request):
    membership_id = request.POST.get("membership") or request.GET.get("membership")
    membership, _ = resolve_active_membership(request, membership_id=membership_id)
    request.session[SESSION_MEMBERSHIP_KEY] = membership.pk
    return redirect("web:action-inbox")
