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
from lamto.web.staff import SESSION_MEMBERSHIP_KEY, capabilities_for

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
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 403)

        self.client.force_login(board.user)
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
        session = self.client.session
        session[SESSION_MEMBERSHIP_KEY] = board_m.pk
        session.save()
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 403)

        session = self.client.session
        session[SESSION_MEMBERSHIP_KEY] = op_m.pk
        session.save()
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 200)

        resp = self.client.get(
            reverse("web:action-inbox"), {"membership": board_m.pk}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session[SESSION_MEMBERSHIP_KEY], board_m.pk)

    def test_signed_form_fields_present_on_proposal_detail_for_approver(self):
        building = Building.objects.create(name="B2")
        board = self.make_membership(
            building,
            OrganizationMembership.Role.BOARD,
            "approver",
            capabilities=(PROPOSAL_APPROVE,),
        )
        self.client.force_login(board.user)
        response = self.client.get(reverse("web:proposal-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "wallet-signing.js")

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
