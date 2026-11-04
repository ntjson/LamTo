"""Integrity re-hashes what LamTo publishes, not only the stored hash.

An insider with database access can edit a published row and leave the
outbox's stored hash alone, or edit the stored payload and keep its hash. Both
must read as a mismatch, while the anchored hash on the chain stays unchanged.
"""

import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings

from lamto.evidence.canonical import payload_hash
from lamto.finance.integrity import verify_published_entry
from lamto.finance.models import VerificationObservation
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world


_STORAGE = tempfile.mkdtemp(prefix="lamto-integrity-recompute-")


def bypass_triggers(table, sql, params):
    """Run one UPDATE with the table's append-only triggers off, as a table owner could."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        cursor.execute(sql, params)
        cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


def chain_answers_with_anchored_hashes(anchored):
    """The chain keeps the hash anchored before any tamper."""
    return lambda event: SimpleNamespace(payload_hash="0x" + anchored[event.event_id])


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _STORAGE}},
    "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _STORAGE}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class IntegrityRecomputeTests(TestCase):
    def setUp(self):
        seed = seed_pilot_world(building_name=f"Recompute {self._testMethodName}", create_sample_report=False)
        self.driver = PilotDomainDriver(seed)
        self.driver.prepare_local_normal_work()
        self.driver.complete_assigned_work()
        self.settlement = self.driver.record_settlement()
        self.driver.confirm_all_chain_events()
        self.entry = self.driver.publish_settlement_entry()
        proposal = self.driver.seed.proposal
        proposal.refresh_from_db()
        self.version = proposal.current_version
        self.version_event = self.version.outbox_event
        self.settlement.refresh_from_db()
        self.anchored = {
            self.version_event.event_id: self.version_event.payload_hash,
            self.settlement.outbox_event.event_id: self.settlement.outbox_event.payload_hash,
        }

    def verify_against_chain(self):
        with patch("lamto.evidence.chain.EvidenceRegistryClient") as client:
            client.return_value.find.side_effect = chain_answers_with_anchored_hashes(self.anchored)
            observation = verify_published_entry(self.entry.pk)
        observation.refresh_from_db()
        return observation

    def local_check(self, observation, event):
        return next(
            check for check in observation.details["local_checks"]
            if check["event_id"] == event.event_id
        )

    def edit_published_amount(self):
        bypass_triggers(
            "finance_proposalversion",
            "UPDATE finance_proposalversion SET amount_vnd = amount_vnd + 90000000 WHERE id = %s",
            [self.version.pk],
        )

    @override_settings(EVIDENCE_ANCHORING_BACKEND="besu")
    def test_untampered_entry_rehashes_to_the_anchored_hash(self):
        observation = self.verify_against_chain()

        self.assertEqual(observation.result, VerificationObservation.Result.VERIFIED)
        check = self.local_check(observation, self.version_event)
        self.assertEqual(check["result"], "VERIFIED")
        self.assertEqual(check["published_rows_rehash"], self.anchored[self.version_event.event_id])

    @override_settings(EVIDENCE_ANCHORING_BACKEND="besu")
    def test_published_amount_edited_alone_is_a_mismatch_while_the_chain_is_unchanged(self):
        self.edit_published_amount()

        observation = self.verify_against_chain()

        self.assertEqual(observation.result, VerificationObservation.Result.MISMATCH)
        self.assertIs(observation.chain_consulted, True)
        check = self.local_check(observation, self.version_event)
        self.assertEqual(check["result"], "MISMATCH")
        self.assertNotEqual(check["published_rows_rehash"], self.anchored[self.version_event.event_id])
        # The stored hash still agrees with the chain: only the re-hash catches it.
        chain_check = next(
            c for c in observation.details["chain_checks"]
            if c["event_id"] == self.version_event.event_id
        )
        self.assertEqual(chain_check["result"], "VERIFIED")

    @override_settings(EVIDENCE_ANCHORING_BACKEND="disabled")
    def test_published_amount_edited_alone_is_a_mismatch_without_anchoring(self):
        self.edit_published_amount()

        observation = verify_published_entry(self.entry.pk)

        self.assertEqual(observation.result, VerificationObservation.Result.MISMATCH)
        self.assertIs(observation.chain_consulted, False)

    @override_settings(EVIDENCE_ANCHORING_BACKEND="besu")
    def test_stored_payload_edited_with_its_hash_kept_is_a_mismatch(self):
        bypass_triggers(
            "evidence_blockchainoutboxevent",
            "UPDATE evidence_blockchainoutboxevent "
            "SET payload = jsonb_set(payload, '{amount_vnd}', to_jsonb((payload->>'amount_vnd')::bigint + 90000000)) "
            "WHERE id = %s",
            [self.version_event.pk],
        )

        observation = self.verify_against_chain()

        self.assertEqual(observation.result, VerificationObservation.Result.MISMATCH)
        check = self.local_check(observation, self.version_event)
        self.assertNotEqual(check["stored_payload_rehash"], check["local_payload_hash"])

    @override_settings(EVIDENCE_ANCHORING_BACKEND="besu")
    def test_row_payload_and_stored_hash_all_rewritten_is_a_mismatch(self):
        self.edit_published_amount()
        self.version_event.refresh_from_db()
        payload = dict(self.version_event.payload, amount_vnd=self.version_event.payload["amount_vnd"] + 90000000)
        bypass_triggers(
            "evidence_blockchainoutboxevent",
            "UPDATE evidence_blockchainoutboxevent SET payload = %s::jsonb, payload_hash = %s WHERE id = %s",
            [json.dumps(payload), payload_hash(payload), self.version_event.pk],
        )

        observation = self.verify_against_chain()

        self.assertEqual(observation.result, VerificationObservation.Result.MISMATCH)
        chain_check = next(
            c for c in observation.details["chain_checks"]
            if c["event_id"] == self.version_event.event_id
        )
        self.assertEqual(chain_check["result"], "MISMATCH")
