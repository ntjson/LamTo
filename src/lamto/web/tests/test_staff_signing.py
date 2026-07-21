import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from io import StringIO

from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.documents.models import Document, DocumentVersion
from lamto.web.forms.staff import (
    AcceptWorkForm,
    CompleteWorkOrderForm,
    RecordPaymentForm,
)
from lamto.web.staff_signing import (
    cleanup_stale_prepared_ops,
    document_pair_options,
    new_event_id,
    selected_pair,
    upload_document_pair,
)

_TEMP = tempfile.mkdtemp(prefix="lamto-staffsign-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


def _age_all_versions(hours=48):
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("ALTER TABLE documents_documentversion DISABLE TRIGGER USER")
    try:
        DocumentVersion.objects.all().update(
            created_at=timezone.now() - timedelta(hours=hours)
        )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE documents_documentversion ENABLE TRIGGER USER")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class UploadDocumentPairTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Signing Building")
        org = Organization.objects.create(
            building=self.building, name="Ops", kind=Organization.Kind.OPERATOR
        )
        self.user = get_user_model().objects.create_user(
            email="op@example.test", password="secret", display_name="Op"
        )
        OrganizationMembership.objects.create(
            user=self.user, organization=org, role=OrganizationMembership.Role.OPERATOR
        )

    def test_new_event_id_is_random_bytes32(self):
        a, b = new_event_id(), new_event_id()
        assert a.startswith("0x") and len(a) == 66 and a != b

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_document_pair_options_are_scoped_and_human_readable(self):
        original, redacted = upload_document_pair(
            self.building,
            Document.Kind.INVOICE,
            self.user,
            _pdf("invoice-original.pdf", b"original"),
            _pdf("invoice-resident.pdf", b"redacted"),
        )
        other = Building.objects.create(name="Other building")
        other_org = Organization.objects.create(
            building=other, name="Other Ops", kind=Organization.Kind.OPERATOR
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            role=OrganizationMembership.Role.OPERATOR,
        )
        upload_document_pair(
            other,
            Document.Kind.INVOICE,
            self.user,
            _pdf("foreign.pdf", b"foreign original"),
            _pdf("foreign-redacted.pdf", b"foreign redacted"),
        )
        options = document_pair_options(self.building.pk, Document.Kind.INVOICE)
        self.assertEqual([item[0] for item in options], [f"{original.pk}:{redacted.pk}"])
        self.assertIn("invoice-original.pdf", options[0][1])
        self.assertIn("invoice-resident.pdf", options[0][1])

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_uploads_linked_clean_pair(self):
        original, redacted = upload_document_pair(
            self.building,
            Document.Kind.QUOTATION,
            self.user,
            _pdf("q.pdf", b"original bytes"),
            _pdf("q-red.pdf", b"redacted bytes differ"),
        )
        assert original.variant == DocumentVersion.Variant.ORIGINAL
        assert original.redacts_id is None
        assert redacted.variant == DocumentVersion.Variant.REDACTED
        assert redacted.redacts_id == original.pk
        assert original.document_id == redacted.document_id
        assert original.scan_status == DocumentVersion.ScanStatus.CLEAN
        assert redacted.scan_status == DocumentVersion.ScanStatus.CLEAN
        assert original.sha256 != redacted.sha256
        # Blobs exist on private storage for both versions.
        storage = storages["private"]
        self.assertTrue(storage.exists(original.storage_key))
        self.assertTrue(storage.exists(redacted.storage_key))

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_identical_bytes_rejected_as_validation_error(self):
        with self.assertRaises(ValidationError):
            upload_document_pair(
                self.building,
                Document.Kind.QUOTATION,
                self.user,
                _pdf("q.pdf", b"same"),
                _pdf("q.pdf", b"same"),
            )

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_redacted_failure_leaves_no_partial_pair_or_blob(self):
        """Redacted failure rolls back DB and purges original storage blob."""
        from lamto.documents.services import create_document_version as real_create
        from lamto.web import staff_signing as signing

        captured_keys = []

        def _create_and_capture(*args, **kwargs):
            version = real_create(*args, **kwargs)
            captured_keys.append(version.storage_key)
            return version

        # Use the real create but record keys; fail redacted after original is stored.
        with patch.object(
            signing, "create_document_version", side_effect=_create_and_capture
        ):
            with patch.object(
                signing, "add_redacted_copy", side_effect=ValueError("redacted scan failed")
            ):
                with self.assertRaises(ValidationError):
                    signing.upload_document_pair(
                        self.building,
                        Document.Kind.QUOTATION,
                        self.user,
                        _pdf("q.pdf", b"original bytes"),
                        _pdf("q-red.pdf", b"redacted bytes differ"),
                    )
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)
        self.assertEqual(len(captured_keys), 1)
        storage = storages["private"]
        self.assertFalse(
            storage.exists(captured_keys[0]),
            f"original blob still present: {captured_keys[0]}",
        )

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_cleanup_stale_prepared_ops_removes_old_orphans_and_blobs(self):
        original, redacted = upload_document_pair(
            self.building,
            Document.Kind.QUOTATION,
            self.user,
            _pdf("old.pdf", b"old original"),
            _pdf("old-r.pdf", b"old redacted"),
        )
        o_key, r_key = original.storage_key, redacted.storage_key
        storage = storages["private"]
        self.assertTrue(storage.exists(o_key))
        self.assertTrue(storage.exists(r_key))
        _age_all_versions(48)
        result = cleanup_stale_prepared_ops(older_than_hours=24)
        self.assertGreaterEqual(result.get("documents_deleted", 0), 1)
        self.assertGreaterEqual(result.get("storage_purged", 0), 2)
        self.assertEqual(Document.objects.count(), 0)
        self.assertFalse(storage.exists(o_key))
        self.assertFalse(storage.exists(r_key))

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_cleanup_management_command_removes_aged_orphan(self):
        upload_document_pair(
            self.building,
            Document.Kind.QUOTATION,
            self.user,
            _pdf("cmd.pdf", b"cmd original"),
            _pdf("cmd-r.pdf", b"cmd redacted"),
        )
        _age_all_versions(48)
        out = StringIO()
        call_command("cleanup_stale_prepared_ops", "--older-than-hours", "24", stdout=out)
        text = out.getvalue()
        self.assertRegex(text, r"documents_deleted=[1-9]")
        self.assertEqual(Document.objects.count(), 0)

    def test_cleanup_management_command_removes_aged_draft_proposal(self):
        """call_command must delete draft Proposals with no current_version past threshold."""
        from lamto.accounts.models import Unit
        from lamto.finance.models import Proposal
        from lamto.maintenance.models import (
            BuildingLocation,
            IssueReport,
            MaintenanceCase,
            TriageDecision,
            WorkOrder,
        )

        location = BuildingLocation.objects.create(
            building=self.building, name="Lobby", active=True
        )
        unit = Unit.objects.create(building=self.building, label="C-1")
        resident = get_user_model().objects.create_user(
            email="draft-r@example.test", password="secret", display_name="R"
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text="draft cleanup",
            selected_location=location,
            location_path_snapshot="Lobby",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=self.user,
            category="c",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_minutes=60,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=self.building,
            category="c",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        work = WorkOrder.objects.create(
            case=case,
            assignee=self.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.ASSIGNED,
        )
        membership = OrganizationMembership.objects.get(user=self.user)
        proposal = Proposal.objects.create(
            work_order=work,
            creator_membership=membership,
            status=Proposal.Status.DRAFT,
        )
        self.assertIsNone(proposal.current_version_id)
        # Age draft past threshold (Proposal.created_at is updatable via QuerySet).
        Proposal.objects.filter(pk=proposal.pk).update(
            created_at=timezone.now() - timedelta(hours=48)
        )
        out = StringIO()
        call_command("cleanup_stale_prepared_ops", "--older-than-hours", "24", stdout=out)
        text = out.getvalue()
        self.assertRegex(text, r"proposals_deleted=[1-9]")
        self.assertFalse(Proposal.objects.filter(pk=proposal.pk).exists())

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_cleanup_management_command_dry_run_does_not_delete(self):
        upload_document_pair(
            self.building,
            Document.Kind.QUOTATION,
            self.user,
            _pdf("dry.pdf", b"dry original"),
            _pdf("dry-r.pdf", b"dry redacted"),
        )
        _age_all_versions(48)
        out = StringIO()
        call_command(
            "cleanup_stale_prepared_ops",
            "--older-than-hours",
            "24",
            "--dry-run",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("dry_run", text)
        self.assertIn("documents_candidate=", text)
        self.assertEqual(Document.objects.count(), 1)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class StaffEvidenceFormTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Evidence Building")
        org = Organization.objects.create(
            building=self.building, name="Maint", kind=Organization.Kind.OPERATOR
        )
        self.user = get_user_model().objects.create_user(
            email="maint-ev@example.test", password="secret", display_name="Maint"
        )
        OrganizationMembership.objects.create(
            user=self.user, organization=org, role=OrganizationMembership.Role.MAINTENANCE
        )
        self.other = Building.objects.create(name="Foreign Building")
        self.before = self._photo(self.building, Document.Kind.BEFORE_PHOTO, "before-local.jpg")
        self.after = self._photo(self.building, Document.Kind.AFTER_PHOTO, "after-local.jpg")
        # Cross-building and wrong-kind noise must not appear in form querysets.
        self._photo(self.other, Document.Kind.BEFORE_PHOTO, "before-foreign.jpg")
        # Wrong kind under before/after filters: REPORT_PHOTO original for this building.
        self._photo(self.building, Document.Kind.REPORT_PHOTO, "report.jpg")

    def _photo(self, building, kind, filename):
        return DocumentVersion.objects.create(
            document=Document.objects.create(building=building, kind=kind),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key=f"staff-ev/{building.pk}/{filename}",
            provider_version_id=f"pv-{filename}",
            filename=filename,
            content_type="image/jpeg",
            byte_size=1,
            sha256=f"{abs(hash(filename)):064x}"[:64],
            scan_status=DocumentVersion.ScanStatus.CLEAN,
            uploader=self.user,
        )

    def test_complete_work_order_form_scopes_photo_querysets(self):
        form = CompleteWorkOrderForm(
            building_id=self.building.pk, uploader_id=self.user.pk
        )
        self.assertQuerySetEqual(
            form.fields["before_versions"].queryset,
            [self.before],
            transform=lambda x: x,
        )
        self.assertQuerySetEqual(
            form.fields["after_versions"].queryset,
            [self.after],
            transform=lambda x: x,
        )

    def test_accept_work_form_uses_pair_choices_not_raw_ids(self):
        invoice_value = "10:11"
        invoice_label = "inv-o.pdf / inv-r.pdf"
        acceptance_value = "20:21"
        acceptance_label = "acc-o.pdf / acc-r.pdf"
        accept = AcceptWorkForm(
            invoice_choices=[(invoice_value, invoice_label)],
            acceptance_choices=[(acceptance_value, acceptance_label)],
        )
        self.assertEqual(
            accept.fields["invoice_pair"].choices[1], (invoice_value, invoice_label)
        )
        self.assertEqual(
            accept.fields["acceptance_pair"].choices[1],
            (acceptance_value, acceptance_label),
        )
        self.assertNotIn("invoice_original_id", accept.fields)
        self.assertNotIn("invoice_redacted_id", accept.fields)
        self.assertNotIn("acceptance_original_id", accept.fields)
        self.assertNotIn("acceptance_redacted_id", accept.fields)

    def test_accept_work_form_rejects_foreign_pair_value(self):
        invoice_value = "10:11"
        acceptance_value = "20:21"
        accept = AcceptWorkForm(
            data={
                "actual_cost_vnd": "1000",
                "invoice_pair": "999:998",  # not in choices
                "acceptance_pair": acceptance_value,
                "event_id": "0x" + "11" * 32,
                "signature": "0x" + "22" * 65,
                "reason": "ok",
            },
            invoice_choices=[(invoice_value, "inv")],
            acceptance_choices=[(acceptance_value, "acc")],
        )
        self.assertFalse(accept.is_valid())
        self.assertIn("Select valid evidence.", accept.errors.get("invoice_pair", []))

    def test_record_payment_form_uses_proof_pair(self):
        proof_value = "30:31"
        form = RecordPaymentForm(
            proof_choices=[(proof_value, "proof-o / proof-r")],
        )
        self.assertEqual(form.fields["proof_pair"].choices[1], (proof_value, "proof-o / proof-r"))
        self.assertNotIn("proof_original_id", form.fields)
        self.assertNotIn("proof_redacted_id", form.fields)

    def test_record_payment_form_rejects_foreign_proof_pair(self):
        form = RecordPaymentForm(
            data={
                "bank_reference": "REF",
                "amount_vnd": "1000",
                "external_status": "COMPLETED",
                "proof_pair": "1:2",
                "event_id": "0x" + "11" * 32,
                "signature": "0x" + "22" * 65,
                "completed_at": "2020-01-01T00:00:00Z",
            },
            proof_choices=[("30:31", "ok pair")],
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Select valid evidence.", form.errors.get("proof_pair", []))

    def test_selected_pair_resolves_and_misses(self):
        original = object()
        redacted = object()
        options = [("1:2", "label", original, redacted)]
        self.assertEqual(selected_pair(options, "1:2"), (original, redacted))
        self.assertIsNone(selected_pair(options, "9:9"))
