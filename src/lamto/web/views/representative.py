"""Resident representative workspace: co-approval and emergency ratification."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from lamto.accounts.capabilities import PROPOSAL_APPROVE
from lamto.finance.models import EmergencyAuthorization
from lamto.web.forms.staff import EmergencyDecideForm
from lamto.accounts.security import require_recent_auth
from lamto.web.staff import require_staff_capability, staff_context
from lamto.web.views.staff_common import accountability_chain


@login_required
@require_http_methods(["GET", "POST"])
def emergency_decide(request, pk):
    membership, memberships = require_staff_capability(request, PROPOSAL_APPROVE)
    authorization = get_object_or_404(
        EmergencyAuthorization.objects.select_related("work_order__case"),
        pk=pk,
        work_order__case__building_id=membership.organization.building_id,
    )
    form = EmergencyDecideForm(request.POST or None)
    if request.method == "POST":
        require_recent_auth(request)
    if request.method == "POST" and form.is_valid():
        try:
            form.save(authorization, membership)
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Emergency outcome recorded.")
            return redirect(
                "web:work-order-detail", pk=authorization.work_order_id
            )
    return render(
        request,
        "web/staff/work_order_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="work",
            work_order=authorization.work_order,
            emergency_decide_form=form,
            list_mode=False,
            accountability_stages=accountability_chain("work"),
        ),
    )
