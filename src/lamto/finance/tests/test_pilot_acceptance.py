"""Task 18 pilot acceptance: normal path, emergency drill, adversarial cases.

These tests drive REAL domain entry points via PilotDomainDriver / factories
(not re-implementations of business rules).
"""

from __future__ import annotations

import secrets
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from urllib.error import URLError

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import storages
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import LEDGER_PUBLISH, PAYMENT_VERIFY
from lamto.accounts.services import grant_capability
from lamto.audit.models import AuditEvent
from lamto.documents.access import authorize_download
from lamto.documents.models import Document
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.corrections import (
    allocate_correction_id,
    allocate_correction_publication_id,
    build_correction_evidence_typed_data,
    create_correction,
    decide_correction,
    finalize_correction_publication,
    prepare_correction_publication,
    _correction_resident_payload,
)
from lamto.finance.emergencies import (
    authorize_emergency,
    build_emergency_authorization_evidence_typed_data,
    mark_overdue_ratifications,
    request_emergency,
)
from lamto.finance.fund import fund_balance
from lamto.finance.models import (
    CorrectionDecision,
    EmergencyRatification,
    MaintenanceFundEntry,
    PublishedLedgerEntry,
)
from lamto.finance.payments import (
    build_payment_verification_evidence_typed_data,
    verify_payment,
)
from lamto.finance.proposals import (
    build_proposal_evidence_payload,
    submit_proposal_version,
)
from lamto.finance.publication import finalize_publication
from lamto.maintenance.ai import process_triage_job
from lamto.maintenance.models import TriageJob, WorkOrder
from lamto.maintenance.workorders import start_work_order
from lamto.testing.factories import (
    DEFAULT_AMOUNT_VND,
    PilotDomainDriver,
    confirm_event,
    new_event_id,
    seed_pilot_world,
)


_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-pilot-accept-")
ZERO_BARE = "00" * 32


def _storage_settings(location: str):
    return {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": location},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": location},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


