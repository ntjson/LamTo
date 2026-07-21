"""Payment self-verify denied; publisher dual-control exclusions."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from lamto.accounts.capabilities import LEDGER_PUBLISH, PAYMENT_VERIFY
from lamto.accounts.services import grant_capability
from lamto.finance.payments import (
    build_payment_verification_evidence_typed_data,
    verify_payment,
)
from lamto.testing.factories import new_event_id

pytestmark = pytest.mark.django_db


def test_payment_recorder_cannot_self_verify_and_forbidden_publishers_blocked(
    page, seeded_pilot
):
    seeded_pilot.prepare_local_normal_work(page)
    seeded_pilot.complete_assigned_work()
    payment = seeded_pilot.accept_and_record_payment()
    recorder = seeded_pilot.seed.roles["board_payment_recorder"]
    grant_capability(recorder, PAYMENT_VERIFY)
    event_id = new_event_id()
    typed = build_payment_verification_evidence_typed_data(
        payment, recorder, "VERIFIED", event_id, timestamp=payment.recorded_at
    )
    signature = seeded_pilot.seed.sign_typed(recorder, typed)
    with pytest.raises(PermissionDenied):
        verify_payment(
            payment,
            recorder,
            "VERIFIED",
            "Self verify",
            signature,
            event_id,
            timestamp=payment.recorded_at,
        )

    seeded_pilot.verify_payment()
    seeded_pilot.confirm_all_chain_events()

    for role_key in ("board_payment_recorder",):
        membership = seeded_pilot.seed.roles[role_key]
        grant_capability(membership, LEDGER_PUBLISH)
        original = seeded_pilot.seed.roles["eligible_publisher"]
        seeded_pilot.seed.roles["eligible_publisher"] = membership
        blocked = seeded_pilot.attempt_publication()
        seeded_pilot.seed.roles["eligible_publisher"] = original
        assert blocked.blocked, f"{role_key} must be denied publication"

    # Verifier-as-publisher is allowed when not creator/publisher/recorder.
    entry = seeded_pilot.sign_publication_snapshot()
    assert entry is not None
    assert seeded_pilot.ledger_count() == 1
