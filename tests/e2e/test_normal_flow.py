"""Cross-role normal flow (domain driver; browser optional)."""

from __future__ import annotations

import pytest

from lamto.testing.factories import DEFAULT_AMOUNT_VND

pytestmark = pytest.mark.django_db


def test_direct_outcome_c_happy_path(seeded_pilot):
    seeded_pilot.submit_report("Lift doors stick", "Building B / Lift 2")
    seeded_pilot.confirm_triage_case()
    seeded_pilot.start_assigned_work()
    seeded_pilot.publish_work_progress()
    seeded_pilot.complete_assigned_work()

    rating = seeded_pilot.rate_completed_case(satisfied=True)

    assert rating.satisfied is True


def test_realistic_normal_flow(page, seeded_pilot):
    seeded_pilot.submit_report(
        "Elevator shakes heavily",
        "Building B / Lift 2",
        "tests/fixtures/elevator.jpg",
    )

    seeded_pilot.confirm_triage_case()
    seeded_pilot.submit_signed_proposal(amount_vnd=DEFAULT_AMOUNT_VND)

    seeded_pilot.start_assigned_work()
    seeded_pilot.publish_work_progress()
    seeded_pilot.complete_assigned_work()
    seeded_pilot.record_settlement_transfer()
    seeded_pilot.record_settlement_ack()
    seeded_pilot.confirm_all_chain_events()
    seeded_pilot.rate_completed_case(satisfied=True)
    seeded_pilot.sign_publication_snapshot()
    seeded_pilot.confirm_all_chain_events()

    ledger = seeded_pilot.open_latest_ledger_entry()
    assert ledger.actual_cost_vnd == DEFAULT_AMOUNT_VND
    assert ledger.status == "Record verified"
    assert ledger.has_redacted_documents()

    verification = seeded_pilot.verify_latest_ledger_entry()
    assert verification.document_hashes_match
    assert verification.chain_events_match
    assert verification.recomputed_fund_balance_vnd == ledger.current_fund_balance_vnd
