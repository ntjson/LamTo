"""Staff session membership helpers.

Active membership is stored in the session and never combined across roles.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from lamto.accounts.models import CapabilityGrant, OrganizationMembership
from lamto.accounts.security import (
    deny_tech_admin_business_access,
    require_staff_mfa,
)
from lamto.accounts.services import require_capability, require_management
from lamto.audit.services import record_audit


SESSION_MEMBERSHIP_KEY = "active_membership_id"


def user_memberships(user):
    return (
        OrganizationMembership.objects.select_related("organization", "organization__building")
        .filter(user=user, active=True)
        .order_by("organization__building__name", "role", "pk")
    )


def capabilities_for(membership) -> set[str]:
    if membership is None:
        return set()
    return set(
        CapabilityGrant.objects.filter(membership=membership).values_list(
            "code", flat=True
        )
    )


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
    # Technical admins never receive finance/document business capabilities.
    if code != "tech.admin":
        deny_tech_admin_business_access(membership)
    try:
        actor = require_capability(request.user, membership.pk, code)
    except PermissionDenied:
        record_audit(
            request.user,
            require_management(request.user, membership.organization.building_id),
            f"workspace.{code}",
            "OrganizationMembership",
            str(membership.pk),
            "denied",
            {"capability": code},
        )
        raise
    return actor, memberships


def nav_items_for(membership) -> list[dict]:
    """Six active capability-filtered areas (spec 4.2 Phase-0): Inbox · Cases ·
    Work · Finance (proposals · payments · fund) · Audit · Ops.
    Ledger (seventh area) is deferred — not in this nav."""
    caps = capabilities_for(membership)
    role = membership.role
    Role = OrganizationMembership.Role
    items: list[dict] = [
        {
            "label": _("Inbox"),
            "url_name": "web:action-inbox",
            "capability": None,
            "active_key": "inbox",
        }
    ]

    if "report.triage" in caps:
        items.append(
            {
                "label": _("Cases"),
                "url_name": "web:case-list",
                "capability": "report.triage",
                "active_key": "cases",
            }
        )

    # Work: operators (assign), board acceptors (accept), and maintenance.
    # Preserves the pre-Plan-4 behavior where work.accept also surfaced Work.
    if caps & {"work.assign", "work.accept"} or role == Role.MAINTENANCE:
        maintenance_only = role == Role.MAINTENANCE and not (
            caps & {"work.assign", "work.accept"}
        )
        items.append(
            {
                "label": _("My work") if maintenance_only else _("Work"),
                "url_name": "web:work-order-list",
                "capability": None,
                "active_key": "work",
            }
        )

    # Finance groups proposals · payments · fund; appears once, landing on the
    # first sub-area the membership can open.
    finance_caps = {
        "proposal.create", "ledger.publish",
        "payment.record", "payment.verify", "fund.record", "fund.verify",
    }
    if caps & finance_caps:
        if caps & {"proposal.create", "ledger.publish"}:
            finance_url = "web:proposal-list"
        elif caps & {"payment.record", "payment.verify"}:
            finance_url = "web:payment-list"
        else:
            finance_url = "web:fund-home"
        items.append(
            {
                "label": _("Finance"),
                "url_name": finance_url,
                "capability": None,
                "active_key": "finance",
            }
        )

    if role == Role.AUDITOR or "audit.export" in caps:
        items.append(
            {
                "label": _("Audit"),
                "url_name": "web:audit-search",
                "capability": "audit.export",
                "active_key": "audit",
            }
        )

    if role == Role.TECH_ADMIN:
        items.append(
            {
                "label": _("Ops"),
                "url_name": "web:ops-health",
                "capability": "tech.admin",
                "active_key": "ops",
            }
        )

    return items




def finance_nav_items_for(membership) -> list[dict[str, str]]:
    caps = capabilities_for(membership)
    destinations = (
        (_("Proposals"), "web:proposal-list", "proposals", {"proposal.create", "ledger.publish"}),
        (_("Payments"), "web:payment-list", "payments", {"payment.record", "payment.verify"}),
        (_("Fund"), "web:fund-home", "fund", {"fund.record", "fund.verify", "ledger.publish"}),
    )
    return [
        {"label": label, "url_name": url_name, "active_key": active_key}
        for label, url_name, active_key, required in destinations
        if caps & required
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
