"""Management session helpers: active building membership + workspace nav."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from lamto.accounts.models import ManagementMembership

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
    return resolve_active_management(request)


def nav_sections_for(membership) -> list[dict]:
    """The workspace sidebar: every destination, grouped, in one place.

    The unlabelled first section holds the two daily starting points; the
    labelled sections chunk the rest so the list stays scannable. Actions
    (New proposal, Publish announcement, Issue bill) are page buttons, not
    places, so they are deliberately absent here.
    """
    return [
        {
            "label": None,
            "items": [
                {
                    "label": _("Inbox"),
                    "url_name": "web:action-inbox",
                    "key": "inbox",
                    "icon": "inbox",
                },
                {
                    "label": _("Cases"),
                    "url_name": "web:case-list",
                    "key": "cases",
                    "icon": "wrench",
                },
            ],
        },
        {
            "label": _("Finance"),
            "items": [
                {
                    "label": _("Proposals"),
                    "url_name": "web:proposal-list",
                    "key": "proposals",
                    "icon": "doc",
                },
                {
                    "label": _("Settlements"),
                    "url_name": "web:settlement-list",
                    "key": "settlements",
                    "icon": "banknote",
                },
                {
                    "label": _("Maintenance fund"),
                    "url_name": "web:fund-home",
                    "key": "fund",
                    "icon": "columns",
                },
            ],
        },
        {
            "label": _("Building"),
            "items": [
                {
                    "label": _("Gate"),
                    "url_name": "web:gate-queue",
                    "key": "gate",
                    "icon": "door",
                },
                {
                    "label": _("Resident registrations"),
                    "url_name": "web:staff-registration-list",
                    "key": "registrations",
                    "icon": "person-add",
                },
                {
                    "label": _("Announcements"),
                    "url_name": "web:staff-announcement-list",
                    "key": "announcements",
                    "icon": "megaphone",
                },
                {
                    "label": _("Bills"),
                    "url_name": "web:staff-bill-list",
                    "key": "bills",
                    "icon": "receipt",
                },
            ],
        },
        {
            "label": _("Ops"),
            "items": [
                {
                    "label": _("Health"),
                    "url_name": "web:ops-health",
                    "key": "health",
                    "icon": "pulse",
                },
                {
                    "label": _("Exceptions"),
                    "url_name": "web:exception-list",
                    "key": "exceptions",
                    "icon": "alert",
                },
                {
                    "label": _("Metrics"),
                    "url_name": "web:pilot-metrics",
                    "key": "metrics",
                    "icon": "chart",
                },
                {
                    "label": _("Exports"),
                    "url_name": "web:export-home",
                    "key": "exports",
                    "icon": "download",
                },
            ],
        },
    ]


def gate_nav_items_for(membership) -> list[dict[str, str]]:
    """The Gate page's own sections, shown as a segmented control."""
    return [
        {"label": _("Review"), "url_name": "web:gate-queue", "active_key": "review"},
        {
            "label": _("Registrations"),
            "url_name": "web:gate-registrations",
            "active_key": "registrations",
        },
        {
            "label": _("Readers"),
            "url_name": "web:gate-devices",
            "active_key": "devices",
        },
        {"label": _("Activity"), "url_name": "web:gate-log", "active_key": "activity"},
    ]


def _current_nav_key(nav_active, extra) -> str | None:
    """Resolve a view's section keys to the one sidebar item it lives under."""
    if nav_active == "finance":
        sub = extra.get("finance_active")
        return "proposals" if sub in (None, "proposal-create") else sub
    if nav_active == "ops":
        return extra.get("ops_active") or "health"
    return nav_active


def staff_context(request, membership, memberships, *, nav_active=None, **extra):
    current = _current_nav_key(nav_active, extra)
    sections = nav_sections_for(membership)
    for section in sections:
        for item in section["items"]:
            item["is_active"] = item["key"] == current
    return {
        "membership": membership,
        "memberships": memberships,
        "membership_count": len(memberships) if memberships is not None else 0,
        "nav_sections": sections,
        "nav_active": nav_active,
        "nav_current": current,
        "gate_nav_items": gate_nav_items_for(membership),
        **extra,
    }


def switch_building_redirect(request):
    building = request.POST.get("building") or request.GET.get("building")
    membership, _memberships = resolve_active_management(request, building_id=building)
    request.session[SESSION_MANAGEMENT_KEY] = membership.pk
    return redirect("web:action-inbox")
