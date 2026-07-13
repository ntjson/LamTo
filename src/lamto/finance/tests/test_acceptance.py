import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import (
    PROPOSAL_APPROVE,
    PROPOSAL_CREATE,
    WORK_ACCEPT,
    WORK_ASSIGN,
)
from lamto.accounts.models import Building, Organization, OrganizationMembership, Unit
from lamto.accounts.services import grant_capability
from lamto.audit.models import AuditEvent
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet, utc_rfc3339
from lamto.finance.acceptance import (
    accept_work,
    build_acceptance_evidence_payload,
    build_acceptance_evidence_typed_data,
)
from lamto.finance.approvals import decide_proposal
from lamto.finance.models import AcceptanceRecord, ApprovalDecision, Proposal
from lamto.finance.proposals import create_proposal, submit_proposal_version
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    TriageJob,
    WorkOrder,
    WorkUpdate,
    WorkUpdateEvidence,
)
from lamto.maintenance.workorders import complete_work_order, start_work_order


class WorkAcceptanceTests(TestCase):
    def _unique(self, base):
        n = getattr(self, "_fixture_seq", 0) + 1
        self._fixture_seq = n
        return f"{base}-{n}"

    def make_signer(self, building, role, capability, suffix):
        suffix = self._unique(suffix)
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        organization = Organization.objects.create(
            building=building,
            name=suffix,
            kind=OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role],
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )
        grant_capability(membership, capability)
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        register_wallet(membership, account.address, proof)
        return membership, account

    def document_pair(self, building, kind, uploader, number, prefix):
        tag = self._unique(prefix)
        document = Document.objects.create(building=building, kind=kind)
        original = DocumentVersion.objects.create(
            document=document,
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key=f"{tag}-original-{number}",
            provider_version_id=f"{tag}-original-{number}",
            filename=f"{tag}-original-{number}.pdf",
            content_type="application/pdf",
            byte_size=10,
            sha256=f"{number:064x}",
            uploader=uploader,
        )
        redacted = DocumentVersion.objects.create(
            document=document,
            version=2,
            variant=DocumentVersion.Variant.REDACTED,
            storage_key=f"{tag}-redacted-{number}",
            provider_version_id=f"{tag}-redacted-{number}",
            filename=f"{tag}-redacted-{number}.pdf",
            content_type="application/pdf",
            byte_size=9,
            sha256=f"{(number + 100):064x}",
            uploader=uploader,
            redacts=original,
        )
        return original, redacted

    def photo(self, building, kind, uploader, number):
        tag = self._unique("photo")
        return DocumentVersion.objects.create(
            document=Document.objects.create(building=building, kind=kind),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key=f"{tag}-{number}",
            provider_version_id=f"{tag}-{number}",
            filename=f"{tag}-{number}.jpg",
            content_type="image/jpeg",
            byte_size=1,
            sha256=f"{number:064d}",
            uploader=uploader,
        )

    def make_completed_work_inputs(self):
        tag = self._unique("work")
        building = Building.objects.create(name=f"Minh An Residence {tag}")
        location = BuildingLocation.objects.create(building=building, name="Lobby")
        unit = Unit.objects.create(building=building, label="A-1")
        operator_user = get_user_model().objects.create_user(
            email=f"operator-{tag}@example.test", password="secret", display_name="Operator"
        )
        operator_org = Organization.objects.create(
            building=building, name=f"Operator {tag}", kind=Organization.Kind.OPERATOR
        )
        operator = OrganizationMembership.objects.create(
            user=operator_user,
            organization=operator_org,
            role=OrganizationMembership.Role.OPERATOR,
        )
        grant_capability(operator, PROPOSAL_CREATE)
        grant_capability(operator, WORK_ASSIGN)
        account = Account.create()
        challenge = begin_wallet_registration(operator)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        register_wallet(operator, account.address.lower(), proof)

        maintenance = get_user_model().objects.create_user(
            email=f"maintenance-{tag}@example.test", password="secret", display_name="Maintenance"
        )
        OrganizationMembership.objects.create(
            user=maintenance,
            organization=operator_org,
            role=OrganizationMembership.Role.MAINTENANCE,
        )
        report = IssueReport.objects.create(
            reporter=get_user_model().objects.create_user(
                email=f"resident-{tag}@example.test", password="secret", display_name="Resident"
            ),
            unit=unit,
            text="Elevator shakes",
            selected_location=location,
            location_path_snapshot="Minh An Residence / Lobby",
        )
        TriageJob.objects.create(report=report)
        decision = TriageDecision.objects.create(
            report=report,
            suggestion=None,
            operator=operator_user,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_minutes=240,
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_at="2026-07-20T12:00:00Z",
        )
        work_order = WorkOrder.objects.create(
            case=case,
            assignee=maintenance,
            priority="HIGH",
            deadline_at=case.deadline_at,
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.PENDING,
        )
        quotation_original, _ = self.document_pair(
            building, Document.Kind.QUOTATION, operator_user, 1, "quotation"
        )
        proposal = create_proposal(work_order, operator)
        event_id = "0x" + secrets.token_hex(32)
        from lamto.finance.proposals import build_proposal_evidence_payload
        from lamto.evidence.signatures import build_evidence_typed_data

        payload = build_proposal_evidence_payload(
            proposal, 18_500_000, "Company X", [quotation_original]
        )
        typed = build_evidence_typed_data(
            event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), "0x" + "00" * 32
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()
        version = submit_proposal_version(
            proposal, 18_500_000, "Company X", [quotation_original], signature, event_id
        )

        board, board_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, PROPOSAL_APPROVE, "board-approve"
        )
        grant_capability(board, WORK_ACCEPT)
        representative, rep_account = self.make_signer(
            building,
            OrganizationMembership.Role.RESIDENT_REP,
            PROPOSAL_APPROVE,
            "representative",
        )
        self.accounts = {
            board.pk: board_account,
            representative.pk: rep_account,
        }
        board_event = "0x" + secrets.token_hex(32)
        rep_event = "0x" + secrets.token_hex(32)
        from lamto.finance.approvals import build_approval_evidence_payload

        board_payload = build_approval_evidence_payload(version, board, "APPROVE")
        board_typed = build_evidence_typed_data(
            board_event,
            EvidenceType.BOARD_APPROVAL,
            "0x" + payload_hash(board_payload),
            "0x" + version.outbox_event.payload_hash,
        )
        board_sig = Account.sign_message(
            encode_typed_data(full_message=board_typed), board_account.key
        ).signature.hex()
        rep_payload = build_approval_evidence_payload(version, representative, "APPROVE")
        rep_typed = build_evidence_typed_data(
            rep_event,
            EvidenceType.REPRESENTATIVE_APPROVAL,
            "0x" + payload_hash(rep_payload),
            "0x" + payload_hash(board_payload),
        )
        rep_sig = Account.sign_message(
            encode_typed_data(full_message=rep_typed), rep_account.key
        ).signature.hex()
        decide_proposal(version, board, "APPROVE", "Within budget", board_sig, board_event)
        decide_proposal(
            version, representative, "APPROVE", "Evidence checked", rep_sig, rep_event
        )

        work_order.refresh_from_db()
        start_work_order(work_order, maintenance)
        before = self.photo(building, Document.Kind.BEFORE_PHOTO, maintenance, 11)
        after = self.photo(building, Document.Kind.AFTER_PHOTO, maintenance, 12)
        complete_work_order(
            work_order, maintenance, "Worn cable", "Cable secured", [before], [after]
        )
        work_order.refresh_from_db()

        invoice_original, invoice_redacted = self.document_pair(
            building, Document.Kind.INVOICE, operator_user, 21, "invoice"
        )
        acceptance_original, acceptance_redacted = self.document_pair(
            building, Document.Kind.ACCEPTANCE_REPORT, operator_user, 31, "acceptance"
        )
        return (
            work_order,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
        )

    def sign_acceptance(
        self,
        work,
        membership,
        actual_cost_vnd=18_500_000,
        invoice_original=None,
        invoice_redacted=None,
        acceptance_original=None,
        acceptance_redacted=None,
        event_id=None,
        timestamp=None,
    ):
        if event_id is None:
            event_id = "0x" + secrets.token_hex(32)
        timestamp = timestamp or work.completed_at
        typed_data = build_acceptance_evidence_typed_data(
            work,
            membership,
            actual_cost_vnd,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            event_id,
            timestamp=timestamp,
        )
        return (
            Account.sign_message(
                encode_typed_data(full_message=typed_data), self.accounts[membership.pk].key
            ).signature.hex(),
            event_id,
            timestamp,
        )

    def test_accept_work_marks_accepted_and_queues_signed_outbox(self):
        (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
        ) = self.make_completed_work_inputs()
        signature, event_id, timestamp = self.sign_acceptance(
            work,
            board,
            invoice_original=invoice_original,
            invoice_redacted=invoice_redacted,
            acceptance_original=acceptance_original,
            acceptance_redacted=acceptance_redacted,
        )
        record = accept_work(
            work,
            board,
            18_500_000,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            signature,
            event_id,
            timestamp=timestamp,
        )
        work.refresh_from_db()
        self.assertEqual(work.status, WorkOrder.Status.ACCEPTED)
        self.assertEqual(record.actual_cost_vnd, 18_500_000)
        self.assertEqual(record.outbox_event.event_type, EvidenceType.WORK_ACCEPTANCE)
        self.assertEqual(record.outbox_event.payload["actual_cost_vnd"], 18_500_000)
        self.assertEqual(
            record.outbox_event.payload["acceptance_timestamp"], utc_rfc3339(timestamp)
        )
        self.assertEqual(
            record.outbox_event.payload["invoice_original_hash"], invoice_original.sha256
        )
        self.assertEqual(len(record.outbox_event.payload["photo_hashes"]), 2)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="work.accept", target_id=str(record.pk), result="accepted"
            ).exists()
        )
        previous = ApprovalDecision.objects.get(
            version=work.proposal.current_version,
            stage=ApprovalDecision.Stage.RESIDENT_REP,
        )
        self.assertEqual(
            record.outbox_event.previous_hash, "0x" + previous.outbox_event.payload_hash
        )

    def test_accept_work_rejects_wrong_status_and_non_positive_cost(self):
        (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
        ) = self.make_completed_work_inputs()
        work.status = WorkOrder.Status.IN_PROGRESS
        work.save(update_fields=["status"])
        signature, event_id, timestamp = self.sign_acceptance(
            work,
            board,
            invoice_original=invoice_original,
            invoice_redacted=invoice_redacted,
            acceptance_original=acceptance_original,
            acceptance_redacted=acceptance_redacted,
        )
        with self.assertRaises(ValidationError):
            accept_work(
                work,
                board,
                18_500_000,
                invoice_original,
                invoice_redacted,
                acceptance_original,
                acceptance_redacted,
                signature,
                event_id,
                timestamp=timestamp,
            )
        work.status = WorkOrder.Status.AWAITING_ACCEPTANCE
        work.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            build_acceptance_evidence_payload(
                work,
                18_500_000.0,
                invoice_original,
                invoice_redacted,
                acceptance_original,
                acceptance_redacted,
                timestamp=timestamp,
            )
        with self.assertRaises(ValidationError):
            build_acceptance_evidence_payload(
                work,
                0,
                invoice_original,
                invoice_redacted,
                acceptance_original,
                acceptance_redacted,
                timestamp=timestamp,
            )

    def test_accept_work_rejects_cross_building_or_wrong_document_kind(self):
        (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
        ) = self.make_completed_work_inputs()
        other_building = Building.objects.create(name="Other")
        bad_original, bad_redacted = self.document_pair(
            other_building, Document.Kind.INVOICE, board.user, 41, "foreign-invoice"
        )
        with self.assertRaises(ValidationError):
            build_acceptance_evidence_payload(
                work,
                18_500_000,
                bad_original,
                bad_redacted,
                acceptance_original,
                acceptance_redacted,
                timestamp=work.completed_at,
            )
        wrong_kind_original, wrong_kind_redacted = self.document_pair(
            work.case.building, Document.Kind.QUOTATION, board.user, 42, "not-invoice"
        )
        with self.assertRaises(ValidationError):
            build_acceptance_evidence_payload(
                work,
                18_500_000,
                wrong_kind_original,
                wrong_kind_redacted,
                acceptance_original,
                acceptance_redacted,
                timestamp=work.completed_at,
            )

    def test_acceptance_is_insert_only_at_orm_and_database(self):
        (
            work,
            board,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
        ) = self.make_completed_work_inputs()
        signature, event_id, timestamp = self.sign_acceptance(
            work,
            board,
            invoice_original=invoice_original,
            invoice_redacted=invoice_redacted,
            acceptance_original=acceptance_original,
            acceptance_redacted=acceptance_redacted,
        )
        record = accept_work(
            work,
            board,
            18_500_000,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            signature,
            event_id,
            timestamp=timestamp,
        )
        record.actual_cost_vnd = 1
        with self.assertRaises(ValueError):
            record.save()
        with self.assertRaises(ValueError):
            record.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcceptanceRecord.objects.filter(pk=record.pk).update(actual_cost_vnd=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcceptanceRecord.objects.filter(pk=record.pk).delete()
