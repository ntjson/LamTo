import hashlib
from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth.hashers import check_password
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from lamto.accounts.models import Building, RegistrationRequest, Unit, User
from lamto.accounts.registration import (
    RegistrationConflict,
    get_registration_status,
    submit_registration,
)


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
