"""Shared staff routes: action inbox and membership switcher."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
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


logger = logging.getLogger(__name__)


def signed_action_failure(request, error, *, action, next_step):
    """Flash a task-focused recovery message; keep the raw error in server logs.

    Covers what failed, that inputs are preserved, and the next safe action.
    Backend exception text never reaches the flash for PermissionDenied.
    """
    logger.warning("%s failed: %s", action, error)
    if isinstance(error, ValidationError):
        detail = (
            error.messages[0]
            if getattr(error, "messages", None)
            else "The server rejected the submitted values."
        )
    else:
        # Typical PermissionDenied: MetaMask signed with a different account
        # than the membership's registered wallet.
        detail = "The connected wallet does not match the wallet registered for this role."
        next_step = "Connect the registered wallet and sign again."
    messages.error(
        request,
        f"{action} was not saved. {detail} "
        f"Your entries are still on this page. {next_step}",
    )


def prepare_record_list(
    request, qs, *, search_fields=(), sorts=(), page_param="page", per_page=20
):
    """Search, sort, and paginate a record list (same pattern as the action inbox).

    ``sorts``: ``((value, label, order_by_fields), ...)``; the first entry is
    the default. A numeric query also matches the record's ID.
    """
    query = (request.GET.get("q") or "").strip()
    if query:
        condition = Q()
        for field in search_fields:
            condition |= Q(**{f"{field}__icontains": query})
        if query.isdigit():
            condition |= Q(pk=int(query))
        qs = qs.filter(condition)
    sort = request.GET.get("sort") or ""
    sort_map = {value: order_by for value, _label, order_by in sorts}
    if sort not in sort_map:
        sort = ""
    if sorts:
        qs = qs.order_by(*sort_map.get(sort, sorts[0][2]))
    page = Paginator(qs, per_page).get_page(request.GET.get(page_param))
    params = request.GET.copy()
    params.pop(page_param, None)
    return {
        "page": page,
        "query": query,
        "sort": sort,
        "sort_options": [
            {"value": value, "label": label, "active": value == sort}
            for value, label, _order in sorts
        ],
        "page_param": page_param,
        "querystring": params.urlencode(),
    }


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


STAGE_STATE_LABELS = {
    "complete": "Completed",
    "current": "Current step",
    "blocked": "Blocked",
    "upcoming": "Not started",
}

# Proposal statuses that clear the proposal stage.
_PROPOSAL_APPROVED = frozenset({"NORMAL_AUTHORIZED", "EMERGENCY_EVIDENCE"})
_WORK_DONE = frozenset({"AWAITING_ACCEPTANCE", "ACCEPTED", "CLOSED"})
_WORK_CLOSED = frozenset({"ACCEPTED", "CLOSED"})


def deadline_tone(deadline_at, *, now=None) -> str:
    """Neutral by default; amber near due (48h); red when past due."""
    if deadline_at is None:
        return "neutral"
    from datetime import timedelta

    from django.utils import timezone

    now = now or timezone.now()
    if timezone.is_naive(deadline_at):
        deadline_at = timezone.make_aware(deadline_at, timezone.utc)
    if deadline_at < now:
        return "overdue"
    if deadline_at <= now + timedelta(hours=48):
        return "soon"
    return "neutral"


def accountability_chain(current: str | None, *, blocked: bool = False):
    """Return ordered stages for an explicit current key (or all-complete when None)."""
    keys = [key for key, _ in ACCOUNTABILITY_STAGES]
    if current is None:
        current_index = len(keys)
    else:
        current_index = keys.index(current)
    stages = []
    for index, (key, label) in enumerate(ACCOUNTABILITY_STAGES):
        if index == current_index and blocked:
            state = "blocked"
        elif index == current_index:
            state = "current"
        elif index < current_index:
            state = "complete"
        else:
            state = "upcoming"
        stages.append(
            {
                "key": key,
                "label": label,
                "state": state,
                "state_label": STAGE_STATE_LABELS[state],
            }
        )
    return stages


def _related_or_none(obj, attr: str):
    if obj is None:
        return None
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return getattr(obj, attr)
    except ObjectDoesNotExist:
        return None


def resolve_accountability_stage(
    source=None,
    *,
    work_order=None,
    proposal=None,
    payment=None,
    acceptance=None,
    entry=None,
    case=None,
    published: bool | None = None,
) -> tuple[str | None, bool]:
    """Derive (current_stage_key, blocked) from real case/proposal state.

    Returns ``(None, False)`` when every stage is complete (published, or a
    non-spending work order already closed). Pass ``published`` to skip the
    ledger lookup (tests and pre-resolved views).
    """
    from lamto.finance.models import PublishedLedgerEntry
    from lamto.finance.models.execution import AcceptanceRecord, PaymentEvidence
    from lamto.finance.models.proposals import Proposal
    from lamto.maintenance.models import MaintenanceCase, WorkOrder

    if source is not None:
        if isinstance(source, PublishedLedgerEntry):
            entry = source
        elif isinstance(source, PaymentEvidence):
            payment = source
        elif isinstance(source, AcceptanceRecord):
            acceptance = source
        elif isinstance(source, Proposal):
            proposal = source
        elif isinstance(source, WorkOrder):
            work_order = source
        elif isinstance(source, MaintenanceCase):
            case = source

    if entry is not None:
        return None, False

    if payment is None and acceptance is not None:
        payment = _related_or_none(acceptance, "payment")
    if acceptance is None and payment is not None:
        acceptance = getattr(payment, "acceptance", None)
    if work_order is None and acceptance is not None:
        work_order = getattr(acceptance, "work_order", None)
    if work_order is None and proposal is not None:
        work_order = getattr(proposal, "work_order", None)
    if work_order is None and payment is not None:
        acc = getattr(payment, "acceptance", None)
        work_order = getattr(acc, "work_order", None) if acc is not None else None
    if proposal is None and work_order is not None:
        proposal = _related_or_none(work_order, "proposal")
    if acceptance is None and work_order is not None:
        acceptance = _related_or_none(work_order, "acceptance")
    if payment is None and acceptance is not None:
        payment = _related_or_none(acceptance, "payment")

    if work_order is not None:
        if published is None:
            published = False
            pk = getattr(work_order, "pk", None)
            if pk is not None:
                published = PublishedLedgerEntry.objects.filter(
                    work_order_id=pk
                ).exists()
            if not published and proposal is not None and getattr(proposal, "pk", None):
                published = PublishedLedgerEntry.objects.filter(
                    proposal_id=proposal.pk
                ).exists()
            if not published and payment is not None and getattr(payment, "pk", None):
                published = PublishedLedgerEntry.objects.filter(
                    payment_id=payment.pk
                ).exists()
        if published:
            return None, False

        if payment is not None:
            return "publication", False

        status = getattr(work_order, "status", "")
        requires_spending = bool(getattr(work_order, "requires_spending", False))
        if acceptance is not None or status in _WORK_CLOSED:
            if not requires_spending:
                return None, False
            return "payment", False

        proposal_status = getattr(proposal, "status", None) if proposal else None
        approved = proposal_status in _PROPOSAL_APPROVED
        rejected = proposal_status == Proposal.Status.REJECTED or proposal_status == "REJECTED"
        if approved:
            return "acceptance", False

        if requires_spending:
            if rejected:
                return "proposal", True
            if proposal is not None or status in _WORK_DONE:
                return "proposal", False
            return "work", False

        if status == WorkOrder.Status.AWAITING_ACCEPTANCE or status == "AWAITING_ACCEPTANCE":
            return "acceptance", False
        if status == WorkOrder.Status.CANCELLED or status == "CANCELLED":
            return "work", True
        return "work", False

    if case is not None:
        latest = None
        work_orders = getattr(case, "work_orders", None)
        if work_orders is not None and hasattr(work_orders, "order_by"):
            latest = work_orders.order_by("-created_at", "-pk").first()
        if latest is not None:
            return resolve_accountability_stage(
                work_order=latest, published=published
            )
        return "work", False

    if proposal is not None:
        return resolve_accountability_stage(
            proposal=proposal,
            work_order=getattr(proposal, "work_order", None),
            published=published,
        )

    return "report", False


def accountability_chain_for(source=None, *, blocked: bool | None = None, **kwargs):
    """Compute the chain from a domain record instead of a hard-coded page stage."""
    current, derived_blocked = resolve_accountability_stage(source, **kwargs)
    return accountability_chain(
        current, blocked=derived_blocked if blocked is None else blocked
    )
