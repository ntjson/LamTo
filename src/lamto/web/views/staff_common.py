"""Shared staff routes: action inbox and membership switcher."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
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


EXCEPTION_KINDS = {"failed_outbox", "integrity_mismatch", "quarantined_upload"}
ACTION_GROUPS = (
    ("do_now", "Do now"),
    ("due_soon", "Due soon"),
    ("exceptions", "Exceptions"),
)


def _action_group(item):
    if item.kind in EXCEPTION_KINDS:
        return "exceptions"
    if item.kind == "deadline_risk":
        return "due_soon"
    return "do_now"


def prepare_action_inbox(items, *, query="", kind="", status="", page_number=1):
    query = query.strip()
    kind_filters = {}
    for item in items:
        kind_filters.setdefault(item.kind, item.title)

    filtered = [
        item
        for item in items
        if (not kind or item.kind == kind)
        and (not status or _action_group(item) == status)
        and (
            not query
            or query.casefold() in f"{item.title} {item.summary}".casefold()
        )
    ]
    page = Paginator(filtered, 20).get_page(page_number)
    grouped = {value: [] for value, _label in ACTION_GROUPS}
    for item in page.object_list:
        grouped[_action_group(item)].append(item)
    return {
        "groups": [
            {"label": label, "items": grouped[value]}
            for value, label in ACTION_GROUPS
            if grouped[value]
        ],
        "page": page,
        "kind_filters": [
            {"value": value, "label": label}
            for value, label in sorted(kind_filters.items(), key=lambda pair: pair[1])
        ],
        "active_kind": kind,
        "status_filters": [
            {"value": value, "label": label} for value, label in ACTION_GROUPS
        ],
        "active_status": status,
        "query": query,
    }


@login_required
@require_GET
def action_inbox(request):
    if not user_memberships(request.user).exists():
        raise PermissionDenied("An active staff membership is required.")
    require_staff_mfa(request)
    membership, memberships = resolve_active_membership(request)
    items = action_items_for(membership)
    inbox = prepare_action_inbox(
        items,
        query=request.GET.get("q", ""),
        kind=request.GET.get("kind", ""),
        status=request.GET.get("status", ""),
        page_number=request.GET.get("page", 1),
    )
    return render(
        request,
        "web/staff/action_inbox.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="inbox",
            action_groups=inbox["groups"],
            action_page=inbox["page"],
            kind_filters=inbox["kind_filters"],
            active_kind=inbox["active_kind"],
            status_filters=inbox["status_filters"],
            active_status=inbox["active_status"],
            inbox_query=inbox["query"],
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


ACCOUNTABILITY_STAGES = (
    ("report", "Report"),
    ("triage", "Triage"),
    ("work", "Work"),
    ("proposal", "Proposal and approval"),
    ("acceptance", "Acceptance"),
    ("payment", "Payment"),
    ("publication", "Publication"),
)


def accountability_chain(current: str, *, blocked: bool = False):
    """Return ordered accountability stages with complete/current/upcoming/blocked state."""
    current_index = [key for key, _ in ACCOUNTABILITY_STAGES].index(current)
    return [
        {
            "key": key,
            "label": label,
            "state": (
                "blocked"
                if index == current_index and blocked
                else "current"
                if index == current_index
                else "complete"
                if index < current_index
                else "upcoming"
            ),
        }
        for index, (key, label) in enumerate(ACCOUNTABILITY_STAGES)
    ]
