"""Seed one fictional demo building for a visitor's self-run demo.

Usage:
  PILOT_ALLOW_FIXTURES=1 python manage.py seed_demo
  PILOT_ALLOW_FIXTURES=1 python manage.py seed_demo \
      --building-name "..." --login-prefix visitorb --password "..."

Built on the same world factory as seed_pilot. Refuses to run when the
building name or the login prefix is already in use, and creates everything
inside one transaction.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from lamto.accounts.models import Building, User
from lamto.testing.factories import (
    DEMO_BUILDING_NAME,
    DEMO_EMAIL_DOMAIN,
    DEMO_LOGIN_PREFIX,
    DEMO_MANAGER_DISPLAY_NAME,
    DEMO_PASSWORD,
    DEMO_RESIDENT_DISPLAY_NAME,
    demo_resident_phone,
    seed_pilot_world,
)

# Lowercase words joined by single hyphens: safe in an email local part.
_LOGIN_PREFIX = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class Command(BaseCommand):
    help = "Seed one fictional demo building with a Management and a resident login."

    def add_arguments(self, parser):
        parser.add_argument(
            "--building-name",
            default=DEMO_BUILDING_NAME,
            help="Display name of the demo building.",
        )
        parser.add_argument(
            "--login-prefix",
            default=DEMO_LOGIN_PREFIX,
            help="Prefix for the Management email and the resident phone number.",
        )
        parser.add_argument(
            "--password",
            default=DEMO_PASSWORD,
            help="Password for both demo logins.",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "PILOT_ALLOW_FIXTURES", False):
            raise CommandError(
                "Refusing to seed: PILOT_ALLOW_FIXTURES is false. "
                "Set PILOT_ALLOW_FIXTURES=1 only in non-production environments."
            )
        name = options["building_name"].strip()
        prefix = options["login_prefix"]
        password = options["password"]
        if not name:
            raise CommandError("--building-name must not be blank.")
        if not password:
            raise CommandError("--password must not be empty.")
        if not _LOGIN_PREFIX.fullmatch(prefix):
            raise CommandError(
                "--login-prefix may use only lowercase letters, digits and single hyphens."
            )
        if Building.objects.filter(name=name).exists():
            raise CommandError(
                f"Demo building {name!r} already exists; nothing was created."
            )
        phone = demo_resident_phone(prefix)
        if _login_prefix_in_use(prefix, phone):
            raise CommandError(
                f"Login prefix {prefix!r} is already in use; nothing was created. "
                "Pass another --login-prefix."
            )

        with transaction.atomic():
            seed = seed_pilot_world(
                building_name=name,
                password=password,
                email_domain=DEMO_EMAIL_DOMAIN,
                email_prefix=prefix,
                create_sample_report=False,
                manager_display_name=DEMO_MANAGER_DISPLAY_NAME,
                resident_display_name=DEMO_RESIDENT_DISPLAY_NAME,
                resident_phone=phone,
            )

        manager = seed.management_users[0]
        resident = seed.residents[0]
        self.stdout.write(self.style.SUCCESS(f"Demo building created: {seed.building.name}"))
        self.stdout.write("")
        self.stdout.write("Logins for the cue card:")
        self.stdout.write(f"  Management (email): {manager.email}")
        self.stdout.write(f"  Resident (phone):   {resident.phone}")
        self.stdout.write(f"  Password (both):    {password}")


def _login_prefix_in_use(prefix: str, phone: str) -> bool:
    return (
        User.objects.filter(
            email__istartswith=f"{prefix}-",
            email__iendswith=f"@{DEMO_EMAIL_DOMAIN}",
        ).exists()
        or User.objects.filter(phone=phone).exists()
    )
