from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from lamto.accounts.models import Building, ManagementMembership, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import (
    BuildingLocation,
    CaseReport,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    TriageJob,
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
        membership = ManagementMembership.objects.create(user=operator, building=building)
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
        CaseReport.objects.create(case=case, report=report, grouped_by=operator)
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
        return membership, case, quotation, None

    def test_create_proposal_is_case_anchored_and_proposes_linked_reports(self):
        operator, case, _quotation, _account = self.make_signed_proposal_inputs()

        proposal = create_proposal(case, operator)

        self.assertEqual(proposal.case, case)
        case.decision.report.refresh_from_db()
        self.assertEqual(case.decision.report.status, IssueReport.Status.PROPOSED)

    def test_create_proposal_rejects_case_with_private_report(self):
        operator, case, _quotation, _account = self.make_signed_proposal_inputs()
        report = case.decision.report
        report.is_private = True
        report.save(update_fields=["is_private"])

        with self.assertRaisesMessage(
            ValidationError, "Private requests cannot become community proposals."
        ):
            create_proposal(case, operator)

    def test_create_proposal_rejects_active_completed_case(self):
        operator, case, _quotation, _account = self.make_signed_proposal_inputs()
        case.completed_at = timezone.now()
        case.save(update_fields=["completed_at"])

        with self.assertRaisesMessage(
            ValidationError, "An active uncompleted case is required."
        ):
            create_proposal(case, operator)

    def test_create_proposal_proposes_all_non_terminal_linked_reports_only(self):
        operator, case, _quotation, _account = self.make_signed_proposal_inputs()
        case = case
        source = case.decision.report
        pending = IssueReport.objects.create(
            reporter=source.reporter,
            unit=source.unit,
            text="Also shaking",
            selected_location=source.selected_location,
            location_path_snapshot=source.location_path_snapshot,
            status=IssueReport.Status.IN_REVIEW,
        )
        completed = IssueReport.objects.create(
            reporter=source.reporter,
            unit=source.unit,
            text="Already completed",
            selected_location=source.selected_location,
            location_path_snapshot=source.location_path_snapshot,
            status=IssueReport.Status.COMPLETED,
        )
        CaseReport.objects.create(case=case, report=pending, grouped_by=operator.user)
        CaseReport.objects.create(case=case, report=completed, grouped_by=operator.user)

        create_proposal(case, operator)

        source.refresh_from_db()
        pending.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(source.status, IssueReport.Status.PROPOSED)
        self.assertEqual(pending.status, IssueReport.Status.PROPOSED)
        self.assertEqual(completed.status, IssueReport.Status.COMPLETED)

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
        return "", event_id

    def test_submitted_version_is_signed_immutable_and_tied_to_case(self):
        operator, case, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(case, operator)
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
        operator, case, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(case, operator)
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
        self.assertEqual(second.number, 2)
        self.assertEqual(first.amount_vnd, 18_500_000)
        self.assertEqual(proposal.current_version_id, second.pk)
        self.assertEqual(proposal.status, proposal.Status.PUBLISHED)

    def test_submission_requires_positive_amount_and_safe_quotation_pair(self):
        operator, case, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(case, operator)
        signature, event_id = self.signed_submission(proposal, account, quotation)

        with self.assertRaises(ValidationError):
            submit_proposal_version(proposal, 0, "Company X", [quotation], signature, event_id)

        unsafe_document = Document.objects.create(
            building=case.building, kind=Document.Kind.QUOTATION
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

    def test_submission_uses_platform_signature_not_submitted_signature(self):
        operator, case, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(case, operator)
        bad_signature = "ignored client signature"
        version = submit_proposal_version(
            proposal, 18_500_000, "Company X", [quotation], bad_signature, "0x" + "cc" * 32
        )
        self.assertTrue(version.outbox_event.signer_address)

    def test_database_trigger_rejects_proposal_version_update_and_delete(self):
        operator, case, quotation, account = self.make_signed_proposal_inputs()
        proposal = create_proposal(case, operator)
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
