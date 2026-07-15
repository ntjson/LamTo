"""Staff session membership helpers.

Active membership is stored in the session and never combined across roles.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from lamto.accounts.models import CapabilityGrant, OrganizationMembership
from lamto.accounts.security import (
    deny_tech_admin_business_access,
    require_staff_mfa,
)
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit


SESSION_MEMBERSHIP_KEY = "active_membership_id"

# Navigation entries keyed by capability code.
NAV_BY_CAPABILITY = (
    (None, "Action inbox", "web:action-inbox"),
    ("report.triage", "Cases", "web:case-list"),
    ("work.assign", "Work orders", "web:work-order-list"),
    ("proposal.create", "Proposals", "web:proposal-list"),
    ("proposal.approve", "Proposals", "web:proposal-list"),
    ("payment.record", "Payments", "web:payment-list"),
    ("payment.verify", "Payments", "web:payment-list"),
    ("work.accept", "Work orders", "web:work-order-list"),
    ("ledger.publish", "Proposals", "web:proposal-list"),
    ("audit.export", "Audit search", "web:audit-search"),
)


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
            membership,
            f"workspace.{code}",
            "OrganizationMembership",
            str(membership.pk),
            "denied",
            {"capability": code},
        )
        raise
    return actor, memberships


def nav_items_for(membership) -> list[dict]:
    caps = capabilities_for(membership)
    # Maintenance role gets work-order nav even without WORK_ASSIGN.
    items = []
    seen_urls = set()
    for cap, label, url_name in NAV_BY_CAPABILITY:
        if cap is not None and cap not in caps:
            continue
        if url_name in seen_urls:
            continue
        seen_urls.add(url_name)
        items.append({"label": label, "url_name": url_name, "capability": cap})
    if (
        membership.role == OrganizationMembership.Role.MAINTENANCE
        and "web:work-order-list" not in seen_urls
    ):
        items.append(
            {
                "label": "My work",
                "url_name": "web:work-order-list",
                "capability": None,
            }
        )
    if membership.role == OrganizationMembership.Role.AUDITOR and "web:audit-search" not in seen_urls:
        items.append(
            {
                "label": "Audit search",
                "url_name": "web:audit-search",
                "capability": "audit.export",
            }
        )
    if membership.role == OrganizationMembership.Role.TECH_ADMIN:
        if "web:ops-health" not in seen_urls:
            items.append(
                {
                    "label": "Ops health",
                    "url_name": "web:ops-health",
                    "capability": "tech.admin",
                }
            )
        if "web:pilot-metrics" not in seen_urls:
            items.append(
                {
                    "label": "Pilot metrics",
                    "url_name": "web:pilot-metrics",
                    "capability": "tech.admin",
                }
            )
    if membership.role == OrganizationMembership.Role.AUDITOR and "web:audit-export" not in seen_urls:
        items.append(
            {
                "label": "Audit export",
                "url_name": "web:audit-export",
                "capability": "audit.export",
            }
        )
    fund_caps = {"fund.record", "fund.verify"}
    if caps & fund_caps and "web:fund-home" not in seen_urls:
        items.append({"label": "Fund", "url_name": "web:fund-home", "capability": "fund.record"})
    return items


def staff_context(request, membership, memberships, *, nav_active=None, **extra):
    return {
        "membership": membership,
        "memberships": memberships,
        "nav_items": nav_items_for(membership),
        "nav_active": nav_active,
        "capabilities": capabilities_for(membership),
        **extra,
    }


def switch_membership_redirect(request):
    membership_id = request.POST.get("membership") or request.GET.get("membership")
    membership, _ = resolve_active_membership(request, membership_id=membership_id)
    next_url = request.POST.get("next") or request.GET.get("next") or "/s/"
    return redirect(next_url)
