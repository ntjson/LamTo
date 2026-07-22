from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import PendingEnrollmentPhoto, ReviewStatus, VehiclePlate
from .photos import delete_pending_photo


class ReviewNotPermitted(PermissionDenied):
    pass


class ReviewNotPossible(ValueError):
    pass


def _assert_manages(membership, building_id):
    if membership.building_id != building_id or not membership.active:
        raise ReviewNotPermitted("Registration belongs to another building.")


def _drop_photo(enrollment):
    photo = PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).first()
    if photo:
        delete_pending_photo(photo.storage_key, photo.provider_version_id)
        photo.delete()


def approve_face(enrollment, membership):
    _assert_manages(membership, enrollment.occupancy.unit.building_id)
    if enrollment.status != ReviewStatus.PENDING:
        raise ReviewNotPossible("Only a pending enrolment can be approved.")
    if not PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).exists():
        raise ReviewNotPossible("The review photo has expired; the resident must resubmit.")
    with transaction.atomic():
        enrollment.status = ReviewStatus.APPROVED
        enrollment.reviewed_by = membership.user
        enrollment.reviewed_at = timezone.now()
        enrollment.review_note = ""
        enrollment.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
        _drop_photo(enrollment)
    return enrollment


def _close_face(enrollment, membership, note):
    with transaction.atomic():
        enrollment.status = ReviewStatus.REJECTED
        enrollment.embedding = None
        enrollment.reviewed_by = membership.user
        enrollment.reviewed_at = timezone.now()
        enrollment.review_note = note[:255]
        enrollment.save(update_fields=["status", "embedding", "reviewed_by", "reviewed_at", "review_note"])
        _drop_photo(enrollment)
    return enrollment


def reject_face(enrollment, membership, note):
    _assert_manages(membership, enrollment.occupancy.unit.building_id)
    if not (note or "").strip():
        raise ReviewNotPossible("A rejection reason is required.")
    if enrollment.status not in {ReviewStatus.PENDING, ReviewStatus.APPROVED}:
        raise ReviewNotPossible("This enrolment has already been closed.")
    return _close_face(enrollment, membership, note.strip())


def revoke_face(enrollment, membership):
    _assert_manages(membership, enrollment.occupancy.unit.building_id)
    return _close_face(enrollment, membership, "Revoked by management.")


def approve_plate(plate, membership):
    _assert_manages(membership, plate.building_id)
    if plate.status == ReviewStatus.APPROVED:
        return plate
    if VehiclePlate.objects.filter(building_id=plate.building_id, plate=plate.plate, status=ReviewStatus.APPROVED).exclude(pk=plate.pk).exists():
        raise ReviewNotPossible("Another resident already holds this plate in this building.")
    plate.status = ReviewStatus.APPROVED
    plate.reviewed_by = membership.user
    plate.reviewed_at = timezone.now()
    plate.review_note = ""
    plate.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    return plate


def reject_plate(plate, membership, note):
    _assert_manages(membership, plate.building_id)
    if not (note or "").strip():
        raise ReviewNotPossible("A rejection reason is required.")
    plate.status = ReviewStatus.REJECTED
    plate.reviewed_by = membership.user
    plate.reviewed_at = timezone.now()
    plate.review_note = note.strip()[:255]
    plate.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    return plate


def revoke_plate_as_manager(plate, membership):
    return reject_plate(plate, membership, "Revoked by management.")
