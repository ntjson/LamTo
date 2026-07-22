import pytest
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile

from lamto.accounts.models import Building, ManagementMembership, User
from lamto.gate.enrollment import submit_face_enrollment, submit_plate
from lamto.gate.models import PendingEnrollmentPhoto, ReviewStatus, VehiclePlate
from lamto.gate.review import ReviewNotPermitted, ReviewNotPossible, approve_face, approve_plate, reject_face, reject_plate, revoke_face
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


def _enrol(occupancy, clean_scanner, seed="nguyen"):
    return submit_face_enrollment(occupancy, SimpleUploadedFile("f.jpg", face_bytes(seed), content_type="image/jpeg"), scanner=clean_scanner)


def test_approving_a_face_keeps_the_vector_and_deletes_the_photo(occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    enrollment = _enrol(occupancy, clean_scanner)
    approve_face(enrollment, management)
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.APPROVED
    assert enrollment.embedding is not None
    assert enrollment.reviewed_by_id == management.user_id
    assert enrollment.reviewed_at is not None
    assert not PendingEnrollmentPhoto.objects.exists()


def test_rejecting_a_face_deletes_the_vector_and_keeps_the_reason(occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    enrollment = _enrol(occupancy, clean_scanner)
    reject_face(enrollment, management, "Face not clearly visible.")
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.REJECTED
    assert enrollment.embedding is None
    assert enrollment.review_note == "Face not clearly visible."
    assert not PendingEnrollmentPhoto.objects.exists()


def test_photo_delete_failure_rolls_back_review_decision(occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    enrollment = _enrol(occupancy, clean_scanner)
    with patch("lamto.gate.review.delete_pending_photo", side_effect=OSError), pytest.raises(OSError):
        approve_face(enrollment, management)
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.PENDING
    assert PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).exists()


def test_rejecting_requires_a_reason(occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    with pytest.raises(ReviewNotPossible):
        reject_face(_enrol(occupancy, clean_scanner), management, "   ")


def test_a_face_cannot_be_approved_once_the_photo_is_gone(occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    enrollment = _enrol(occupancy, clean_scanner)
    PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).delete()
    with pytest.raises(ReviewNotPossible):
        approve_face(enrollment, management)


def test_a_manager_from_another_building_cannot_decide(occupancy, use_fake_embedder, gate_storage, clean_scanner):
    other_building = Building.objects.create(name="Other Building")
    outsider = ManagementMembership.objects.create(user=User.objects.create(email="out@example.com", display_name="Out"), building=other_building)
    with pytest.raises(ReviewNotPermitted):
        approve_face(_enrol(occupancy, clean_scanner), outsider)


def test_revoking_an_approved_face_deletes_the_vector(occupancy, management, use_fake_embedder, gate_storage, clean_scanner):
    enrollment = _enrol(occupancy, clean_scanner)
    approve_face(enrollment, management)
    revoke_face(enrollment, management)
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.REJECTED
    assert enrollment.embedding is None


def test_approving_a_plate_marks_it_and_attributes_the_decision(occupancy, management):
    plate = submit_plate(occupancy, "51F12345")
    approve_plate(plate, management)
    plate.refresh_from_db()
    assert plate.status == ReviewStatus.APPROVED
    assert plate.reviewed_by_id == management.user_id


def test_approving_a_plate_another_resident_already_holds_fails(occupancy, second_occupancy, management):
    approve_plate(submit_plate(second_occupancy, "51F12345"), management)
    clash = VehiclePlate.objects.create(occupancy=occupancy, building=occupancy.unit.building, plate="51F12345")
    with pytest.raises(ReviewNotPossible):
        approve_plate(clash, management)


def test_rejecting_a_plate_records_the_reason(occupancy, management):
    plate = submit_plate(occupancy, "51F12345")
    reject_plate(plate, management, "Not a resident vehicle.")
    plate.refresh_from_db()
    assert plate.status == ReviewStatus.REJECTED
    assert plate.review_note == "Not a resident vehicle."
