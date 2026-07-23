from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from lamto.accounts.models import RegistrationRequest
from lamto.accounts.registration import (
    RegistrationConflict,
    approve_registration,
    reject_registration,
)
from lamto.web.staff import require_management_context, staff_context


def _detail_response(request, membership, memberships, registration):
    return render(
        request,
        "web/staff/registrations/detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="registrations",
            registration=registration,
        ),
    )


@login_required
@require_GET
def registration_list(request):
    membership, memberships = require_management_context(request)
    registrations = RegistrationRequest.objects.filter(
        building_id=membership.building_id,
        status=RegistrationRequest.Status.PENDING,
    ).select_related("unit", "building").order_by("created_at")
    return render(
        request,
        "web/staff/registrations/list.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="registrations",
            registrations=registrations,
        ),
    )


@login_required
@require_GET
def registration_detail(request, request_id):
    membership, memberships = require_management_context(request)
    registration = get_object_or_404(
        RegistrationRequest.objects.filter(
            building_id=membership.building_id
        ).select_related("building", "unit"),
        pk=request_id,
    )
    return _detail_response(request, membership, memberships, registration)


@login_required
@require_POST
def registration_approve(request, request_id):
    membership, _memberships = require_management_context(request)
    try:
        approve_registration(request_id=request_id, actor=request.user)
    except RegistrationConflict:
        messages.error(request, "This registration has already been decided.")
        return redirect("web:staff-registration-detail", request_id)
    messages.success(request, "Registration approved.")
    return redirect("web:staff-registration-list")


@login_required
@require_POST
def registration_reject(request, request_id):
    membership, memberships = require_management_context(request)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Rejection reason is required.")
        registration = get_object_or_404(
            RegistrationRequest.objects.filter(
                building_id=membership.building_id
            ).select_related("building", "unit"),
            pk=request_id,
        )
        return _detail_response(request, membership, memberships, registration)
    try:
        reject_registration(request_id=request_id, actor=request.user, reason=reason)
    except RegistrationConflict:
        messages.error(request, "This registration has already been decided.")
        return redirect("web:staff-registration-detail", request_id)
    messages.success(request, "Registration rejected.")
    return redirect("web:staff-registration-list")
