import hashlib
from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    RegistrationRequest,
    ResidentOccupancy,
    Unit,
    User,
)
from lamto.accounts.registration import (
    RegistrationConflict,
    approve_registration,
    expire_registration_requests,
    get_registration_status,
    reject_registration,
    submit_registration,
)
from lamto.audit.models import AuditEvent


@pytest.fixture
def unit(db):
    building = Building.objects.create(name="Tower A")
    return Unit.objects.create(building=building, label="101")


def submit(unit, **overrides):
    values = {
        "full_name": "  Nguyễn Văn An  ",
        "phone": "090 123 4567",
        "email": " AN@example.com ",
        "password": "correct horse battery staple",
        "building_id": unit.building_id,
        "unit_id": unit.id,
    }
    values.update(overrides)
    return submit_registration(**values)


@pytest.fixture
def manager(unit):
    user = User.objects.create_user(email="manager@example.com", password="secret")
    ManagementMembership.objects.create(user=user, building=unit.building)
    return user


def test_manager_approves_registration_atomically(unit, manager):
    request = submit(unit).request
    password_hash = request.password_hash

    user = approve_registration(request_id=request.id, actor=manager)

    request.refresh_from_db()
    assert request.status == RegistrationRequest.Status.APPROVED
    assert request.decided_by == manager
    assert request.decided_at is not None
    assert request.password_hash == ""
    assert user.password == password_hash
    assert user.display_name == "Nguyễn Văn An"
    assert (
        ResidentOccupancy.objects.filter(user=user, unit=unit, active=True).count()
        == 1
    )
    event = AuditEvent.objects.get(action="registration.approved")
    assert event.membership.user == manager
    assert event.target_type == "RegistrationRequest"
    assert set(event.metadata) == {"building_id", "unit_id"}


def test_manager_from_another_building_cannot_decide(unit):
    other = Building.objects.create(name="Tower B")
    manager = User.objects.create_user(email="manager@example.com", password="secret")
    ManagementMembership.objects.create(user=manager, building=other)

    with pytest.raises(PermissionDenied):
        approve_registration(request_id=submit(unit).request.id, actor=manager)


def test_rejection_requires_reason_and_clears_secret(unit, manager):
    request = submit(unit).request
    with pytest.raises(ValueError):
        reject_registration(request_id=request.id, actor=manager, reason=" ")

    reject_registration(request_id=request.id, actor=manager, reason=" Not a resident ")

    request.refresh_from_db()
    assert request.status == RegistrationRequest.Status.REJECTED
    assert request.rejection_reason == "Not a resident"
    assert request.password_hash == ""
    event = AuditEvent.objects.get(action="registration.rejected")
    assert event.metadata == {
        "building_id": unit.building_id,
        "unit_id": unit.id,
        "reason": "Not a resident",
    }


def test_second_decision_conflicts(unit, manager):
    request = submit(unit).request
    reject_registration(request_id=request.id, actor=manager, reason="Duplicate")

    with pytest.raises(RegistrationConflict):
        approve_registration(request_id=request.id, actor=manager)


def test_approval_user_conflict_rolls_back(unit, manager):
    request = submit(unit).request
    User.objects.create_user(phone="0901234567", password="existing")

    with pytest.raises(RegistrationConflict):
        approve_registration(request_id=request.id, actor=manager)

    request.refresh_from_db()
    assert request.status == RegistrationRequest.Status.PENDING
    assert User.objects.filter(phone=request.phone).count() == 0
    assert not ResidentOccupancy.objects.filter(
        unit=request.unit, user__phone=request.phone
    ).exists()


def test_expiry_clears_hash_and_records_decision_time(unit):
    request = submit(unit).request
    now = timezone.now()
    RegistrationRequest.objects.filter(pk=request.pk).update(expires_at=now)

    assert expire_registration_requests(now=now) == 1

    request.refresh_from_db()
    assert request.status == RegistrationRequest.Status.EXPIRED
    assert request.password_hash == ""
    assert request.decided_at == now


