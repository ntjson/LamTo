from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import PROPOSAL_CREATE
from lamto.accounts.models import Building, Organization, OrganizationMembership, Unit
from lamto.accounts.services import grant_capability
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    TriageJob,
    WorkOrder,
)
from lamto.finance.models import Proposal, ProposalDocument, ProposalVersion

from lamto.finance.proposals import (
    build_proposal_evidence_payload,
    create_proposal,
    submit_proposal_version,
)


class ProposalVersionTests(TestCase):
    def make_signed_proposal_inputs(self):
        building = Building.objects.create(name="Minh An Residence")
        location = BuildingLocation.objects.create(building=building, name="Lobby")
        unit = Unit.objects.create(building=building, label="A-1")
        operator = get_user_model().objects.create_user(
            email="operator@example.test", password="secret", display_name="Operator"
        )
        organization = Organization.objects.create(
            building=building, name="Operator", kind=Organization.Kind.OPERATOR
        )
        membership = OrganizationMembership.objects.create(
            user=operator,
            organization=organization,
            role=OrganizationMembership.Role.OPERATOR,
        )
        grant_capability(membership, PROPOSAL_CREATE)
        report = IssueReport.objects.create(
            reporter=get_user_model().objects.create_user(
                email="resident@example.test", password="secret", display_name="Resident"
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
            operator=operator,
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
            assignee=operator,
            priority="HIGH",
            deadline_at=case.deadline_at,
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.PENDING,
        )
        document = Document.objects.create(building=building, kind=Document.Kind.QUOTATION)
        quotation = DocumentVersion.objects.create(
            document=document,
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key="quotation-original",
            provider_version_id="quotation-original",
            filename="quotation.pdf",
            content_type="application/pdf",
            byte_size=10,
            sha256="1" * 64,
            uploader=operator,
        )
        DocumentVersion.objects.create(
            document=document,
            version=2,
            variant=DocumentVersion.Variant.REDACTED,
            storage_key="quotation-redacted",
            provider_version_id="quotation-redacted",
            filename="quotation-redacted.pdf",
            content_type="application/pdf",
            byte_size=9,
            sha256="2" * 64,
            uploader=operator,
            redacts=quotation,
        )
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        register_wallet(membership, account.address.lower(), proof)
        return membership, work_order, quotation, account

    def signed_submission(
        self,
        proposal,
        account,
        quotation,
        amount_vnd=18_500_000,
        event_id=None,
        previous_hash=None,
        contractor_name="Company X",
    ):
        event_id = event_id or "0x" + "aa" * 32
        previous_hash = previous_hash or "0x" + "00" * 32
        payload = build_proposal_evidence_payload(
            proposal, amount_vnd, contractor_name, [quotation]
        )
        typed_data = build_evidence_typed_data(
            event_id,
            EvidenceType.PROPOSAL_CREATED,
            "0x" + payload_hash(payload),
            previous_hash,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed_data), account.key
        ).signature.hex()
        return signature, event_id

    def test_submitted_version_is_signed_immutable_and_tied_to_work_order(self):
        operator, work_order, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(work_order, operator)
        signature, event_id = self.signed_submission(proposal, account, quotation)
        version = submit_proposal_version(
            proposal=proposal,
            amount_vnd=18_500_000,
            contractor_name="Company X",
            quotation_versions=[quotation],
            signature=signature,
            event_id=event_id,
        )

        self.assertEqual(version.number, 1)
        self.assertEqual(version.amount_vnd, 18_500_000)
        self.assertEqual(version.proposal_id, proposal.pk)
        self.assertEqual(version.outbox_event.event_id, event_id)
        version.amount_vnd = 1
        with self.assertRaises(ValueError):
            version.save()

    def test_revision_is_a_new_version_and_resets_normal_authorization(self):
        operator, work_order, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(work_order, operator)
        first_signature, first_event_id = self.signed_submission(proposal, account, quotation)
        first = submit_proposal_version(
            proposal, 18_500_000, "Company X", [quotation], first_signature, first_event_id
        )
        second_event_id = "0x" + "bb" * 32
        second_signature, _ = self.signed_submission(
            proposal,
            account,
            quotation,
            amount_vnd=19_000_000,
            event_id=second_event_id,
            previous_hash="0x" + first.outbox_event.payload_hash,
            contractor_name="Company Y",
        )

        second = submit_proposal_version(
            proposal,
            19_000_000,
            "Company Y",
            [quotation],
            second_signature,
            second_event_id,
        )

        first.refresh_from_db()
        proposal.refresh_from_db()
        work_order.refresh_from_db()
        self.assertEqual(second.number, 2)
        self.assertEqual(first.amount_vnd, 18_500_000)
        self.assertEqual(proposal.current_version_id, second.pk)
        self.assertEqual(proposal.status, proposal.Status.NORMAL_AUTHORIZED)
        self.assertEqual(work_order.authorization_status, WorkOrder.AuthorizationStatus.AUTHORIZED)

    def test_submission_requires_positive_amount_and_safe_quotation_pair(self):
        operator, work_order, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(work_order, operator)
        signature, event_id = self.signed_submission(proposal, account, quotation)

        with self.assertRaises(ValidationError):
            submit_proposal_version(proposal, 0, "Company X", [quotation], signature, event_id)

        unsafe_document = Document.objects.create(
            building=work_order.case.building, kind=Document.Kind.QUOTATION
        )
        unsafe_quotation = DocumentVersion.objects.create(
            document=unsafe_document,
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key="quotation-without-redaction",
            provider_version_id="quotation-without-redaction",
            filename="quotation.pdf",
            content_type="application/pdf",
            byte_size=10,
            sha256="3" * 64,
            uploader=operator.user,
        )
        with self.assertRaises(ValidationError):
            submit_proposal_version(
                proposal, 18_500_000, "Company X", [unsafe_quotation], signature, event_id
            )

    def test_submission_rejects_bad_signature_before_creating_version(self):
        operator, work_order, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(work_order, operator)
        other_account = Account.create()
        payload = build_proposal_evidence_payload(
            proposal, 18_500_000, "Company X", [quotation]
        )
        typed_data = build_evidence_typed_data(
            "0x" + "cc" * 32,
            EvidenceType.PROPOSAL_CREATED,
            "0x" + payload_hash(payload),
            "0x" + "00" * 32,
        )
        bad_signature = Account.sign_message(
            encode_typed_data(full_message=typed_data), other_account.key
        ).signature.hex()
        with self.assertRaises(PermissionDenied):
            submit_proposal_version(
                proposal, 18_500_000, "Company X", [quotation], bad_signature, "0x" + "cc" * 32
            )
        self.assertFalse(ProposalVersion.objects.filter(proposal=proposal).exists())

    def test_database_trigger_rejects_proposal_version_update_and_delete(self):
        operator, work_order, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(work_order, operator)
        signature, event_id = self.signed_submission(proposal, account, quotation)
        version = submit_proposal_version(
            proposal, 18_500_000, "Company X", [quotation], signature, event_id
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProposalVersion.objects.filter(pk=version.pk).update(amount_vnd=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProposalVersion.objects.filter(pk=version.pk).delete()

        link = ProposalDocument.objects.filter(proposal_version=version).first()
        with self.assertRaises(ValueError):
            link.document_version = quotation
            link.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProposalDocument.objects.filter(pk=link.pk).update(document_version_id=quotation.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProposalDocument.objects.filter(pk=link.pk).delete()
