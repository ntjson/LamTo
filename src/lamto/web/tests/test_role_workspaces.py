import hashlib
import secrets
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import (
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    PROPOSAL_APPROVE,
    PROPOSAL_CREATE,
    REPORT_TRIAGE,
)
from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    Unit,
)
from lamto.accounts.services import grant_capability
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    utc_rfc3339,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import AcceptanceRecord, PaymentEvidence
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    WorkOrder,
)
from lamto.web.action_inbox import action_items_for
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.web.staff import SESSION_MEMBERSHIP_KEY, capabilities_for
import time

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-staff-")


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class RoleWorkspaceTests(TestCase):
    def enroll_mfa(self, user):
        """Task 17: staff workspaces require confirmed TOTP + verified session."""
        device = TOTPDevice.objects.create(
            user=user, name="test", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        return device

    def _unique(self, base):
        n = getattr(self, "_fixture_seq", 0) + 1
        self._fixture_seq = n
        return f"{base}-{n}"

    def make_membership(self, building, role, suffix, capabilities=(), *, with_wallet=False):
        suffix = self._unique(suffix)
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test",
            password="secret",
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
        if with_wallet:
            account = Account.create()
            challenge = begin_wallet_registration(membership)
            proof = Account.sign_message(
                encode_typed_data(full_message=challenge), account.key
            ).signature.hex()
            register_wallet(membership, account.address, proof)
            if not hasattr(self, "accounts"):
                self.accounts = {}
            self.accounts[membership.pk] = account
        return membership

    def queue_event(self, membership, *, confirm=True):
        event_id = "0x" + secrets.token_hex(32)
        payload = {
            "fund_entry_id": secrets.randbelow(10**8) + 1,
            "entry_type": "INFLOW",
            "amount_vnd": 1,
            "source_document_original_hash": secrets.token_hex(32),
            "source_document_redacted_hash": secrets.token_hex(32),
            "maker_membership_id": membership.pk,
            "entry_timestamp": utc_rfc3339(timezone.now()),
        }
        previous = "0x" + "00" * 32
        typed = build_evidence_typed_data(
            event_id,
            EvidenceType.FUND_ENTRY,
            "0x" + payload_hash(payload),
            previous,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[membership.pk].key
        ).signature.hex()
        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.FUND_ENTRY,
                payload,
                previous,
                membership,
                signature,
            )
        if confirm:
            event.status = BlockchainOutboxEvent.Status.CONFIRMED
            event.confirmed_at = timezone.now()
            event.save(update_fields=["status", "confirmed_at"])
        return event

    def document_pair(self, building, uploader, kind, tag):
        doc = Document.objects.create(building=building, kind=kind)
        storage = storages["private"]
        o_bytes = f"{tag}-o".encode()
        r_bytes = f"{tag}-r".encode()
        o_key = f"staff/{tag}-o"
        r_key = f"staff/{tag}-r"
        storage.save(o_key, ContentFile(o_bytes))
        storage.save(r_key, ContentFile(r_bytes))
        original = DocumentVersion.objects.create(
            document=doc,
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            filename=f"{tag}-o.bin",
            content_type="application/pdf",
            byte_size=len(o_bytes),
            sha256=hashlib.sha256(o_bytes).hexdigest(),
            storage_key=o_key,
            provider_version_id=f"{tag}-o-v",
            scan_status=DocumentVersion.ScanStatus.CLEAN,
            uploader=uploader,
        )
        redacted = DocumentVersion.objects.create(
            document=doc,
            version=2,
            variant=DocumentVersion.Variant.REDACTED,
            filename=f"{tag}-r.bin",
            content_type="application/pdf",
            byte_size=len(r_bytes),
            sha256=hashlib.sha256(r_bytes).hexdigest(),
            storage_key=r_key,
            provider_version_id=f"{tag}-r-v",
            scan_status=DocumentVersion.ScanStatus.CLEAN,
            uploader=uploader,
            redacts=original,
        )
        return original, redacted

    def make_workspace_users(self):
        building = Building.objects.create(name=self._unique("Building"))
        location = BuildingLocation.objects.create(
            building=building, name="Lobby", active=True
        )
        maintenance = self.make_membership(
            building, OrganizationMembership.Role.MAINTENANCE, "maint"
        )
        # Board membership with verify only (no payment.record)
        board = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "board",
            capabilities=(PAYMENT_VERIFY, PROPOSAL_APPROVE),
            with_wallet=True,
        )
        # Separate recorder membership for FK attribution
        recorder = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "recorder",
            capabilities=(PAYMENT_RECORD,),
            with_wallet=True,
        )

        unit = Unit.objects.create(building=building, label="A-1")
        resident = get_user_model().objects.create_user(
            email=self._unique("res") + "@example.test",
            password="secret",
            display_name="Resident",
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text="Elevator shakes",
            selected_location=location,
            location_path_snapshot=f"{building.name} / Lobby",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=recorder.user,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_minutes=120,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        work_order = WorkOrder.objects.create(
            case=case,
            assignee=maintenance.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.ACCEPTED,
        )
        inv_o, inv_r = self.document_pair(
            building, board.user, Document.Kind.INVOICE, self._unique("inv")
        )
        acc_o, acc_r = self.document_pair(
            building, board.user, Document.Kind.ACCEPTANCE_REPORT, self._unique("acc")
        )
        proof_o, proof_r = self.document_pair(
            building, board.user, Document.Kind.PAYMENT_PROOF, self._unique("proof")
        )
        accept_event = self.queue_event(recorder)
        payment_event = self.queue_event(recorder)
        acceptance = AcceptanceRecord(
            work_order=work_order,
            actual_cost_vnd=1_000_000,
            invoice_original=inv_o,
            invoice_redacted=inv_r,
            acceptance_original=acc_o,
            acceptance_redacted=acc_r,
            membership=recorder,
            wallet=accept_event.signer_wallet,
            signature=accept_event.signature,
            outbox_event=accept_event,
            accepted_at=timezone.now(),
        )
        acceptance.save()
        PaymentEvidence(
            acceptance=acceptance,
            bank_reference=self._unique("REF").upper(),
            amount_vnd=1_000_000,
            external_status=PaymentEvidence.ExternalStatus.COMPLETED,
            completed_at=timezone.now(),
            proof_original=proof_o,
            proof_redacted=proof_r,
            recorder=recorder,
            wallet=payment_event.signer_wallet,
            signature=payment_event.signature,
            outbox_event=payment_event,
            recorded_at=timezone.now(),
        ).save()
        return maintenance.user, board

    def test_maintenance_cannot_open_finance_and_board_sees_only_granted_actions(self):
        maintenance, board = self.make_workspace_users()
        self.client.force_login(maintenance)
        self.enroll_mfa(maintenance)
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 403)

        self.client.force_login(board.user)
        self.enroll_mfa(board.user)
        response = self.client.get(
            reverse("web:action-inbox"), {"membership": board.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment verification")
        self.assertNotContains(response, "Record payment")

    def test_active_membership_not_combined(self):
        building = Building.objects.create(name="B1")
        user = get_user_model().objects.create_user(
            email="multi@example.test", password="secret", display_name="Multi"
        )
        board_org = Organization.objects.create(
            building=building, name="Board", kind=Organization.Kind.BOARD
        )
        op_org = Organization.objects.create(
            building=building, name="Ops", kind=Organization.Kind.OPERATOR
        )
        board_m = OrganizationMembership.objects.create(
            user=user, organization=board_org, role=OrganizationMembership.Role.BOARD
        )
        op_m = OrganizationMembership.objects.create(
            user=user, organization=op_org, role=OrganizationMembership.Role.OPERATOR
        )
        grant_capability(board_m, PAYMENT_VERIFY)
        grant_capability(op_m, REPORT_TRIAGE)
        grant_capability(op_m, PROPOSAL_CREATE)

        self.client.force_login(user)
        self.enroll_mfa(user)
        session = self.client.session
        session[SESSION_MEMBERSHIP_KEY] = board_m.pk
        session.save()
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 403)

        session = self.client.session
        session[SESSION_MEMBERSHIP_KEY] = op_m.pk
        # re-bind MFA device after session mutation
        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 200)

        resp = self.client.get(
            reverse("web:action-inbox"), {"membership": board_m.pk}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session[SESSION_MEMBERSHIP_KEY], board_m.pk)

    def test_signed_form_wallet_script_is_wired_for_intercept(self):
        """wallet-signing.js must load as classic script and bind data-signed-form."""
        from pathlib import Path as P

        building = Building.objects.create(name="B2")
        board = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "approver",
            capabilities=(PROPOSAL_APPROVE,),
        )
        self.client.force_login(board.user)
        self.enroll_mfa(board.user)
        response = self.client.get(reverse("web:proposal-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "wallet-signing.js")
        # Not a module import — classic script tag without type=module
        body = response.content.decode()
        self.assertNotIn('type="module"', body)
        self.assertIn("wallet-signing.js", body)

        js_path = (
            P(__file__).resolve().parents[1] / "static" / "web" / "wallet-signing.js"
        )
        js = js_path.read_text()
        self.assertNotIn("export async function", js)
        self.assertNotIn("export function", js)
        self.assertIn("data-signed-form", js)
        self.assertIn("eth_signTypedData_v4", js)
        self.assertIn("LamToWalletSigning", js)
        self.assertIn("bindSignedForms", js)

    def test_payment_and_case_routes_disambiguate_colliding_pks(self):
        """Equal PKs across tables must not open the wrong staff form."""
        from django.db import connection

        building = Building.objects.create(name=self._unique("Collide"))
        location = BuildingLocation.objects.create(
            building=building, name="Hall", active=True
        )
        board = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "board-col",
            capabilities=(PAYMENT_RECORD, PAYMENT_VERIFY),
            with_wallet=True,
        )
        operator = self.make_membership(
            building,
            OrganizationMembership.Role.OPERATOR,
            "op-col",
            capabilities=(REPORT_TRIAGE,),
        )
        # Grant triage for report/case access
        grant_capability(operator, REPORT_TRIAGE)

        unit = Unit.objects.create(building=building, label="C-1")
        resident = get_user_model().objects.create_user(
            email=self._unique("rcol") + "@example.test",
            password="secret",
            display_name="R",
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text="Leak",
            selected_location=location,
            location_path_snapshot=f"{building.name} / Hall",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=operator.user,
            category="Plumbing",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_minutes=60,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Plumbing",
            urgency="HIGH",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        # Force case.pk == report.pk when possible by inserting with explicit id
        target_id = max(report.pk, case.pk)
        # Create a second report with forced pk equal to case when different
        if report.pk != case.pk:
            # Staff report route must load IssueReport, case route MaintenanceCase
            self.client.force_login(operator.user)
            self.enroll_mfa(operator.user)
            r_resp = self.client.get(
                reverse("web:staff-report-detail", kwargs={"pk": report.pk})
            )
            # report already linked to active case → redirect to case
            self.assertIn(r_resp.status_code, (200, 302))
            c_resp = self.client.get(
                reverse("web:case-detail", kwargs={"pk": case.pk})
            )
            self.assertEqual(c_resp.status_code, 200)
            self.assertContains(c_resp, f"Case #{case.pk}")
            # case-detail with report pk (if different) must 404 — not silently open report
            if report.pk != case.pk:
                wrong = self.client.get(
                    reverse("web:case-detail", kwargs={"pk": report.pk})
                )
                # only 404 if no case with that id
                if not MaintenanceCase.objects.filter(
                    pk=report.pk, building_id=building.pk
                ).exists():
                    self.assertEqual(wrong.status_code, 404)

        # Payment collision: AcceptanceRecord and PaymentEvidence with same pk
        maintenance = self.make_membership(
            building, OrganizationMembership.Role.MAINTENANCE, "mcol"
        )
        work_order = WorkOrder.objects.create(
            case=case,
            assignee=maintenance.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.ACCEPTED,
        )
        inv_o, inv_r = self.document_pair(
            building, board.user, Document.Kind.INVOICE, self._unique("invc")
        )
        acc_o, acc_r = self.document_pair(
            building, board.user, Document.Kind.ACCEPTANCE_REPORT, self._unique("accc")
        )
        proof_o, proof_r = self.document_pair(
            building, board.user, Document.Kind.PAYMENT_PROOF, self._unique("proofc")
        )
        accept_event = self.queue_event(board)
        payment_event = self.queue_event(board)

        # Create acceptance with explicit pk, then payment with same pk
        collision_pk = 900001
        acceptance = AcceptanceRecord(
            pk=collision_pk,
            work_order=work_order,
            actual_cost_vnd=500_000,
            invoice_original=inv_o,
            invoice_redacted=inv_r,
            acceptance_original=acc_o,
            acceptance_redacted=acc_r,
            membership=board,
            wallet=accept_event.signer_wallet,
            signature=accept_event.signature,
            outbox_event=accept_event,
            accepted_at=timezone.now(),
        )
        acceptance.save()

        # Separate acceptance without payment for record route, and payment with same pk
        # as a different acceptance's identity space — create payment with forced pk
        work_order2 = WorkOrder.objects.create(
            case=case,
            assignee=maintenance.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.ACCEPTED,
        )
        inv_o2, inv_r2 = self.document_pair(
            building, board.user, Document.Kind.INVOICE, self._unique("invc2")
        )
        acc_o2, acc_r2 = self.document_pair(
            building, board.user, Document.Kind.ACCEPTANCE_REPORT, self._unique("accc2")
        )
        proof_o2, proof_r2 = self.document_pair(
            building, board.user, Document.Kind.PAYMENT_PROOF, self._unique("proofc2")
        )
        accept_event2 = self.queue_event(board)
        payment_event2 = self.queue_event(board)
        acceptance2 = AcceptanceRecord(
            work_order=work_order2,
            actual_cost_vnd=600_000,
            invoice_original=inv_o2,
            invoice_redacted=inv_r2,
            acceptance_original=acc_o2,
            acceptance_redacted=acc_r2,
            membership=board,
            wallet=accept_event2.signer_wallet,
            signature=accept_event2.signature,
            outbox_event=accept_event2,
            accepted_at=timezone.now(),
        )
        acceptance2.save()
        payment = PaymentEvidence(
            pk=collision_pk,  # same as acceptance.pk above
            acceptance=acceptance2,
            bank_reference=self._unique("REFCOL").upper(),
            amount_vnd=600_000,
            external_status=PaymentEvidence.ExternalStatus.COMPLETED,
            completed_at=timezone.now(),
            proof_original=proof_o2,
            proof_redacted=proof_r2,
            recorder=board,
            wallet=payment_event2.signer_wallet,
            signature=payment_event2.signature,
            outbox_event=payment_event2,
            recorded_at=timezone.now(),
        )
        payment.save()
        self.assertEqual(acceptance.pk, payment.pk)

        self.client.force_login(board.user)
        self.enroll_mfa(board.user)
        record_resp = self.client.get(
            reverse("web:payment-record-detail", kwargs={"pk": collision_pk})
        )
        self.assertEqual(record_resp.status_code, 200)
        self.assertContains(record_resp, f"Acceptance #{collision_pk}")
        self.assertContains(record_resp, "Record payment")

        verify_resp = self.client.get(
            reverse("web:payment-verify-detail", kwargs={"pk": collision_pk})
        )
        self.assertEqual(verify_resp.status_code, 200)
        self.assertContains(verify_resp, f"Payment #{collision_pk}")
        self.assertContains(verify_resp, "Payment verification")

        # Inbox links must use disambiguated routes
        items = action_items_for(board)
        record_urls = [i.url for i in items if i.kind == "payment_record"]
        verify_urls = [i.url for i in items if i.kind == "payment_verification"]
        self.assertTrue(any(f"/payments/record/{collision_pk}/" in u for u in record_urls))
        self.assertTrue(any(f"/payments/verify/{collision_pk}/" in u for u in verify_urls))

    def test_inbox_mutation_routes_and_publish_only_access(self):
        from lamto.accounts.capabilities import (
            EMERGENCY_AUTHORIZE,
            LEDGER_PUBLISH,
            WORK_ACCEPT,
        )
        from lamto.finance.models import EmergencyAuthorization

        building = Building.objects.create(name=self._unique("Mut"))
        location = BuildingLocation.objects.create(
            building=building, name="Roof", active=True
        )
        board = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "board-mut",
            capabilities=(EMERGENCY_AUTHORIZE, WORK_ACCEPT, LEDGER_PUBLISH),
            with_wallet=True,
        )
        maint = self.make_membership(
            building, OrganizationMembership.Role.MAINTENANCE, "maint-mut"
        )
        unit = Unit.objects.create(building=building, label="M-1")
        resident = get_user_model().objects.create_user(
            email=self._unique("rmut") + "@example.test",
            password="secret",
            display_name="R",
        )
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text="Flood",
            selected_location=location,
            location_path_snapshot="x",
        )
        decision = TriageDecision.objects.create(
            report=report,
            operator=board.user,
            category="Water",
            urgency="CRITICAL",
            location=location,
            department="Ops",
            deadline_minutes=30,
            differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Water",
            urgency="CRITICAL",
            location=location,
            department="Ops",
            deadline_at=timezone.now(),
            active=True,
        )
        wo_accept = WorkOrder.objects.create(
            case=case,
            assignee=maint.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.AWAITING_ACCEPTANCE,
            completed_at=timezone.now(),
        )
        wo_em = WorkOrder.objects.create(
            case=case,
            assignee=maint.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            emergency=True,
            emergency_reason="Burst pipe",
            emergency_requested_by=board,
            emergency_requested_at=timezone.now(),
            authorization_status=WorkOrder.AuthorizationStatus.PENDING,
            status=WorkOrder.Status.ASSIGNED,
        )
        items = action_items_for(board)
        accept_urls = [i.url for i in items if i.kind == "work_acceptance"]
        em_urls = [i.url for i in items if i.kind == "emergency_authorize"]
        self.assertTrue(any(f"/work/{wo_accept.pk}/accept/" in u for u in accept_urls))
        self.assertTrue(
            any(f"/work/{wo_em.pk}/emergency/authorize/" in u for u in em_urls)
        )

        # Mutation pages render signed forms
        self.client.force_login(board.user)
        self.enroll_mfa(board.user)
        ar = self.client.get(reverse("web:work-accept", kwargs={"pk": wo_accept.pk}))
        self.assertEqual(ar.status_code, 200)
        self.assertContains(ar, "data-signed-form")
        self.assertContains(ar, "Accept work")

        er = self.client.get(
            reverse("web:emergency-authorize", kwargs={"pk": wo_em.pk})
        )
        self.assertEqual(er.status_code, 200)
        self.assertContains(er, "data-signed-form")
        self.assertContains(er, "Authorize emergency")

        # Pure ledger.publish membership can open proposal list
        publisher = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "pub-only",
            capabilities=(LEDGER_PUBLISH,),
            with_wallet=True,
        )
        self.client.force_login(publisher.user)
        self.enroll_mfa(publisher.user)
        pl = self.client.get(reverse("web:proposal-list"))
        self.assertEqual(pl.status_code, 200)
        self.assertContains(pl, "Pending publication")

    def test_action_items_respect_capabilities(self):
        building = Building.objects.create(name="B3")
        verifier = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "ver",
            capabilities=(PAYMENT_VERIFY,),
        )
        titles = {i.title for i in action_items_for(verifier)}
        self.assertNotIn("Record payment", titles)
        self.assertTrue(PAYMENT_VERIFY in capabilities_for(verifier))
        self.assertFalse(PAYMENT_RECORD in capabilities_for(verifier))
