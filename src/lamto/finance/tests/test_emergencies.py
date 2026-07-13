from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import EMERGENCY_AUTHORIZE, PROPOSAL_APPROVE, WORK_ASSIGN
from lamto.accounts.models import Organization, OrganizationMembership
from lamto.accounts.services import grant_capability
from lamto.evidence.canonical import payload_hash
from lamto.evidence.services import begin_wallet_registration, register_wallet, utc_rfc3339
from lamto.finance.models import EmergencyAuthorization, EmergencyRatification
from lamto.finance.emergencies import (
    authorize_emergency,
    build_emergency_authorization_evidence_typed_data,
    build_emergency_ratification_evidence_typed_data,
    decide_emergency,
    mark_overdue_ratifications,
    request_emergency,
)
from lamto.finance.tests.test_proposals import ProposalVersionTests as _ProposalVersionTests
from lamto.maintenance.workorders import start_work_order


_make_signed_proposal_inputs = _ProposalVersionTests.make_signed_proposal_inputs
del _ProposalVersionTests


class EmergencyFlowTests(TestCase):
    def make_signer(self, building, role, capability, suffix):
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

    def make_emergency_actors(self):
        operator, work_order, _, _ = _make_signed_proposal_inputs(self)
        grant_capability(operator, WORK_ASSIGN)
        maintenance = get_user_model().objects.create_user(
            email="maintenance@example.test", password="secret", display_name="Maintenance"
        )
        OrganizationMembership.objects.create(
            user=maintenance,
            organization=operator.organization,
            role=OrganizationMembership.Role.MAINTENANCE,
        )
        work_order.assignee = maintenance
        work_order.save(update_fields=["assignee"])
        board, board_account = self.make_signer(
            work_order.case.building,
            OrganizationMembership.Role.BOARD,
            EMERGENCY_AUTHORIZE,
            "board",
        )
        representative, representative_account = self.make_signer(
            work_order.case.building,
            OrganizationMembership.Role.RESIDENT_REP,
            PROPOSAL_APPROVE,
            "representative",
        )
        self.accounts = {board.pk: board_account, representative.pk: representative_account}
        return work_order, operator, board, representative, maintenance

    def sign_emergency(self, work_order, membership, estimate_vnd=9_200_000, timestamp=None):
        event_id = "0x" + "a1" * 32
        typed_data = build_emergency_authorization_evidence_typed_data(
            work_order, membership, estimate_vnd, event_id, timestamp=timestamp
        )
        return (
            Account.sign_message(
                encode_typed_data(full_message=typed_data), self.accounts[membership.pk].key
            ).signature.hex(),
            event_id,
        )

    def sign_ratification(self, authorization, membership, decision, reason):
        event_id = "0x" + "b1" * 32
        typed_data = build_emergency_ratification_evidence_typed_data(
            authorization, membership, decision, reason, event_id
        )
        return (
            Account.sign_message(
                encode_typed_data(full_message=typed_data), self.accounts[membership.pk].key
            ).signature.hex(),
            event_id,
        )

    def test_board_signature_allows_start_before_chain_and_rep_records_outcome(self):
        work, operator, board, representative, maintenance = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
        authorization_signature, auth_event = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorization = authorize_emergency(
            requested, board, 9_200_000,
            authorization_signature, auth_event, now=authorized_at,
        )

        started = start_work_order(work, maintenance)
        self.assertEqual(started.status, "IN_PROGRESS")
        self.assertEqual(started.verification_label, "Pending blockchain anchoring")

        reason = "Insufficient estimate detail"
        decision_signature, decision_event = self.sign_ratification(
            authorization, representative, "REJECT", reason
        )
        outcome = decide_emergency(
            authorization, representative, "REJECT", reason,
            decision_signature, decision_event,
        )
        self.assertLessEqual(outcome.decided_at, authorization.authorized_at + timedelta(hours=24))
        self.assertEqual(outcome.decision, "REJECT")
        self.assertEqual(
            outcome.outbox_event.payload["reason_digest"], payload_hash({"reason": reason})
        )
        self.assertNotIn("reason", outcome.outbox_event.payload)

    def test_request_is_immutable_and_authorization_copies_emergency_identity(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak", drill=True)
        now = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(requested, board, timestamp=now)
        authorization = authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=now
        )

        self.assertEqual(authorization.reason, "Active water leak")
        self.assertEqual(authorization.ratification_deadline, now + timedelta(hours=24))
        self.assertEqual(authorization.label, "Emergency drill")
        self.assertEqual(requested.emergency_label, "Emergency drill")
        authorization.reason = "changed"
        with self.assertRaises(ValueError):
            authorization.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(requested).objects.filter(pk=requested.pk).update(emergency=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyAuthorization.objects.filter(pk=authorization.pk).update(reason="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyAuthorization.objects.filter(pk=authorization.pk).delete()

    def test_overdue_outcome_is_unsigned_idempotent_and_prevents_late_replacement(self):
        work, operator, board, representative, _ = self.make_emergency_actors()
        requested_at = timezone.now() - timedelta(hours=26)
        with patch("lamto.finance.emergencies.timezone.now", return_value=requested_at):
            requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorization = authorize_emergency(
            requested,
            board,
            9_200_000,
            signature,
            event_id,
            now=authorized_at,
        )

        self.assertEqual(mark_overdue_ratifications(timezone.now()), 1)
        self.assertEqual(mark_overdue_ratifications(timezone.now()), 0)
        outcome = EmergencyRatification.objects.get(authorization=authorization)
        self.assertEqual(outcome.outcome, "OVERDUE")
        self.assertIsNone(outcome.membership)
        self.assertIsNone(outcome.outbox_event)
        decision_signature, decision_event = self.sign_ratification(
            authorization, representative, "REJECT", "Too late"
        )
        with self.assertRaises(ValidationError):
            decide_emergency(
                authorization,
                representative,
                "REJECT",
                "Too late",
                decision_signature,
                decision_event,
            )
        self.assertEqual(EmergencyRatification.objects.filter(authorization=authorization).count(), 1)
        outcome.reason = "changed"
        with self.assertRaises(ValueError):
            outcome.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyRatification.objects.filter(pk=outcome.pk).update(reason="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyRatification.objects.filter(pk=outcome.pk).delete()

    def test_authorization_rejects_timestamp_before_request(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        signature, event_id = self.sign_emergency(requested, board)

        with self.assertRaisesMessage(
            ValidationError, "Authorization time cannot precede the emergency request."
        ):
            authorize_emergency(
                requested,
                board,
                9_200_000,
                signature,
                event_id,
                now=requested.emergency_requested_at - timedelta(seconds=1),
            )

    def test_authorization_signature_timestamp_matches_record_and_deadline(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at + timedelta(minutes=5)
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )

        authorization = authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=authorized_at
        )

        self.assertEqual(authorization.authorized_at, authorized_at)
        self.assertEqual(
            authorization.outbox_event.payload["authorization_timestamp"],
            utc_rfc3339(authorized_at),
        )
        self.assertEqual(
            authorization.ratification_deadline, authorized_at + timedelta(hours=24)
        )

    def test_representative_signature_binds_exact_outcome_reason(self):
        work, operator, board, representative, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorization = authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=authorized_at
        )
        decision_signature, decision_event = self.sign_ratification(
            authorization, representative, "REJECT", "Signed representative reason"
        )

        with self.assertRaises(PermissionDenied):
            decide_emergency(
                authorization,
                representative,
                "REJECT",
                "Different supplied reason",
                decision_signature,
                decision_event,
            )
        self.assertFalse(
            EmergencyRatification.objects.filter(authorization=authorization).exists()
        )

    def test_database_rejects_invalid_human_ratification_provenance(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorization = authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=authorized_at
        )
        fields = {
            "authorization": authorization,
            "reason": "Representative reason",
            "membership": authorization.membership,
            "wallet": authorization.wallet,
            "outbox_event": authorization.outbox_event,
            "decided_at": timezone.now(),
            "label": "Emergency",
        }

        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyRatification.objects.create(
                decision="RATIFY", outcome="RATIFIED", signature="", **fields
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyRatification.objects.create(
                decision="RATIFY",
                outcome="REJECTED",
                signature=authorization.signature,
                **fields,
            )
