"""Tamper mismatch freezes publication."""

from __future__ import annotations

import pytest
from django.core.files.storage import storages

pytestmark = pytest.mark.django_db

def test_tampered_document_blocks_publish(page, seeded_pilot):
    seeded_pilot.prepare_locally_approved_normal_work(page)
    seeded_pilot.complete_assigned_work()
    seeded_pilot.accept_and_record_payment()
    seeded_pilot.verify_payment()
    seeded_pilot.confirm_all_chain_events()

    payment = seeded_pilot._ctx["payment"]
    storage = storages["private"]
    with storage.open(payment.proof_original.storage_key, "wb") as handle:
        handle.write(b"tampered-for-e2e")

    blocked = seeded_pilot.attempt_publication()
    assert blocked.blocked
    assert "mismatch" in blocked.reason.lower()
