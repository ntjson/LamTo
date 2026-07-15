"""Maintenance workspace: assigned work start/complete."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.models import OrganizationMembership
from lamto.audit.services import record_audit
from lamto.maintenance.models import WorkOrder
from lamto.maintenance.workorders import start_work_order
from lamto.web.forms.staff import CompleteWorkOrderForm
from lamto.web.staff import resolve_active_membership, staff_context


def _require_maintenance(membership):
    if membership.role != OrganizationMembership.Role.MAINTENANCE:
        # Operators with WORK_ASSIGN may also view.
        from lamto.accounts.models import CapabilityGrant
        from lamto.accounts.capabilities import WORK_ASSIGN, WORK_ACCEPT

        codes = set(
            CapabilityGrant.objects.filter(membership=membership).values_list(
                "code", flat=True
            )
        )
        if WORK_ASSIGN not in codes and WORK_ACCEPT not in codes:
            raise PermissionDenied("Maintenance or work capability required.")


@login_required
@require_GET
def work_order_list(request):
    membership, memberships = resolve_active_membership(request)
    _require_maintenance(membership)
    building_id = membership.organization.building_id
    qs = WorkOrder.objects.filter(case__building_id=building_id)
    if membership.role == OrganizationMembership.Role.MAINTENANCE:
        qs = qs.filter(assignee=request.user)
    status = request.GET.get("status") or ""
    valid_status = status in WorkOrder.Status.values
    if valid_status:
        qs = qs.filter(status=status)
    work_orders = qs.order_by("-created_at")[:100]
    items = [
        {
            "url": f"/s/work/{wo.pk}/",
            "title": f"Work order #{wo.pk}",
            "status": wo.status,
            "deadline": wo.deadline_at,
        }
        for wo in work_orders
    ]
    filters = [
        {"label": label, "value": value, "active": valid_status and value == status}
        for value, label in WorkOrder.Status.choices
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
            filters=filters,
            filters_active=valid_status,
            filter_param="status",
            empty_label="No work orders.",
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def work_order_detail(request, pk):
    membership, memberships = resolve_active_membership(request)
    _require_maintenance(membership)
    work_order = get_object_or_404(
        WorkOrder.objects.select_related("case", "assignee", "emergency_requested_by"),
        pk=pk,
        case__building_id=membership.organization.building_id,
    )
    form = CompleteWorkOrderForm(request.POST or None)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "start":
            try:
                start_work_order(work_order, request.user)
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    messages.error(request, str(error))
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
                messages.success(request, "Work started.")
                return redirect("web:work-order-detail", pk=work_order.pk)
        elif action == "complete" and form.is_valid():
            # Evidence versions must be uploaded separately; empty for now surfaces validation.
            before_ids = request.POST.getlist("before_version_ids")
            after_ids = request.POST.getlist("after_version_ids")
            from lamto.documents.models import DocumentVersion

            before = list(DocumentVersion.objects.filter(pk__in=before_ids))
            after = list(DocumentVersion.objects.filter(pk__in=after_ids))
            try:
                form.save(work_order, request.user, before, after)
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    form.add_error(None, error)
                else:
                    raise
            else:
                messages.success(request, "Work completed.")
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
        ),
    )
