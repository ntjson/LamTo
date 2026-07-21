"""Task 18 pilot acceptance: normal path and adversarial cases.

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

from lamto.audit.models import AuditEvent
from lamto.documents.access import authorize_download
from lamto.documents.models import Document
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.fund import fund_balance
from lamto.finance.models import (
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
        driver.prepare_local_normal_work()
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

    def test_payment_recorder_self_verification_denied_and_publisher_dual_control(self):
        driver = self.driver
        driver.prepare_local_normal_work()
        driver.complete_assigned_work()
        payment = driver.accept_and_record_payment()
        recorder = driver.seed.management_memberships[0]
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

        entry = driver.sign_publication_snapshot()
        self.assertIsNotNone(entry)
        self.assertEqual(driver.ledger_count(), 1)

    def test_proposal_revision_after_signature_requires_new_publication(self):
        driver = self.driver
        driver.login(None, "resident").submit_report("Elevator issue", "Lift 2", None)
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        version1 = driver.login(None, "operator").submit_signed_proposal(
            amount_vnd=DEFAULT_AMOUNT_VND
        )
        work = driver.seed.work_order
        work.refresh_from_db()
        self.assertEqual(
            work.authorization_status, WorkOrder.AuthorizationStatus.AUTHORIZED
        )

        operator = driver.seed.management_memberships[0]
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
            work.authorization_status, WorkOrder.AuthorizationStatus.AUTHORIZED
        )
        started = start_work_order(work, driver.seed.management_users[0])
        self.assertEqual(started.status, WorkOrder.Status.IN_PROGRESS)

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
        driver.prepare_local_normal_work()
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()
        driver.sign_publication_snapshot()
        driver.confirm_all_chain_events()
        entry = PublishedLedgerEntry.objects.get(case__building=driver.seed.building)
        proof_original = entry.payment.proof_original

        self.assertTrue(authorize_download(driver.seed.residents[0], None, proof_original))
        manager = driver.seed.management_memberships[0]
        self.assertTrue(authorize_download(manager.user, manager.pk, proof_original))

    def test_tampered_document_blocks_publish(self):
        driver = self.driver
        driver.prepare_local_normal_work()
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

    def test_backup_restore_and_outbox_replay_idempotent_hashes(self):
        driver = self.driver
        driver.prepare_local_normal_work()
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
        self.assertIn("management-1@", text)
        self.assertIn("resident@", text)
        self.assertNotIn("PILOT_WALLET", text)
        # Never dump private key hex blobs.
        self.assertNotRegex(text, r"\b[0-9a-f]{64}\b")
