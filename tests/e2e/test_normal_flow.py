"""Cross-role normal flow (domain driver; browser optional)."""

from __future__ import annotations

import pytest

from lamto.testing.factories import DEFAULT_AMOUNT_VND

pytestmark = pytest.mark.django_db


def test_realistic_normal_flow(page, seeded_pilot):
    resident = seeded_pilot.login(page, "resident")
    resident.submit_report(
        "Elevator shakes heavily",
        "Building B / Lift 2",
        "tests/fixtures/elevator.jpg",
    )

    operator = seeded_pilot.login(page, "operator")
    operator.confirm_triage_and_create_paid_work_order()
    operator.submit_signed_proposal(amount_vnd=DEFAULT_AMOUNT_VND)

    seeded_pilot.login(page, "maintenance").complete_assigned_work()
    seeded_pilot.login(page, "board_payment_recorder").accept_and_record_payment()
    seeded_pilot.login(page, "board_payment_verifier").verify_payment()
    seeded_pilot.confirm_all_chain_events()
    seeded_pilot.login(page, "eligible_publisher").sign_publication_snapshot()
    seeded_pilot.confirm_all_chain_events()

    ledger = seeded_pilot.login(page, "resident").open_latest_ledger_entry()
    assert ledger.actual_cost_vnd == DEFAULT_AMOUNT_VND
    assert ledger.status == "Record verified"
    assert ledger.has_redacted_documents()

    verification = seeded_pilot.login(page, "auditor").verify_latest_ledger_entry()
    assert verification.document_hashes_match
    assert verification.chain_events_match
    assert verification.recomputed_fund_balance_vnd == ledger.current_fund_balance_vnd