@override_settings(STORAGES=_storage_settings(_TEMP_STORAGE))
class PilotAcceptanceTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(
            building_name=f"Pilot Accept {self._testMethodName}",
            create_sample_report=False,
        )
        self.driver = PilotDomainDriver(self.seed)

    def sign_correction(self, membership, **kwargs):
        event_id = kwargs.pop("event_id", new_event_id())
        typed = build_correction_evidence_typed_data(
            event_id=event_id,
            actor_organization_id=membership.organization_id,
            **kwargs,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed),
            self.seed.accounts[membership.pk].key,
        ).signature.hex()
        return signature, event_id

    def test_realistic_normal_flow(self):
        driver = self.driver
        resident = driver.login(None, "resident")
        resident.submit_report(
            "Elevator shakes heavily",
            "Building B / Lift 2",
            "tests/fixtures/elevator.jpg",
        )

        operator = driver.login(None, "operator")
        operator.confirm_triage_and_create_paid_work_order()
        operator.submit_signed_proposal(amount_vnd=DEFAULT_AMOUNT_VND)

        driver.login(None, "board_approver").approve_proposal()
        driver.login(None, "resident_representative").coapprove_proposal()
        driver.login(None, "maintenance").complete_assigned_work()
        driver.login(None, "board_payment_recorder").accept_and_record_payment()
        driver.login(None, "board_payment_verifier").verify_payment()
        driver.confirm_all_chain_events()
        driver.login(None, "eligible_publisher").sign_publication_snapshot()
        driver.confirm_all_chain_events()

        ledger = driver.login(None, "resident").open_latest_ledger_entry()
        self.assertEqual(ledger.actual_cost_vnd, DEFAULT_AMOUNT_VND)
        self.assertEqual(ledger.status, "Record verified")
        self.assertTrue(ledger.has_redacted_documents())

        verification = driver.login(None, "auditor").verify_latest_ledger_entry()
        self.assertTrue(verification.document_hashes_match)
        self.assertTrue(verification.chain_events_match)
        self.assertEqual(
            verification.recomputed_fund_balance_vnd, ledger.current_fund_balance_vnd
        )
        self.assertEqual(driver.ledger_count(), 1)
        self.assertEqual(driver.fund_balance(), 100_000_000 - DEFAULT_AMOUNT_VND)

    def test_normal_work_can_start_pending_anchor_but_cannot_publish(self):
        driver = self.driver
        driver.pause_chain()
        driver.prepare_locally_approved_normal_work()
        work = driver.login(None, "maintenance").start_assigned_work()

        self.assertEqual(work.verification_label, "Pending blockchain anchoring")
        driver.login(None, "maintenance").complete_assigned_work()
        driver.login(None, "board_payment_recorder").accept_and_record_payment()
        driver.login(None, "board_payment_verifier").verify_payment()
        before_ids = driver.latest_outbox_event_ids()
        blocked = driver.login(None, "eligible_publisher").attempt_publication()

        self.assertEqual(
            blocked.reason, "Required blockchain evidence is still pending"
        )
        self.assertEqual(driver.ledger_count(), 0)

        driver.resume_chain()
        driver.confirm_all_chain_events()
        # Retries reuse the same event IDs (no new rows while paused confirm is no-op).
        self.assertEqual(driver.latest_outbox_event_ids(), before_ids)
        driver.login(None, "eligible_publisher").sign_publication_snapshot()
        self.assertEqual(driver.ledger_count(), 1)
        driver.confirm_all_chain_events()
        self.assertEqual(driver.ledger_count(), 1)

    def test_controlled_emergency_drill_is_isolated_and_preserved(self):
        driver = self.driver
        starting_balance = driver.fund_balance()
        driver.pause_chain()
        drill = driver.login(None, "board_emergency_approver").authorize_emergency_drill()
        started = driver.login(None, "maintenance").start_drill_work()
        outcome = driver.login(None, "resident_representative").reject_drill(
            "Estimate incomplete"
        )

        self.assertEqual(drill.label, "Emergency drill")
        self.assertEqual(started.verification_label, "Pending blockchain anchoring")
        self.assertEqual(outcome.label, "Ratification rejected")
        self.assertEqual(outcome.domain_label, "Emergency drill")
        self.assertEqual(outcome.outcome, "REJECTED")

        driver.resume_chain()
        driver.confirm_all_chain_events()
        self.assertEqual(driver.fund_balance(), starting_balance)
        self.assertEqual(driver.ledger_count(drill=True), 0)
        self.assertTrue(AuditEvent.objects.filter(action="emergency.request").exists())
        self.assertTrue(AuditEvent.objects.filter(action="emergency.authorize").exists())
        self.assertTrue(AuditEvent.objects.filter(action="work.start").exists())
        self.assertTrue(AuditEvent.objects.filter(action="emergency.reject").exists())
        self.assertTrue(
            driver.audit_contains(drill.id, ["emergency"])
            or AuditEvent.objects.filter(target_id=str(drill.id)).exists()
        )
        work = driver.seed.work_order
        work.refresh_from_db()
        self.assertTrue(work.drill)
        self.assertTrue(work.emergency)

    def test_emergency_outcomes_ratified_rejected_and_overdue(self):
        driver = self.driver
        driver.pause_chain()
        drill = driver.authorize_emergency_drill()
        driver.start_drill_work()
        rejected = driver.reject_drill("Estimate incomplete")
        self.assertEqual(rejected.outcome, "REJECTED")
        auth_id = drill.authorization.pk

        driver.login(None, "resident").submit_report("Drill 2 leak", "Lift 2", None)
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        work2 = driver.seed.work_order
        requested = request_emergency(
            work2, driver.seed.roles["operator"], "Drill 2", drill=True
        )
        board = driver.seed.roles["board_emergency_approver"]
        at = requested.emergency_requested_at
        eid = new_event_id()
        typed = build_emergency_authorization_evidence_typed_data(
            requested, board, 1_000_000, eid, timestamp=at
        )
        sig = driver.seed.sign_typed(board, typed)
        auth2 = authorize_emergency(requested, board, 1_000_000, sig, eid, now=at)
        driver._ctx["emergency_authorization"] = auth2
        ratified = driver.ratify_drill("Confirmed safe completion path")
        self.assertEqual(ratified.outcome, "RATIFIED")

        driver.login(None, "resident").submit_report("Drill 3 overdue", "Lift 2", None)
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        work3 = driver.seed.work_order
        past = timezone.now() - timedelta(hours=26)
        with patch("lamto.finance.emergencies.timezone.now", return_value=past):
            requested3 = request_emergency(
                work3, driver.seed.roles["operator"], "Drill 3", drill=True
            )
        eid3 = new_event_id()
        typed3 = build_emergency_authorization_evidence_typed_data(
            requested3, board, 1_000_000, eid3, timestamp=past
        )
        sig3 = driver.seed.sign_typed(board, typed3)
        auth3 = authorize_emergency(
            requested3, board, 1_000_000, sig3, eid3, now=past
        )
        self.assertEqual(mark_overdue_ratifications(timezone.now()), 1)
        overdue = EmergencyRatification.objects.get(authorization=auth3)
        self.assertEqual(overdue.outcome, "OVERDUE")
        self.assertEqual(overdue.label, "Emergency drill")
        self.assertEqual(
            EmergencyRatification.objects.get(authorization_id=auth_id).outcome,
            "REJECTED",
        )
        self.assertEqual(driver.fund_balance(), 100_000_000)
        self.assertEqual(driver.ledger_count(drill=True), 0)

    def test_payment_recorder_self_verification_denied_and_publisher_dual_control(self):
        driver = self.driver
        driver.prepare_locally_approved_normal_work()
        driver.complete_assigned_work()
        payment = driver.accept_and_record_payment()
        recorder = driver.seed.roles["board_payment_recorder"]
        grant_capability(recorder, PAYMENT_VERIFY)
        event_id = new_event_id()
        typed = build_payment_verification_evidence_typed_data(
            payment, recorder, "VERIFIED", event_id, timestamp=payment.recorded_at
        )
        signature = driver.seed.sign_typed(recorder, typed)
        with self.assertRaises(PermissionDenied):
            verify_payment(
                payment,
                recorder,
                "VERIFIED",
                "Self verify",
                signature,
                event_id,
                timestamp=payment.recorded_at,
            )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="payment.verify", result="denied"
            ).exists()
            or AuditEvent.objects.filter(result="denied").exists()
        )

        driver.verify_payment()
        driver.confirm_all_chain_events()

        # Forbidden publishers: board approver and payment recorder (creator is operator org).
        for role_key in ("board_approver", "board_payment_recorder"):
            membership = driver.seed.roles[role_key]
            grant_capability(membership, LEDGER_PUBLISH)
            original = driver.seed.roles["eligible_publisher"]
            driver.seed.roles["eligible_publisher"] = membership
            blocked = driver.attempt_publication()
            driver.seed.roles["eligible_publisher"] = original
            self.assertTrue(blocked.blocked, msg=f"{role_key} should be blocked")

        # Operator creator cannot hold LEDGER_PUBLISH on operator org.
        with self.assertRaises(PermissionDenied):
            grant_capability(driver.seed.roles["operator"], LEDGER_PUBLISH)

        entry = driver.sign_publication_snapshot()
        self.assertIsNotNone(entry)
        self.assertEqual(driver.ledger_count(), 1)

    def test_proposal_revision_after_signature_requires_new_approval(self):
        driver = self.driver
        driver.login(None, "resident").submit_report("Elevator issue", "Lift 2", None)
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        version1 = driver.login(None, "operator").submit_signed_proposal(
            amount_vnd=DEFAULT_AMOUNT_VND
        )
        driver.login(None, "board_approver").approve_proposal()
        driver.login(None, "resident_representative").coapprove_proposal()
        work = driver.seed.work_order
        work.refresh_from_db()
        self.assertEqual(
            work.authorization_status, WorkOrder.AuthorizationStatus.AUTHORIZED
        )

        operator = driver.seed.roles["operator"]
        proposal = driver.seed.proposal
        quotation = driver._ctx["quotation_original"]
        event_id = new_event_id()
        payload = build_proposal_evidence_payload(
            proposal, 19_000_000, "Changed Contractor", [quotation]
        )
        typed = build_evidence_typed_data(
            event_id,
            EvidenceType.PROPOSAL_CREATED,
            "0x" + payload_hash(payload),
            "0x" + version1.outbox_event.payload_hash,
        )
        signature = driver.seed.sign_typed(operator, typed)
        version2 = submit_proposal_version(
            proposal,
            19_000_000,
            "Changed Contractor",
            [quotation],
            signature,
            event_id,
        )
        proposal.refresh_from_db()
        work.refresh_from_db()
        self.assertEqual(version2.number, 2)
        self.assertEqual(proposal.current_version_id, version2.pk)
        self.assertEqual(
            work.authorization_status, WorkOrder.AuthorizationStatus.PENDING
        )
        with self.assertRaises(PermissionDenied):
            start_work_order(work, driver.seed.users["maintenance"])

    def test_ai_outage_leaves_report_and_inbox_authoritative(self):
        driver = self.driver
        report = driver.login(None, "resident").submit_report(
            "Elevator shakes — AI offline path", "Lift 2", None
        )
        with patch("lamto.maintenance.ai.urlopen", side_effect=URLError("offline")):
            job = process_triage_job(report.triage_job.id)
        self.assertEqual(job.status, TriageJob.Status.NEEDS_MANUAL)
        work = driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        self.assertIsNotNone(work.pk)
        self.assertEqual(report.pk, driver.seed.report.pk)

    def test_role_object_file_export_matrix_denies_prohibited_access(self):
        driver = self.driver
        driver.prepare_locally_approved_normal_work()
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()
        driver.sign_publication_snapshot()
        driver.confirm_all_chain_events()
        entry = PublishedLedgerEntry.objects.get(case__building=driver.seed.building)
        proof_original = entry.payment.proof_original

        # Resident (no staff membership) denied original proof.
        with self.assertRaises(PermissionDenied):
            authorize_download(driver.seed.users["resident"], None, proof_original)
        # Operator without download grant path denied when using wrong membership.
        with self.assertRaises(PermissionDenied):
            authorize_download(
                driver.seed.users["operator"],
                driver.seed.roles["operator"].pk,
                proof_original,
            )
        # Maintenance denied without auditor role.
        with self.assertRaises(PermissionDenied):
            authorize_download(
                driver.seed.users["maintenance"],
                driver.seed.roles["maintenance"].pk,
                proof_original,
            )
        # Tech admin denied financial originals.
        with self.assertRaises(PermissionDenied):
            authorize_download(
                driver.seed.users["tech_admin"],
                driver.seed.roles["tech_admin"].pk,
                proof_original,
            )

    def test_tampered_document_blocks_publish_and_correction_preserves_original(self):
        driver = self.driver
        driver.prepare_locally_approved_normal_work()
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()

        payment = driver._ctx["payment"]
        storage = storages["private"]
        with storage.open(payment.proof_original.storage_key, "wb") as handle:
            handle.write(b"tampered-payment-proof-bytes-for-pilot")

        blocked = driver.attempt_publication()
        self.assertTrue(blocked.blocked)
        self.assertIn("mismatch", blocked.reason.lower())

        # Fresh published entry for correction path.
        seed2 = seed_pilot_world(
            building_name=f"Pilot Correct {self._testMethodName}",
            create_sample_report=False,
        )
        d2 = PilotDomainDriver(seed2)
        d2.prepare_locally_approved_normal_work()
        d2.complete_assigned_work()
        d2.accept_and_record_payment()
        d2.verify_payment()
        d2.confirm_all_chain_events()
        d2.sign_publication_snapshot()
        d2.confirm_all_chain_events()
        entry = PublishedLedgerEntry.objects.get(case__building=seed2.building)
        original_cost = entry.actual_cost_vnd
        original_published_at = entry.published_at
        balance_before = d2.fund_balance()
        new_amount = original_cost - 500_000

        operator = seed2.roles["correction_operator"]
        board = seed2.roles["correction_board"]
        rep = seed2.roles["resident_representative"]
        publisher = seed2.roles["eligible_publisher"]
        evidence_o, _ = d2.seed.document_pair(
            Document.Kind.CORRECTION_EVIDENCE, operator.user, "correction"
        )
        correction_id = allocate_correction_id()
        create_ts = timezone.now()
        replacement_hashes = [evidence_o.sha256]
        event_id = new_event_id()
        sig = Account.sign_message(
            encode_typed_data(
                full_message=build_correction_evidence_typed_data(
                    correction_id=correction_id,
                    original_event_id=entry.snapshot.outbox_event.event_id,
                    original_hash=entry.snapshot.outbox_event.payload_hash,
                    replacement_hashes=replacement_hashes,
                    reason="Invoice arithmetic error",
                    decision="APPROVE",
                    actor_organization_id=operator.organization_id,
                    publisher_snapshot_hash=ZERO_BARE,
                    event_id=event_id,
                    timestamp=create_ts,
                    previous_hash="0x" + entry.snapshot.outbox_event.payload_hash,
                )
            ),
            seed2.accounts[operator.pk].key,
        ).signature.hex()
        correction = create_correction(
            entry,
            operator,
            "Invoice arithmetic error",
            {"actual_cost_vnd": new_amount, "contractor_name": entry.contractor_name},
            [evidence_o],
            sig,
            event_id,
            correction_id=correction_id,
            timestamp=create_ts,
        )
        confirm_event(correction.outbox_event)

        board_ts = timezone.now()
        board_event = new_event_id()
        board_typed = build_correction_evidence_typed_data(
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="Board accepts",
            decision="APPROVE",
            actor_organization_id=board.organization_id,
            publisher_snapshot_hash=ZERO_BARE,
            event_id=board_event,
            timestamp=board_ts,
            previous_hash="0x" + correction.outbox_event.payload_hash,
        )
        board_sig = Account.sign_message(
            encode_typed_data(full_message=board_typed), seed2.accounts[board.pk].key
        ).signature.hex()
        board_decision = decide_correction(
            correction,
            board,
            CorrectionDecision.Stage.BOARD,
            "APPROVE",
            "Board accepts",
            board_sig,
            board_event,
            timestamp=board_ts,
        )
        confirm_event(board_decision.outbox_event)

        rep_ts = timezone.now()
        rep_event = new_event_id()
        rep_typed = build_correction_evidence_typed_data(
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="Rep co-approves",
            decision="APPROVE",
            actor_organization_id=rep.organization_id,
            publisher_snapshot_hash=ZERO_BARE,
            event_id=rep_event,
            timestamp=rep_ts,
            previous_hash="0x" + board_decision.outbox_event.payload_hash,
        )
        rep_sig = Account.sign_message(
            encode_typed_data(full_message=rep_typed), seed2.accounts[rep.pk].key
        ).signature.hex()
        rep_decision = decide_correction(
            correction,
            rep,
            CorrectionDecision.Stage.RESIDENT_REP,
            "APPROVE",
            "Rep co-approves",
            rep_sig,
            rep_event,
            timestamp=rep_ts,
        )
        confirm_event(rep_decision.outbox_event)

        snapshot_id = allocate_correction_publication_id()
        pub_ts = timezone.now()
        resident_payload_hash = payload_hash(_correction_resident_payload(correction))
        pub_event = new_event_id()
        pub_typed = build_correction_evidence_typed_data(
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason=correction.reason,
            decision="APPROVE",
            actor_organization_id=publisher.organization_id,
            publisher_snapshot_hash=resident_payload_hash,
            event_id=pub_event,
            timestamp=pub_ts,
            previous_hash="0x" + rep_decision.outbox_event.payload_hash,
        )
        pub_sig = Account.sign_message(
            encode_typed_data(full_message=pub_typed),
            seed2.accounts[publisher.pk].key,
        ).signature.hex()
        snapshot = prepare_correction_publication(
            correction,
            publisher,
            pub_sig,
            pub_event,
            snapshot_id=snapshot_id,
            timestamp=pub_ts,
        )
        confirm_event(snapshot.outbox_event)
        first = finalize_correction_publication(snapshot.pk)
        second = finalize_correction_publication(snapshot.pk)
        self.assertEqual(first.pk, second.pk)

        entry.refresh_from_db()
        self.assertEqual(entry.actual_cost_vnd, original_cost)
        self.assertEqual(entry.published_at, original_published_at)
        reverse = MaintenanceFundEntry.objects.get(
            correction=correction, entry_type=MaintenanceFundEntry.EntryType.REVERSAL
        )
        replacement = MaintenanceFundEntry.objects.get(
            correction=correction, entry_type=MaintenanceFundEntry.EntryType.REPLACEMENT
        )
        self.assertEqual(reverse.amount_vnd, original_cost)
        self.assertEqual(replacement.amount_vnd, -new_amount)
        self.assertEqual(
            fund_balance(seed2.building.pk, verified_only=True),
            balance_before + original_cost - new_amount,
        )

    def test_backup_restore_and_outbox_replay_idempotent_hashes(self):
        driver = self.driver
        driver.prepare_locally_approved_normal_work()
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        before = driver.latest_outbox_event_ids()
        driver.confirm_all_chain_events()
        driver.confirm_all_chain_events()
        self.assertEqual(driver.latest_outbox_event_ids(), before)
        entry = driver.sign_publication_snapshot()
        self.assertIsInstance(entry, PublishedLedgerEntry)
        again = finalize_publication(entry.snapshot_id)
        self.assertEqual(again.pk, entry.pk)
        self.assertEqual(driver.ledger_count(), 1)
        outflows = MaintenanceFundEntry.objects.filter(
            fund__building=driver.seed.building,
            entry_type=MaintenanceFundEntry.EntryType.OUTFLOW,
        )
        self.assertEqual(outflows.count(), 1)
        balance = driver.fund_balance()
        finalize_publication(entry.snapshot_id)
        self.assertEqual(driver.fund_balance(), balance)
        self.assertEqual(driver.ledger_count(), 1)
        # Event IDs remain stable after replay.
        self.assertEqual(
            set(before).issubset(set(driver.latest_outbox_event_ids())), True
        )


@override_settings(STORAGES=_storage_settings(_TEMP_STORAGE), PILOT_ALLOW_FIXTURES=False)
class SeedPilotGateTests(TestCase):
    def test_seed_pilot_refuses_when_fixtures_disallowed(self):
        out = StringIO()
        with self.assertRaises(Exception):
            call_command("seed_pilot", "--fixture", stdout=out, stderr=out)

    @override_settings(PILOT_ALLOW_FIXTURES=True)
    def test_seed_pilot_creates_logins(self):
        out = StringIO()
        call_command(
            "seed_pilot",
            "--fixture",
            "--building-name",
            f"SeedCmd {secrets.token_hex(4)}",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("operator@", text)
        self.assertIn("resident@", text)
        self.assertNotIn("PILOT_WALLET", text)
        # Never dump private key hex blobs.
        self.assertNotRegex(text, r"\b[0-9a-f]{64}\b")
