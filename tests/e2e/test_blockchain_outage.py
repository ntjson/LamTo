"""Chain paused: work may start pending anchor; publication blocked until confirm."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_normal_work_can_start_pending_anchor_but_cannot_publish(page, seeded_pilot):
    seeded_pilot.pause_chain()
    seeded_pilot.prepare_local_normal_work(page)
    work = seeded_pilot.start_assigned_work()

    assert work.verification_label == "Pending blockchain anchoring"
    seeded_pilot.complete_assigned_work()
    seeded_pilot.record_settlement_transfer()
    seeded_pilot.record_settlement_ack()
    before_ids = seeded_pilot.latest_outbox_event_ids()
    blocked = seeded_pilot.attempt_publication()

    assert blocked.reason == "Required blockchain evidence is still pending"
    assert seeded_pilot.ledger_count() == 0

    seeded_pilot.resume_chain()
    seeded_pilot.confirm_all_chain_events()
    assert seeded_pilot.latest_outbox_event_ids() == before_ids
    seeded_pilot.sign_publication_snapshot()
    assert seeded_pilot.ledger_count() == 1
    seeded_pilot.confirm_all_chain_events()
    assert seeded_pilot.ledger_count() == 1
