"""Maintenance workspace: assigned work start/complete."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.audit.services import record_audit
from lamto.maintenance.models import WorkOrder
from lamto.maintenance.workorders import start_work_order
from lamto.web.forms.staff import CompleteWorkOrderForm
from lamto.web.staff import require_management_context, staff_context
from lamto.web.views.staff_common import accountability_chain_for, prepare_record_list


def _require_maintenance(membership):
    return membership


@login_required
@require_GET
def work_order_list(request):
    membership, memberships = require_management_context(request)
    _require_maintenance(membership)
    building_id = membership.building_id
    qs = WorkOrder.objects.filter(case__building_id=building_id).select_related("case")
    status = request.GET.get("status") or ""
    status_groups = {
        "active": (WorkOrder.Status.ASSIGNED, WorkOrder.Status.IN_PROGRESS),
        "acceptance": (WorkOrder.Status.AWAITING_ACCEPTANCE,),
        "done": (WorkOrder.Status.ACCEPTED, WorkOrder.Status.CLOSED, WorkOrder.Status.CANCELLED),
    }
    valid_status = status in WorkOrder.Status.values
    active_group = status if status in status_groups else next(
        (group for group, values in status_groups.items() if status in values), ""
    )
    if status in status_groups:
        qs = qs.filter(status__in=status_groups[status])
    elif valid_status:
        qs = qs.filter(status=status)
    list_meta = prepare_record_list(
        request,
        qs,
        search_fields=("case__category", "assignee__display_name"),
        sorts=(
            ("", "Newest first", ("-created_at",)),
            ("deadline", "Deadline soonest", ("deadline_at",)),
        ),
    )
    next_actions = {
        WorkOrder.Status.ASSIGNED: "Start work",
        WorkOrder.Status.IN_PROGRESS: "Complete work",
        WorkOrder.Status.AWAITING_ACCEPTANCE: "Accept completed work",
        WorkOrder.Status.ACCEPTED: "Record payment",
    }
    from lamto.web.views.staff_common import deadline_tone

    items = [
        {
            "url": f"/s/work/{wo.pk}/",
            "title": f"Work order #{wo.pk} · {wo.case.category}",
            "status": wo.get_status_display(),
            "deadline": wo.deadline_at,
            "deadline_tone": deadline_tone(wo.deadline_at),
            "next_action": next_actions.get(wo.status, ""),
        }
        for wo in list_meta["page"].object_list
    ]
    filters = [
        {"label": label, "value": value, "active": value == active_group}
        for value, label in (
            ("active", "Active"),
            ("acceptance", "Awaiting acceptance"),
            ("done", "Done"),
        )
    ]
    return render(
        request,
        "web/staff/work_order_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="work",
            list_mode=True,
            items=items,
            list_meta=list_meta,
            search_label="Search work orders",
            filters=filters,
            filters_active=valid_status or status in status_groups,
            filter_param="status",
            empty_label="No work orders.",
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def work_order_detail(request, pk):
    membership, memberships = require_management_context(request)
    _require_maintenance(membership)
    work_order = get_object_or_404(
        WorkOrder.objects.select_related("case", "assignee"),
        pk=pk,
        case__building_id=membership.building_id,
    )
    form = CompleteWorkOrderForm(
        request.POST or None,
        building_id=membership.building_id,
        uploader_id=request.user.pk,
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "start":
            try:
                start_work_order(work_order, request.user)
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    detail = (
                        error.messages[0]
                        if getattr(error, "messages", None)
                        else "The work order is not in a startable state."
                    )
                    messages.error(
                        request,
                        f"Work was not started. {detail} "
                        "Nothing was changed — review the status and try again.",
                    )
                else:
                    raise
            else:
                record_audit(
                    request.user,
                    membership,
                    "workspace.work.start",
                    "WorkOrder",
                    str(work_order.pk),
                    "accepted",
                )
                messages.success(
                    request,
                    "Work started. Complete it and link the before/after photos when done.",
                )
                return redirect("web:work-order-detail", pk=work_order.pk)
        elif action == "complete" and form.is_valid():
            try:
                form.save(work_order, request.user)
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    form.add_error(None, error)
                else:
                    raise
            else:
                messages.success(
                    request,
                    "Work completed. The Board reviews and accepts the finished work next.",
                )
                return redirect("web:work-order-detail", pk=work_order.pk)

    return render(
        request,
        "web/staff/work_order_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="work",
            list_mode=False,
            work_order=work_order,
            form=form,
            is_assignee=work_order.assignee_id == request.user.pk,
            accountability_stages=accountability_chain_for(work_order),
        ),
    )
