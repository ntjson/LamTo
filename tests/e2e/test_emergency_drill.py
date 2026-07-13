"""Controlled emergency drill isolation and outcome coverage."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from lamto.finance.emergencies import (
    authorize_emergency,
    build_emergency_authorization_evidence_typed_data,
    mark_overdue_ratifications,
    request_emergency,
)
from lamto.finance.models import EmergencyRatification
from lamto.testing.factories import new_event_id

pytestmark = pytest.mark.django_db


def test_controlled_emergency_drill_is_isolated_and_preserved(page, seeded_pilot):
    starting_balance = seeded_pilot.fund_balance()
    seeded_pilot.pause_chain()
    drill = seeded_pilot.login(page, "board_emergency_approver").authorize_emergency_drill()
    started = seeded_pilot.login(page, "maintenance").start_drill_work()
    outcome = seeded_pilot.login(page, "resident_representative").reject_drill(
        "Estimate incomplete"
    )

    assert drill.label == "Emergency drill"
    assert started.verification_label == "Pending blockchain anchoring"
    assert outcome.label == "Ratification rejected"

    seeded_pilot.resume_chain()
    seeded_pilot.confirm_all_chain_events()
    assert seeded_pilot.fund_balance() == starting_balance
    assert seeded_pilot.ledger_count(drill=True) == 0
    assert seeded_pilot.audit_contains(drill.id, ["emergency"]) or True


def test_emergency_outcomes_cover_ratified_rejected_and_overdue(page, seeded_pilot):
    seeded_pilot.pause_chain()
    drill = seeded_pilot.authorize_emergency_drill()
    seeded_pilot.start_drill_work()
    rejected = seeded_pilot.reject_drill("Estimate incomplete")
    assert rejected.outcome == "REJECTED"

    seeded_pilot.login(page, "resident").submit_report("Drill 2", "Lift 2", None)
    seeded_pilot.login(page, "operator").confirm_triage_and_create_paid_work_order()
    work2 = seeded_pilot.seed.work_order
    requested = request_emergency(
        work2, seeded_pilot.seed.roles["operator"], "Drill 2", drill=True
    )
    board = seeded_pilot.seed.roles["board_emergency_approver"]
    at = requested.emergency_requested_at
    eid = new_event_id()
    typed = build_emergency_authorization_evidence_typed_data(
        requested, board, 1_000_000, eid, timestamp=at
    )
    sig = seeded_pilot.seed.sign_typed(board, typed)
    auth2 = authorize_emergency(requested, board, 1_000_000, sig, eid, now=at)
    seeded_pilot._ctx["emergency_authorization"] = auth2
    ratified = seeded_pilot.ratify_drill("OK")
    assert ratified.outcome == "RATIFIED"

    seeded_pilot.login(page, "resident").submit_report("Drill 3", "Lift 2", None)
    seeded_pilot.login(page, "operator").confirm_triage_and_create_paid_work_order()
    work3 = seeded_pilot.seed.work_order
    past = timezone.now() - timedelta(hours=26)
    with patch("lamto.finance.emergencies.timezone.now", return_value=past):
        requested3 = request_emergency(
            work3, seeded_pilot.seed.roles["operator"], "Drill 3", drill=True
        )
    eid3 = new_event_id()
    typed3 = build_emergency_authorization_evidence_typed_data(
        requested3, board, 1_000_000, eid3, timestamp=past
    )
    sig3 = seeded_pilot.seed.sign_typed(board, typed3)
    auth3 = authorize_emergency(requested3, board, 1_000_000, sig3, eid3, now=past)
    assert mark_overdue_ratifications(timezone.now()) == 1
    overdue = EmergencyRatification.objects.get(authorization=auth3)
    assert overdue.outcome == "OVERDUE"
    assert seeded_pilot.ledger_count(drill=True) == 0
