import tempfile

from django.test import TestCase, override_settings

from lamto.finance.integrity import verify_published_entry
from lamto.finance.publication import _collect_document_checks, _load_execution_chain
from lamto.finance.selectors import ledger_entry_proof
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world


_STORAGE = tempfile.mkdtemp(prefix="lamto-settlement-boundary-")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _STORAGE}},
    "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _STORAGE}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class SettlementBoundaryTests(TestCase):
    def flow(self):
        seed = seed_pilot_world(building_name=f"Boundary {self._testMethodName}", create_sample_report=False)
        driver = PilotDomainDriver(seed)
        driver.prepare_local_normal_work()
        driver.complete_assigned_work()
        driver.record_settlement_transfer()
        settlement = driver.record_settlement_ack()
        driver.confirm_all_chain_events()
        return driver, settlement

    def test_settlement_documents_feed_publication_checks(self):
        driver, settlement = self.flow()
        proposal = driver.seed.proposal
        proposal.refresh_from_db()
        self.assertEqual(_load_execution_chain(proposal), settlement)
        gates = {gate for _document, _digest, gate in _collect_document_checks(proposal, proposal.current_version, settlement)}
        self.assertTrue({"SETTLEMENT_TRANSFER_ORIGINAL", "SETTLEMENT_TRANSFER_REDACTED", "SETTLEMENT_ACK_ORIGINAL", "SETTLEMENT_ACK_REDACTED"}.issubset(gates))

    def test_publication_finalizes_and_integrity_traverses_settlement_chain(self):
        driver, settlement = self.flow()
        entry = driver.sign_publication_snapshot()
        observation = verify_published_entry(entry.pk)
        checked = set(observation.checked_chain_event_ids)
        self.assertIn(driver.seed.proposal.current_version.outbox_event.event_id, checked)
        self.assertIn(settlement.outbox_event.event_id, checked)

    def test_settlement_publishes_story_and_both_anchor_proofs(self):
        driver, settlement = self.flow()
        entry = settlement.ledger_entry
        proof = ledger_entry_proof(entry)
        self.assertEqual(entry.resident_payload["actual_cost_vnd"], settlement.amount_vnd)
        for key, event in (("proposal_version", entry.proposal.current_version.outbox_event), ("settlement", settlement.outbox_event)):
            self.assertEqual(proof[key]["event_id"], event.event_id)
            self.assertEqual(proof[key]["payload_hash"], event.payload_hash)
            self.assertTrue(proof[key]["evidence_level"])

    def test_pilot_settlement_flow_publishes_one_balanced_entry(self):
        driver, _settlement = self.flow()
        driver.sign_publication_snapshot()
        self.assertEqual(driver.ledger_count(), 1)
        self.assertEqual(driver.fund_balance(), 100_000_000 - driver._ctx["amount_vnd"])
