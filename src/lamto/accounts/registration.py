import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from .backends import normalize_phone
from .models import RegistrationRequest, Unit, User


class RegistrationConflict(Exception):
    pass


@dataclass(frozen=True)
class RegistrationSubmission:
    request: RegistrationRequest
    status_token: str = field(repr=False)


_DUPLICATE_CONSTRAINTS = {
    "unique_pending_registration_phone",
    "unique_pending_registration_email",
}


def status_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expire_stale_requests():
    RegistrationRequest.objects.filter(
        status=RegistrationRequest.Status.PENDING,
        expires_at__lte=timezone.now(),
    ).update(status=RegistrationRequest.Status.EXPIRED)


@transaction.atomic
def submit_registration(*, full_name, phone, email, password, building_id, unit_id):
    user_phone = normalize_phone(phone)
    email = (
        BaseUserManager.normalize_email(email.strip()).casefold()
        if email and email.strip()
        else None
    )
    if user_phone is None or not Unit.objects.filter(
        pk=unit_id, building_id=building_id
    ).exists():
        raise RegistrationConflict("Registration cannot be submitted")
    phone = "+84" + user_phone[1:]

    _expire_stale_requests()
    duplicate = User.objects.filter(phone=user_phone)
    pending = RegistrationRequest.objects.filter(
        status=RegistrationRequest.Status.PENDING, phone=phone
    )
    if email is not None:
        duplicate = duplicate | User.objects.filter(email__iexact=email)
        pending = pending | RegistrationRequest.objects.filter(
            status=RegistrationRequest.Status.PENDING, email=email
        )
    if duplicate.exists() or pending.exists():
        raise RegistrationConflict("Registration cannot be submitted")

    token = secrets.token_urlsafe(32)
    try:
        request = RegistrationRequest.objects.create(
            full_name=full_name.strip(),
            phone=phone,
            email=email,
            building_id=building_id,
            unit_id=unit_id,
            password_hash=make_password(password),
            status_token_digest=status_token_digest(token),
            expires_at=timezone.now() + timedelta(days=30),
        )
    except IntegrityError as error:
        constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if constraint in _DUPLICATE_CONSTRAINTS:
            raise RegistrationConflict("Registration cannot be submitted") from error
        raise
    return RegistrationSubmission(request=request, status_token=token)


def get_registration_status(status_token):
    request = RegistrationRequest.objects.get(
        status_token_digest=status_token_digest(status_token)
    )
    if (
        request.status == RegistrationRequest.Status.PENDING
        and request.expires_at <= timezone.now()
    ):
        request.status = RegistrationRequest.Status.EXPIRED
        request.save(update_fields=["status", "updated_at"])
    return request
