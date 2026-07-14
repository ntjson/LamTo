"""Backend and level at settlement, derived from the terminal outbox status (spec 5.2).

Stored columns were rejected: finance_publicationsnapshot is DB append-only
(migration 0008), and weakening that trigger would amend a P1 gate.
"""

from django.test import SimpleTestCase
from django.utils import timezone

from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
from lamto.finance.models import PublicationSnapshot

Status = BlockchainOutboxEvent.Status


def _snapshot(status, confirmed_at=None):
    snapshot = PublicationSnapshot()
    snapshot.outbox_event = BlockchainOutboxEvent(
        status=status, confirmed_at=confirmed_at
    )
    return snapshot


class SettlementDerivationTests(SimpleTestCase):
    def test_local_settlement_records_disabled_backend(self):
        snapshot = _snapshot(Status.LOCAL)
        self.assertEqual(snapshot.anchoring_backend, "disabled")
        self.assertEqual(snapshot.settled_evidence_level, EvidenceLevel.LOCAL_SIGNED)

    def test_confirmed_settlement_records_besu_backend(self):
        snapshot = _snapshot(Status.CONFIRMED, confirmed_at=timezone.now())
        self.assertEqual(snapshot.anchoring_backend, "besu")
        self.assertEqual(snapshot.settled_evidence_level, EvidenceLevel.CHAIN_CONFIRMED)

    def test_post_settlement_mismatch_keeps_settlement_facts(self):
        # CONFIRMED -> MISMATCH re-check preserves confirmed_at; the level at
        # settlement stays CHAIN_CONFIRMED even though the current level is MISMATCH.
        snapshot = _snapshot(Status.MISMATCH, confirmed_at=timezone.now())
        self.assertEqual(snapshot.anchoring_backend, "besu")
        self.assertEqual(snapshot.settled_evidence_level, EvidenceLevel.CHAIN_CONFIRMED)
        self.assertEqual(
            snapshot.outbox_event.evidence_level, EvidenceLevel.MISMATCH
        )

    def test_unsettled_snapshot_has_no_settlement_facts(self):
        for status in (Status.PENDING, Status.SUBMITTED, Status.FAILED, Status.MISMATCH):
            snapshot = _snapshot(status)
            self.assertEqual(snapshot.anchoring_backend, "")
            self.assertEqual(snapshot.settled_evidence_level, "")
