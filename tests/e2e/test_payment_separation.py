"""Payment recording and verification require separate managers."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

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
    recorder = seeded_pilot.seed.management_memberships[0]
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

    entry = seeded_pilot.sign_publication_snapshot()
    assert entry is not None
    assert seeded_pilot.ledger_count() == 1
