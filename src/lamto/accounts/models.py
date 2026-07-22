from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=160)
    phone = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="Canonical local form 0xxxxxxxxx; residents may log in with it.",
    )
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    def __str__(self):
        return self.display_name or self.email

    def save(self, *args, **kwargs):
        # Keep User.phone in the same canonical form login accepts.
        if self.phone:
            from lamto.accounts.backends import normalize_phone

            canonical = normalize_phone(self.phone)
            if canonical is not None:
                self.phone = canonical
        return super().save(*args, **kwargs)


class Building(models.Model):
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="Asia/Ho_Chi_Minh")


class Unit(models.Model):
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    label = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["building", "label"], name="unit_label_per_building"),
            models.UniqueConstraint(fields=["id", "building"], name="unit_id_building_key"),
        ]


class ResidentOccupancy(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)


class ManagementMembership(models.Model):
    """The single Management staff role, scoped to a building."""

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "building"], name="management_membership_once"
            )
        ]


class AuthThrottleBucket(models.Model):
    """Cross-worker login/MFA failure throttle keyed by SHA-256(account|ip)."""

    key_digest = models.CharField(max_length=64, unique=True, db_index=True)
    failure_count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AuthThrottleBucket({self.key_digest[:12]}…, failures={self.failure_count})"


class BackupMarker(models.Model):
    """Insert-only record of a successful backup (ops health surface)."""

    marker_id = models.CharField(max_length=64, unique=True)
    signed_at = models.DateTimeField()
    signature = models.CharField(max_length=128)
    storage_key = models.CharField(max_length=512, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("BackupMarker rows are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("BackupMarker rows are append-only.")
