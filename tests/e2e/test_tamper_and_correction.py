"""Tamper mismatch freezes publish; correction preserves original ledger entry."""

from __future__ import annotations

import pytest
from django.core.files.storage import storages
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.documents.models import Document
from lamto.evidence.canonical import payload_hash
from lamto.finance.corrections import (
    allocate_correction_id,
    allocate_correction_publication_id,
    build_correction_evidence_typed_data,
    create_correction,
    decide_correction,
    finalize_correction_publication,
    prepare_correction_publication,
    _correction_resident_payload,
)
from lamto.finance.fund import fund_balance
from lamto.finance.models import (
    CorrectionDecision,
    MaintenanceFundEntry,
    PublishedLedgerEntry,
)
from lamto.testing.factories import PilotDomainDriver, confirm_event, new_event_id, seed_pilot_world

pytestmark = pytest.mark.django_db

ZERO_BARE = "00" * 32


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


def test_correction_preserves_original_and_reconciles_fund(page, seeded_pilot, temp_storage):
    seed = seed_pilot_world(
        building_name="E2E Correction Building",
        create_sample_report=False,
    )
    driver = PilotDomainDriver(seed)
    driver.prepare_locally_approved_normal_work(page)
    driver.complete_assigned_work()
    driver.accept_and_record_payment()
    driver.verify_payment()
    driver.confirm_all_chain_events()
    driver.sign_publication_snapshot()
    driver.confirm_all_chain_events()

    entry = PublishedLedgerEntry.objects.get(case__building=seed.building)
    original_cost = entry.actual_cost_vnd
    balance_before = driver.fund_balance()
    new_amount = original_cost - 500_000

    operator = seed.roles["correction_operator"]
    board = seed.roles["correction_board"]
    rep = seed.roles["resident_representative"]
    publisher = seed.roles["eligible_publisher"]
    evidence_o, _ = driver.seed.document_pair(
        Document.Kind.CORRECTION_EVIDENCE, operator.user, "corr"
    )
    correction_id = allocate_correction_id()
    create_ts = timezone.now()
    event_id = new_event_id()
    replacement_hashes = [evidence_o.sha256]
    typed = build_correction_evidence_typed_data(
        correction_id=correction_id,
        original_event_id=entry.snapshot.outbox_event.event_id,
        original_hash=entry.snapshot.outbox_event.payload_hash,
        replacement_hashes=replacement_hashes,
        reason="Invoice arithmetic error",
        decision="APPROVE",
        actor_organization_id=operator.organization_id,
        publisher_snapshot_hash=ZERO_BARE,
        event_id=event_id,
        timestamp=create_ts,
        previous_hash="0x" + entry.snapshot.outbox_event.payload_hash,
    )
    sig = Account.sign_message(
        encode_typed_data(full_message=typed), seed.accounts[operator.pk].key
    ).signature.hex()
    correction = create_correction(
        entry,
        operator,
        "Invoice arithmetic error",
        {"actual_cost_vnd": new_amount, "contractor_name": entry.contractor_name},
        [evidence_o],
        sig,
        event_id,
        correction_id=correction_id,
        timestamp=create_ts,
    )
    confirm_event(correction.outbox_event)

    for actor, stage, prev in (
        (board, CorrectionDecision.Stage.BOARD, correction.outbox_event),
        (rep, CorrectionDecision.Stage.RESIDENT_REP, None),
    ):
        if stage == CorrectionDecision.Stage.RESIDENT_REP:
            prev_hash = "0x" + board_decision.outbox_event.payload_hash
        else:
            prev_hash = "0x" + prev.payload_hash
        ts = timezone.now()
        ev = new_event_id()
        t = build_correction_evidence_typed_data(
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="approve",
            decision="APPROVE",
            actor_organization_id=actor.organization_id,
            publisher_snapshot_hash=ZERO_BARE,
            event_id=ev,
            timestamp=ts,
            previous_hash=prev_hash,
        )
        s = Account.sign_message(
            encode_typed_data(full_message=t), seed.accounts[actor.pk].key
        ).signature.hex()
        decision = decide_correction(
            correction, actor, stage, "APPROVE", "approve", s, ev, timestamp=ts
        )
        confirm_event(decision.outbox_event)
        if stage == CorrectionDecision.Stage.BOARD:
            board_decision = decision
        else:
            rep_decision = decision

    snapshot_id = allocate_correction_publication_id()
    pub_ts = timezone.now()
    resident_payload_hash = payload_hash(_correction_resident_payload(correction))
    pub_event = new_event_id()
    pub_typed = build_correction_evidence_typed_data(
        correction_id=correction.pk,
        original_event_id=entry.snapshot.outbox_event.event_id,
        original_hash=entry.snapshot.outbox_event.payload_hash,
        replacement_hashes=replacement_hashes,
        reason=correction.reason,
        decision="APPROVE",
        actor_organization_id=publisher.organization_id,
        publisher_snapshot_hash=resident_payload_hash,
        event_id=pub_event,
        timestamp=pub_ts,
        previous_hash="0x" + rep_decision.outbox_event.payload_hash,
    )
    pub_sig = Account.sign_message(
        encode_typed_data(full_message=pub_typed), seed.accounts[publisher.pk].key
    ).signature.hex()
    snapshot = prepare_correction_publication(
        correction,
        publisher,
        pub_sig,
        pub_event,
        snapshot_id=snapshot_id,
        timestamp=pub_ts,
    )
    confirm_event(snapshot.outbox_event)
    finalize_correction_publication(snapshot.pk)

    entry.refresh_from_db()
    assert entry.actual_cost_vnd == original_cost
    reverse = MaintenanceFundEntry.objects.get(
        correction=correction, entry_type=MaintenanceFundEntry.EntryType.REVERSAL
    )
    replacement = MaintenanceFundEntry.objects.get(
        correction=correction, entry_type=MaintenanceFundEntry.EntryType.REPLACEMENT
    )
    assert reverse.amount_vnd == original_cost
    assert replacement.amount_vnd == -new_amount
    assert fund_balance(seed.building.pk, verified_only=True) == (
        balance_before + original_cost - new_amount
    )
