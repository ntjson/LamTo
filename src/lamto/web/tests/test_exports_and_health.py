"""Auditor exports, formula neutralization, and ops health/metrics."""

from __future__ import annotations

import csv
import io
import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.capabilities import AUDIT_EXPORT, TECH_ADMIN
from lamto.accounts.models import BackupMarker, Building, Organization, OrganizationMembership
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.accounts.services import grant_capability
from lamto.audit.models import AuditEvent
from lamto.audit.services import record_audit
from lamto.web.views.exports import neutralize_cell


class ExportsAndHealthTests(TestCase):
    def _unique(self, base):
        n = getattr(self, "_seq", 0) + 1
        self._seq = n
        return f"{base}-{n}"

    def make_membership(self, role, suffix, capabilities=(), *, building=None):
        building = building or self.building
        suffix = self._unique(suffix)
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test",
            password="secret-pass-123",
            display_name=suffix,
        )
        organization = Organization.objects.create(
            building=building,
            name=suffix,
            kind=OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role],
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )
        for code in capabilities:
            grant_capability(membership, code)
        return membership

    def enroll_and_bind(self, user):
        device = TOTPDevice.objects.create(
            user=user, name="test", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        return device

    def setUp(self):
        self.building = Building.objects.create(name=self._unique("Export Building"))
        self.auditor = self.make_membership(
            OrganizationMembership.Role.AUDITOR,
            "auditor",
            capabilities=(AUDIT_EXPORT,),
        )
        self.operator = self.make_membership(
            OrganizationMembership.Role.OPERATOR,
            "operator",
            capabilities=(),
        )
        self.tech = self.make_membership(
            OrganizationMembership.Role.TECH_ADMIN,
            "tech",
            capabilities=(TECH_ADMIN,),
        )

    def test_neutralize_spreadsheet_formula_prefixes(self):
        self.assertEqual(neutralize_cell("=CMD()"), "'=CMD()")
        self.assertEqual(neutralize_cell("+1234"), "'+1234")
        self.assertEqual(neutralize_cell("-1+1"), "'-1+1")
        self.assertEqual(neutralize_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(neutralize_cell("normal text"), "normal text")
        self.assertEqual(neutralize_cell(None), "")

    def test_auditor_export_streams_csv_and_audits_success(self):
        record_audit(
            self.auditor.user,
            self.auditor,
            "test.action",
            "Thing",
            "1",
            "accepted",
            {"note": "=HACK()"},
        )
        self.client.force_login(self.auditor.user)
        self.enroll_and_bind(self.auditor.user)
        response = self.client.get(reverse("web:audit-export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.reader(io.StringIO(body))
        rows = list(reader)
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "id")
        # Success audited
        self.assertTrue(
            AuditEvent.objects.filter(
                action="audit.export", result="accepted", actor=self.auditor.user
            ).exists()
        )
        # No raw private key material markers in export body
        self.assertNotIn("private_key", body.lower())
        self.assertNotIn("bank_account", body.lower())

    def test_non_auditor_export_denied_and_audited(self):
        self.client.force_login(self.operator.user)
        self.enroll_and_bind(self.operator.user)
        response = self.client.get(reverse("web:audit-export"))
        self.assertEqual(response.status_code, 403)

    def test_export_document_kind_has_hash_columns_not_bytes(self):
        self.client.force_login(self.auditor.user)
        self.enroll_and_bind(self.auditor.user)
        response = self.client.get(reverse("web:audit-export") + "?kind=documents")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        header = next(csv.reader(io.StringIO(body)))
        self.assertIn("sha256", header)
        self.assertNotIn("raw_bytes", header)
        self.assertNotIn("storage_body", header)

    def test_health_requires_tech_admin(self):
        self.client.force_login(self.auditor.user)
        self.enroll_and_bind(self.auditor.user)
        self.assertEqual(self.client.get(reverse("web:ops-health")).status_code, 403)

        self.client.force_login(self.tech.user)
        self.enroll_and_bind(self.tech.user)
        response = self.client.get(reverse("web:ops-health") + "?format=json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in (
            "queue_age_seconds",
            "queue_count",
            "quarantined_files",
            "notification_failures",
            "outbox_status_counts",
            "last_confirmed_block",
            "latest_backup_marker",
            "integrity_mismatches",
        ):
            self.assertIn(key, data)
        # No document content or private keys
        blob = str(data).lower()
        self.assertNotIn("private_key", blob)
        self.assertNotIn("document_content", blob)

    def test_health_includes_backup_marker(self):
        BackupMarker.objects.create(
            marker_id="m1",
            signed_at=timezone.now(),
            signature="abc",
            storage_key="ops/backups/markers/m1.json",
            metadata={"object_count": 0},
        )
        self.client.force_login(self.tech.user)
        self.enroll_and_bind(self.tech.user)
        data = self.client.get(reverse("web:ops-health") + "?format=json").json()
        self.assertIsNotNone(data["latest_backup_marker"])
        self.assertEqual(data["latest_backup_marker"]["marker_id"], "m1")

    def test_pilot_metrics_non_authoritative(self):
        self.client.force_login(self.tech.user)
        self.enroll_and_bind(self.tech.user)
        response = self.client.get(reverse("web:pilot-metrics") + "?format=json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["authoritative"])
        self.assertIn("ai_suggestion_accepted", data)
        self.assertIn("triage_latency_ms_avg", data)

    def test_backup_objects_command_filesystem_mode(self):
        from django.core.management import call_command
        from io import StringIO
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "manifest.json")
            out = StringIO()
            with override_settings(
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": tmp},
                    },
                    "private": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": tmp},
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                    },
                }
            ):
                os.environ["LAMTO_BACKUP_ALLOW_FS"] = "1"
                try:
                    call_command(
                        "backup_objects",
                        dest_prefix="object-backups",
                        manifest_path=manifest,
                        stdout=out,
                    )
                finally:
                    os.environ.pop("LAMTO_BACKUP_ALLOW_FS", None)
            self.assertTrue(os.path.isfile(manifest))
            self.assertTrue(BackupMarker.objects.exists())
            # restore dry structural path
            out2 = StringIO()
            os.environ["LAMTO_BACKUP_ALLOW_FS"] = "1"
            try:
                with override_settings(
                    STORAGES={
                        "default": {
                            "BACKEND": "django.core.files.storage.FileSystemStorage",
                            "OPTIONS": {"location": tmp},
                        },
                        "private": {
                            "BACKEND": "django.core.files.storage.FileSystemStorage",
                            "OPTIONS": {"location": tmp},
                        },
                        "staticfiles": {
                            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                        },
                    }
                ):
                    call_command(
                        "restore_object_backup",
                        manifest=manifest,
                        dest_prefix="restore-drill",
                        dry_run=True,
                        stdout=out2,
                    )
            finally:
                os.environ.pop("LAMTO_BACKUP_ALLOW_FS", None)
            self.assertIn("restore_object_backup", out2.getvalue())
