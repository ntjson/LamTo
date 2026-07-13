from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import Organization, OrganizationMembership
from lamto.accounts.services import grant_capability
from lamto.accounts.capabilities import PROPOSAL_APPROVE
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.approvals import (
    build_approval_evidence_payload,
    decide_proposal,
    proposal_is_locally_authorized,
)
from lamto.finance.models import ApprovalDecision, Proposal, ProposalVersion
from lamto.finance.proposals import create_proposal, submit_proposal_version
from lamto.finance.tests.test_proposals import ProposalVersionTests as _ProposalVersionTests


_make_signed_proposal_inputs = _ProposalVersionTests.make_signed_proposal_inputs
_signed_submission = _ProposalVersionTests.signed_submission
del _ProposalVersionTests


class ProposalApprovalTests(TestCase):
    def make_approver(self, building, role, suffix):
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        organization = Organization.objects.create(
            building=building, name=suffix, kind=OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role]
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )
        grant_capability(membership, PROPOSAL_APPROVE)
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        register_wallet(membership, account.address, proof)
        return membership, account

    def make_version_and_approvers(self):
        operator, work_order, quotation, account = (
            _make_signed_proposal_inputs(self)
        )
        proposal = create_proposal(work_order, operator)
        signature, event_id = _signed_submission(self, proposal, account, quotation)
        version = submit_proposal_version(
            proposal, 18_500_000, "Company X", [quotation], signature, event_id
        )
        board, board_account = self.make_approver(
            work_order.case.building, OrganizationMembership.Role.BOARD, "board"
        )
        representative, representative_account = self.make_approver(
            work_order.case.building,
            OrganizationMembership.Role.RESIDENT_REP,
            "representative",
        )
        self.accounts = {
            operator.pk: account,
            board.pk: board_account,
            representative.pk: representative_account,
        }
        self.board = board
        return version, board, representative

    def sign_decision(self, version, membership, decision, event_id):
        payload = build_approval_evidence_payload(version, membership, decision)
        previous_hash = "0x" + version.outbox_event.payload_hash
        if membership.organization.kind == Organization.Kind.RESIDENT_REP:
            board_payload = build_approval_evidence_payload(
                version, self.board, "APPROVE"
            )
            previous_hash = "0x" + payload_hash(board_payload)
        typed_data = build_evidence_typed_data(
            event_id,
            EvidenceType.BOARD_APPROVAL
            if membership.organization.kind == Organization.Kind.BOARD
            else EvidenceType.REPRESENTATIVE_APPROVAL,
            "0x" + payload_hash(payload),
            previous_hash,
        )
        return Account.sign_message(
            encode_typed_data(full_message=typed_data), self.accounts[membership.pk].key
        ).signature.hex()

    def approve_version(self, version, board, representative):
        board_event = "0x" + "b1" * 32
        rep_event = "0x" + "c1" * 32
        board_signature = self.sign_decision(version, board, "APPROVE", board_event)
        rep_signature = self.sign_decision(version, representative, "APPROVE", rep_event)
        decide_proposal(version, board, "APPROVE", "Within budget", board_signature, board_event)
        decide_proposal(
            version,
            representative,
            "APPROVE",
            "Evidence checked",
            rep_signature,
            rep_event,
        )
        return board_event, rep_event

    def test_two_local_signatures_authorize_work_while_chain_is_pending(self):
        version, board, representative = self.make_version_and_approvers()
        board_event, rep_event = self.approve_version(version, board, representative)

        version.refresh_from_db()
        version.proposal.work_order.refresh_from_db()
        self.assertTrue(proposal_is_locally_authorized(version))
        self.assertEqual(
            version.proposal.work_order.authorization_state,
            "AUTHORIZED",
        )
        self.assertEqual(
            set(
                BlockchainOutboxEvent.objects.filter(
                    event_id__in=[board_event, rep_event]
                ).values_list("status", flat=True)
            ),
            {BlockchainOutboxEvent.Status.PENDING},
        )

    def test_representative_must_follow_board_and_rejection_ends_proposal(self):
        version, board, representative = self.make_version_and_approvers()
        rep_event = "0x" + "d1" * 32
        rep_signature = self.sign_decision(version, representative, "APPROVE", rep_event)
        with self.assertRaises(ValidationError):
            decide_proposal(
                version, representative, "APPROVE", "Too early", rep_signature, rep_event
            )
        self.assertFalse(ApprovalDecision.objects.exists())

        board_event = "0x" + "e1" * 32
        board_signature = self.sign_decision(version, board, "REJECT", board_event)
        decision = decide_proposal(
            version, board, "REJECT", "Not within budget", board_signature, board_event
        )

        version.refresh_from_db()
        version.proposal.refresh_from_db()
        self.assertEqual(decision.decision, ApprovalDecision.Decision.REJECT)
        self.assertEqual(version.proposal.status, Proposal.Status.REJECTED)
        self.assertEqual(ApprovalDecision.objects.count(), 1)
        with self.assertRaises(ValidationError):
            decide_proposal(
                version, representative, "APPROVE", "After rejection", rep_signature, rep_event
            )

    def test_decisions_and_database_rows_are_append_only(self):
        version, board, representative = self.make_version_and_approvers()
        self.approve_version(version, board, representative)
        decision = ApprovalDecision.objects.get(
            version=version, stage=ApprovalDecision.Stage.BOARD
        )

        decision.reason = "changed"
        with self.assertRaises(ValueError):
            decision.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ApprovalDecision.objects.filter(pk=decision.pk).update(reason="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ApprovalDecision.objects.filter(pk=decision.pk).delete()

    def test_revision_invalidates_old_approvals_without_copying_them(self):
        version, board, representative = self.make_version_and_approvers()
        self.approve_version(version, board, representative)
        old_amount = version.amount_vnd
        proposal = version.proposal
        operator = proposal.creator_membership
        quotation = version.quotations.filter(variant="ORIGINAL").first()
        second_event = "0x" + "f1" * 32
        second_signature, _ = _signed_submission(
            self,
            proposal,
            self.accounts[operator.pk],
            quotation,
            amount_vnd=19_000_000,
            event_id=second_event,
            previous_hash="0x" + version.outbox_event.payload_hash,
            contractor_name="Company Y",
        )

        second = submit_proposal_version(
            proposal,
            19_000_000,
            "Company Y",
            [quotation],
            second_signature,
            second_event,
        )

        version.refresh_from_db()
        proposal.refresh_from_db()
        work_order = proposal.work_order
        work_order.refresh_from_db()
        self.assertEqual(version.amount_vnd, old_amount)
        self.assertEqual(ApprovalDecision.objects.filter(version=version).count(), 2)
        self.assertEqual(ApprovalDecision.objects.filter(version=second).count(), 0)
        self.assertFalse(proposal_is_locally_authorized(version))
        self.assertEqual(proposal.current_version_id, second.pk)
        self.assertEqual(proposal.status, Proposal.Status.IN_REVIEW)
        self.assertEqual(work_order.authorization_status, "PENDING")

    def test_signature_must_match_the_active_membership_wallet_and_snapshot(self):
        version, board, representative = self.make_version_and_approvers()
        event_id = "0x" + "a1" * 32
        payload = build_approval_evidence_payload(version, board, "APPROVE")
        typed_data = build_evidence_typed_data(
            event_id,
            EvidenceType.BOARD_APPROVAL,
            "0x" + payload_hash(payload),
            "0x" + version.outbox_event.payload_hash,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed_data), self.accounts[representative.pk].key
        ).signature.hex()
        with self.assertRaises(PermissionDenied):
            decide_proposal(version, board, "APPROVE", "Wrong wallet", signature, event_id)
        self.assertFalse(ApprovalDecision.objects.exists())

    def test_pending_anchor_label_clears_only_after_all_events_confirm(self):
        version, board, representative = self.make_version_and_approvers()
        board_event, rep_event = self.approve_version(version, board, representative)
        work_order = version.proposal.work_order

        self.assertEqual(work_order.verification_label, "Pending blockchain anchoring")
        self.assertEqual(version.verification_label, "Pending blockchain anchoring")
        BlockchainOutboxEvent.objects.filter(
            event_id__in=[version.outbox_event.event_id, board_event, rep_event]
        ).update(status=BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(work_order.verification_label, "Blockchain anchored")
