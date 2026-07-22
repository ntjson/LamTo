from django.contrib import messages
from django.core.files.storage import storages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.gate.devices import issue_credential, revoke_credential, rotate_credential
from lamto.gate.models import FaceEnrollment, GateDevice, GateDeviceCredential, GateEvent, PendingEnrollmentPhoto, ReviewStatus, VehiclePlate
from lamto.gate.review import approve_face, approve_plate, reject_face, reject_plate, revoke_face, revoke_plate_as_manager, ReviewNotPossible
from lamto.accounts.security import require_recent_auth
from lamto.web.staff import require_management_context, staff_context

def _context(request, membership, memberships, **extra):
    return staff_context(request, membership, memberships, nav_active="gate", **extra)

@require_GET
def gate_queue(request):
    membership, memberships = require_management_context(request)
    return render(request, "web/staff/gate_queue.html", _context(request, membership, memberships,
        pending_faces=FaceEnrollment.objects.filter(status=ReviewStatus.PENDING, occupancy__unit__building=membership.building).select_related("occupancy__user", "occupancy__unit"),
        pending_plates=VehiclePlate.objects.filter(status=ReviewStatus.PENDING, building=membership.building).select_related("occupancy__user", "occupancy__unit")))

@require_GET
def gate_face_photo(request, pk):
    membership, _ = require_management_context(request)
    photo = get_object_or_404(PendingEnrollmentPhoto, enrollment_id=pk, enrollment__occupancy__unit__building=membership.building)
    try: handle = storages["private"].open(photo.storage_key, "rb")
    except (FileNotFoundError, OSError) as error: raise Http404 from error
    return FileResponse(handle, content_type=photo.content_type)

@require_http_methods(["POST"])
def gate_face_decide(request, pk):
    membership, _ = require_management_context(request); enrollment = get_object_or_404(FaceEnrollment, pk=pk, occupancy__unit__building=membership.building)
    try:
        decision = request.POST.get("decision")
        if decision == "approve": approve_face(enrollment, membership)
        elif decision == "reject": reject_face(enrollment, membership, request.POST.get("note", ""))
        elif decision == "revoke": revoke_face(enrollment, membership)
        else: messages.error(request, "Unknown decision.")
    except ReviewNotPossible as error: messages.error(request, str(error))
    return redirect(request.POST.get("next") or "web:gate-queue")

@require_http_methods(["POST"])
def gate_plate_decide(request, pk):
    membership, _ = require_management_context(request); plate = get_object_or_404(VehiclePlate, pk=pk, building=membership.building)
    try:
        decision = request.POST.get("decision")
        if decision == "approve": approve_plate(plate, membership)
        elif decision == "reject": reject_plate(plate, membership, request.POST.get("note", ""))
        elif decision == "revoke": revoke_plate_as_manager(plate, membership)
    except ReviewNotPossible as error: messages.error(request, str(error))
    return redirect(request.POST.get("next") or "web:gate-queue")

@require_GET
def gate_registrations(request):
    membership, memberships = require_management_context(request)
    return render(request, "web/staff/gate_registrations.html", _context(request, membership, memberships,
        faces=FaceEnrollment.objects.filter(status=ReviewStatus.APPROVED, occupancy__unit__building=membership.building),
        plates=VehiclePlate.objects.filter(status=ReviewStatus.APPROVED, building=membership.building)))

@require_http_methods(["GET", "POST"])
def gate_devices(request):
    membership, memberships = require_management_context(request); issued_token = None
    if request.method == "POST":
        require_recent_auth(request)
        action = request.POST.get("action")
        if action == "create":
            device = GateDevice.objects.create(building=membership.building, label=request.POST.get("label", "").strip(), direction=request.POST.get("direction")); _, issued_token = issue_credential(device, membership)
        elif action == "rotate": _, issued_token = rotate_credential(get_object_or_404(GateDevice, pk=request.POST.get("device"), building=membership.building), membership)
        elif action == "revoke": revoke_credential(get_object_or_404(GateDeviceCredential, pk=request.POST.get("credential"), device__building=membership.building), membership)
    return render(request, "web/staff/gate_devices.html", _context(request, membership, memberships, devices=GateDevice.objects.filter(building=membership.building).prefetch_related("credentials"), directions=GateDevice.Direction.choices, issued_token=issued_token))

@require_GET
def gate_log(request):
    membership, memberships = require_management_context(request)
    return render(request, "web/staff/gate_log.html", _context(request, membership, memberships, events=GateEvent.objects.filter(building=membership.building).select_related("device", "matched_occupancy__user", "matched_occupancy__unit").order_by("-occurred_at")[:500]))
