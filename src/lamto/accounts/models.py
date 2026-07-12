from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=160)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []


class Building(models.Model):
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="Asia/Ho_Chi_Minh")


class Unit(models.Model):
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    label = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["building", "label"], name="unit_label_per_building")
        ]


class Organization(models.Model):
    class Kind(models.TextChoices):
        BOARD = "BOARD", "Management Board"
        OPERATOR = "OPERATOR", "Property-management operator"
        RESIDENT_REP = "RESIDENT_REP", "Resident representative"
        AUDITOR = "AUDITOR", "Auditor"
        PLATFORM = "PLATFORM", "Platform provider"

    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=24, choices=Kind.choices)

    def clean(self):
        super().clean()
        if self.pk:
            current_kind = type(self).objects.filter(pk=self.pk).values_list("kind", flat=True).first()
            if current_kind is not None and current_kind != self.kind:
                valid_roles = [
                    role
                    for role, kind in OrganizationMembership.ROLE_TO_ORGANIZATION_KIND.items()
                    if kind == self.kind
                ]
                if self.organizationmembership_set.exclude(role__in=valid_roles).exists():
                    raise ValidationError({"kind": "Organization kind does not match its memberships."})


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OPERATOR = "OPERATOR", "Operator"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        BOARD = "BOARD", "Board"
        RESIDENT_REP = "RESIDENT_REP", "Resident representative"
        AUDITOR = "AUDITOR", "Auditor"
        TECH_ADMIN = "TECH_ADMIN", "Technical administrator"

    ROLE_TO_ORGANIZATION_KIND = {
        Role.BOARD: Organization.Kind.BOARD,
        Role.RESIDENT_REP: Organization.Kind.RESIDENT_REP,
        Role.AUDITOR: Organization.Kind.AUDITOR,
        Role.TECH_ADMIN: Organization.Kind.PLATFORM,
        Role.OPERATOR: Organization.Kind.OPERATOR,
        Role.MAINTENANCE: Organization.Kind.OPERATOR,
    }

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    role = models.CharField(max_length=24, choices=Role.choices)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization", "role"], name="membership_once"
            )
        ]

    def clean(self):
        expected_kind = self.ROLE_TO_ORGANIZATION_KIND.get(self.role)
        if expected_kind and self.organization.kind != expected_kind:
            raise ValidationError({"role": "Role does not match the organization kind."})


class ResidentOccupancy(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
