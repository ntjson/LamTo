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
from lamto.audit.models import AuditEvent
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    utc_rfc3339,
)
from lamto.finance.models import EmergencyAuthorization, EmergencyRatification
from lamto.finance.emergencies import (
    authorize_emergency,
    build_emergency_authorization_evidence_payload,
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

    def sign_ratification(
        self, authorization, membership, decision, reason, timestamp=None
    ):
        event_id = "0x" + "b1" * 32
        typed_data = build_emergency_ratification_evidence_typed_data(
            authorization, membership, decision, reason, event_id, timestamp=timestamp
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
        decided_at = authorization.authorized_at + timedelta(hours=1)
        decision_signature, decision_event = self.sign_ratification(
            authorization, representative, "REJECT", reason, timestamp=decided_at
        )
        outcome = decide_emergency(
            authorization, representative, "REJECT", reason,
            decision_signature, decision_event, now=decided_at,
        )
        self.assertLessEqual(outcome.decided_at, authorization.authorized_at + timedelta(hours=24))
        self.assertEqual(outcome.decision, "REJECT")
        self.assertEqual(
            outcome.outbox_event.payload["reason_digest"], payload_hash({"reason": reason})
        )
        self.assertNotIn("reason", outcome.outbox_event.payload)
        self.assertEqual(outcome.label, "Emergency")
        BlockchainOutboxEvent.objects.filter(
            pk__in=[authorization.outbox_event_id, outcome.outbox_event_id]
        ).update(status=BlockchainOutboxEvent.Status.CONFIRMED)
        started = type(started).objects.get(pk=started.pk)
        self.assertEqual(started.verification_label, "Blockchain anchored")

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
        self.assertEqual(outcome.label, "Emergency")
        BlockchainOutboxEvent.objects.filter(pk=authorization.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.CONFIRMED
        )
        work.refresh_from_db()
        self.assertEqual(work.verification_label, "Pending blockchain anchoring")
        attempted_at = timezone.now()
        decision_signature, decision_event = self.sign_ratification(
            authorization,
            representative,
            "REJECT",
            "Too late",
            timestamp=attempted_at,
        )
        with self.assertRaises(ValidationError):
            decide_emergency(
                authorization,
                representative,
                "REJECT",
                "Too late",
                decision_signature,
                decision_event,
                now=attempted_at,
            )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="emergency.reject", result="denied", target_id=str(authorization.pk)
            ).exists()
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
        decided_at = authorized_at + timedelta(hours=1)
        decision_signature, decision_event = self.sign_ratification(
            authorization,
            representative,
            "REJECT",
            "Signed representative reason",
            timestamp=decided_at,
        )

        with self.assertRaises(PermissionDenied):
            decide_emergency(
                authorization,
                representative,
                "REJECT",
                "Different supplied reason",
                decision_signature,
                decision_event,
                now=decided_at,
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

    def test_outcome_signature_timestamp_matches_persisted_decision(self):
        work, operator, board, representative, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorization = authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=authorized_at
        )
        signed_at = authorized_at + timedelta(hours=1)
        persisted_at = signed_at + timedelta(minutes=1)
        decision_signature, decision_event = self.sign_ratification(
            authorization,
            representative,
            "REJECT",
            "Signed decision time",
            timestamp=signed_at,
        )

        with self.assertRaises(PermissionDenied):
            decide_emergency(
                authorization,
                representative,
                "REJECT",
                "Signed decision time",
                decision_signature,
                decision_event,
                now=persisted_at,
            )
        self.assertFalse(
            EmergencyRatification.objects.filter(authorization=authorization).exists()
        )

        outcome = decide_emergency(
            authorization,
            representative,
            "REJECT",
            "Signed decision time",
            decision_signature,
            decision_event,
            now=signed_at,
        )
        self.assertEqual(outcome.decided_at, signed_at)
        self.assertEqual(
            outcome.outbox_event.payload["decision_timestamp"], utc_rfc3339(signed_at)
        )

    def _assert_decision_at_or_after_deadline_is_rejected(self, offset):
        work, operator, board, representative, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
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
        decided_at = authorization.ratification_deadline + offset
        decision_signature, decision_event = self.sign_ratification(
            authorization,
            representative,
            "REJECT",
            "Deadline reached",
            timestamp=decided_at,
        )

        with self.assertRaisesMessage(
            ValidationError, "Emergency ratification deadline has passed."
        ):
            decide_emergency(
                authorization,
                representative,
                "REJECT",
                "Deadline reached",
                decision_signature,
                decision_event,
                now=decided_at,
            )
        self.assertFalse(
            EmergencyRatification.objects.filter(authorization=authorization).exists()
        )

    def test_decision_at_deadline_is_rejected(self):
        self._assert_decision_at_or_after_deadline_is_rejected(timedelta(0))

    def test_decision_after_deadline_is_rejected(self):
        self._assert_decision_at_or_after_deadline_is_rejected(timedelta(microseconds=1))

    def test_requested_emergency_cannot_be_directly_authorized(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")

        with self.assertRaises(IntegrityError), transaction.atomic():
            type(requested).objects.filter(pk=requested.pk).update(
                authorization_status="AUTHORIZED"
            )
        requested.refresh_from_db()
        self.assertEqual(requested.authorization_status, "PENDING")

        authorized_at = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=authorized_at
        )
        requested.refresh_from_db()
        self.assertEqual(requested.authorization_status, "AUTHORIZED")

    def test_cannot_request_emergency_after_normal_authorization(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        work.authorization_status = type(work).AuthorizationStatus.AUTHORIZED
        work.save(update_fields=["authorization_status"])

        with self.assertRaisesMessage(
            ValidationError,
            "Cannot request emergency on an already authorized work order.",
        ):
            request_emergency(work, operator, "Active water leak")
        work.refresh_from_db()
        self.assertFalse(work.emergency)
        self.assertIsNone(work.emergency_requested_at)

        # Direct ORM conversion of already-AUTHORIZED non-emergency into emergency
        # must also fail while AUTHORIZED and no EmergencyAuthorization exists.
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(work).objects.filter(pk=work.pk).update(
                emergency=True,
                emergency_reason="Forged after authorization",
                emergency_requested_by=operator,
                emergency_requested_at=timezone.now(),
            )
        work.refresh_from_db()
        self.assertFalse(work.emergency)
        self.assertEqual(
            work.authorization_status, type(work).AuthorizationStatus.AUTHORIZED
        )

    def test_database_rejects_partial_emergency_request_identity(self):
        work, _, _, _, _ = self.make_emergency_actors()

        with self.assertRaises(IntegrityError), transaction.atomic():
            type(work).objects.filter(pk=work.pk).update(emergency=True)

    def test_database_requires_exact_24_hour_authorization_deadline(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        payload = build_emergency_authorization_evidence_payload(
            requested, 9_200_000, timestamp=authorized_at
        )
        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.EMERGENCY_AUTHORIZATION,
                payload,
                "0x" + "00" * 32,
                board,
                signature,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyAuthorization.objects.create(
                work_order=requested,
                reason=requested.emergency_reason,
                estimate_vnd=9_200_000,
                membership=board,
                wallet=event.signer_wallet,
                signature=event.signature,
                authorized_at=authorized_at,
                ratification_deadline=authorized_at + timedelta(hours=23),
                drill=requested.drill,
                label="Emergency",
                outbox_event=event,
            )

    def test_database_rejects_overdue_outcome_before_deadline(self):
        work, operator, board, _, _ = self.make_emergency_actors()
        requested = request_emergency(work, operator, "Active water leak")
        authorized_at = requested.emergency_requested_at
        signature, event_id = self.sign_emergency(
            requested, board, timestamp=authorized_at
        )
        authorization = authorize_emergency(
            requested, board, 9_200_000, signature, event_id, now=authorized_at
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            EmergencyRatification.objects.create(
                authorization=authorization,
                decision="OVERDUE",
                outcome="OVERDUE",
                reason="No decision by deadline.",
                decided_at=authorization.ratification_deadline - timedelta(seconds=1),
                label="Emergency",
            )