def test_submit_registration_hashes_secrets_and_normalizes_values(unit):
    submission = submit(unit)
    request = submission.request

    assert request.full_name == "Nguyễn Văn An"
    assert request.phone == "+84901234567"
    assert request.email == "an@example.com"
    assert request.status_token_digest == hashlib.sha256(
        submission.status_token.encode()
    ).hexdigest()
    assert submission.status_token not in request.status_token_digest
    assert check_password("correct horse battery staple", request.password_hash)
    assert abs(request.expires_at - request.created_at - timedelta(days=30)) < timedelta(
        seconds=2
    )


def test_submit_registration_accepts_phone_only_resident(unit):
    assert submit(unit, email=" ").request.email is None


def test_submission_repr_does_not_expose_status_token(unit):
    submission = submit(unit)

    assert submission.status_token not in repr(submission)


def test_unit_must_belong_to_building(unit):
    other_building = Building.objects.create(name="Tower B")

    with pytest.raises(RegistrationConflict):
        submit(unit, building_id=other_building.id)


def test_composite_fk_rejects_direct_cross_building_write(unit):
    other_building = Building.objects.create(name="Tower B")

    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationRequest.objects.create(
            full_name="Nguyễn Văn An",
            phone="+84901234567",
            building=other_building,
            unit=unit,
            password_hash="hashed",
            status_token_digest="a" * 64,
            expires_at=timezone.now() + timedelta(days=30),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS registration_unit_building_fk IMMEDIATE")


@pytest.mark.parametrize("field,value", [("phone", "0901234567"), ("email", "AN@EXAMPLE.COM")])
def test_pending_duplicate_has_generic_failure(unit, field, value):
    submit(unit)

    with pytest.raises(RegistrationConflict, match="Registration cannot be submitted"):
        submit(unit, **{field: value})


@pytest.mark.parametrize("status", [RegistrationRequest.Status.REJECTED, RegistrationRequest.Status.EXPIRED])
def test_terminal_request_does_not_block_later_submission(unit, status):
    first = submit(unit).request
    first.status = status
    first.save(update_fields=["status"])

    assert submit(unit).request.pk != first.pk


def test_stale_pending_request_does_not_block_later_submission(unit):
    first = submit(unit).request
    RegistrationRequest.objects.filter(pk=first.pk).update(expires_at=timezone.now())

    assert submit(unit).request.pk != first.pk
    first.refresh_from_db()
    assert first.status == RegistrationRequest.Status.EXPIRED
    assert first.password_hash == ""
    assert first.decided_at is not None


@pytest.mark.parametrize("existing", ["phone", "email"])
def test_existing_user_has_same_generic_failure(unit, existing):
    values = {existing: "0901234567" if existing == "phone" else "an@example.com"}
    User.objects.create_user(password="existing password", **values)

    with pytest.raises(RegistrationConflict, match="Registration cannot be submitted"):
        submit(unit)


def test_unrelated_integrity_error_is_not_hidden(unit, monkeypatch):
    def fail(**kwargs):
        raise IntegrityError("unrelated")

    monkeypatch.setattr(RegistrationRequest.objects, "create", fail)

    with pytest.raises(IntegrityError, match="unrelated"):
        submit(unit)


def test_status_lookup_uses_only_token_and_expires_stale_request(unit):
    submission = submit(unit)
    RegistrationRequest.objects.filter(pk=submission.request.pk).update(
        expires_at=timezone.now()
    )

    request = get_registration_status(submission.status_token)

    assert request.status == RegistrationRequest.Status.EXPIRED
    assert request.password_hash == ""
    assert request.decided_at is not None
    with pytest.raises(RegistrationRequest.DoesNotExist):
        get_registration_status(request.phone)


def test_admin_does_not_expose_secret_hashes():
    model_admin = admin.site._registry[RegistrationRequest]

    assert "password_hash" in model_admin.readonly_fields
    assert "status_token_digest" in model_admin.readonly_fields


def test_model_has_no_plaintext_secret_fields():
    field_names = {field.name for field in RegistrationRequest._meta.fields}

    assert "password" not in field_names
    assert "status_token" not in field_names
