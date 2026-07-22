from datetime import timedelta

import pytest
from unittest.mock import patch
from django.utils import timezone

from lamto.audit.models import AuditEvent
from lamto.gate.models import GateDevice, GateEvent
from lamto.gate.retention import purge_expired_gate_events
from lamto.gate.enrollment import submit_face_enrollment
from lamto.gate.models import PendingEnrollmentPhoto, ReviewStatus
from django.core.files.uploadedfile import SimpleUploadedFile
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


def test_retention_boundary_deletes_whole_event_without_audit_or_reconstruction(building, management, settings):
    settings.GATE_EVENT_RETENTION_HOURS = 24
    now = timezone.now()
    device = GateDevice.objects.create(building=building, label="North", direction="ENTRY")
    old = GateEvent.objects.create(building=building, device=device, kind="PLATE", direction="ENTRY", occurred_at=now - timedelta(hours=24, microseconds=1), raw_plate_text="SECRET", normalized_plate_text="SECRET")
    fresh = GateEvent.objects.create(building=building, device=device, kind="PLATE", direction="ENTRY", occurred_at=now - timedelta(hours=24))
    assert purge_expired_gate_events(now) == 1
    assert not GateEvent.objects.filter(pk=old.pk).exists()
    assert GateEvent.objects.filter(pk=fresh.pk).exists()
    assert not AuditEvent.objects.filter(metadata__icontains="SECRET").exists()


def test_photo_delete_failure_does_not_expire_enrollment(occupancy, use_fake_embedder, gate_storage, clean_scanner):
    from lamto.gate.retention import purge_expired_enrollment_photos
    enrollment = submit_face_enrollment(occupancy, SimpleUploadedFile("f.jpg", face_bytes("resident"), content_type="image/jpeg"), scanner=clean_scanner)
    PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).update(expires_at=timezone.now() - timedelta(seconds=1))
    with patch("lamto.gate.retention.delete_pending_photo", side_effect=OSError), pytest.raises(OSError):
        purge_expired_enrollment_photos()
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.PENDING
    assert enrollment.embedding is not None
