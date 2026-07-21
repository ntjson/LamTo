"""Disabled anchoring: publication and fund flows settle LOCAL (spec 5.2/5.4).

The driver's chain is paused so it never fake-confirms; the REAL worker
(`process_due_outbox_events`) performs every settlement, constructing no chain
client. Nothing may present LOCAL_SIGNED as chain confirmation.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from lamto.config.worker import process_publication_finalization_batch
from lamto.documents.models import Document
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
from lamto.evidence.worker import process_due_outbox_events
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
    fund_balance,
    get_or_create_fund,
    record_fund_source,
    verify_fund_source,
)
from lamto.finance.integrity import verify_published_entry
from lamto.finance.models import (
    MaintenanceFundEntry,
    PublishedLedgerEntry,
    VerificationObservation,
)
from lamto.finance.selectors import published_ledger_entries
from lamto.testing.factories import PilotDomainDriver, new_event_id, seed_pilot_world

pytestmark = pytest.mark.django_db

Status = BlockchainOutboxEvent.Status


def _settle_locally():
    """Run the real worker; in disabled mode every due event settles LOCAL."""
    for event in process_due_outbox_events():
        assert event.status == Status.LOCAL, event.status


def test_disabled_mode_publication_and_fund_flows(page, temp_storage, settings):
    settings.EVIDENCE_ANCHORING_BACKEND = "disabled"
    seed = seed_pilot_world(
        building_name="Offchain Building", create_sample_report=False
    )
    driver = PilotDomainDriver(seed)
    # seed_opening_fund fake-confirms its two events (a legitimate mixed
    # history); everything queued after this line must settle LOCAL.
    preconfirmed = set(
        BlockchainOutboxEvent.objects.filter(status=Status.CONFIRMED).values_list(
            "pk", flat=True
        )
    )
    driver.pause_chain()

    # --- Publication flow -------------------------------------------------
    driver.prepare_local_normal_work(page)
    driver.complete_assigned_work()
    driver.accept_and_record_payment()
    driver.verify_payment()
    _settle_locally()

    snapshot = driver.sign_publication_snapshot()  # prerequisites are LOCAL-settled
    _settle_locally()
    batch = process_publication_finalization_batch()
    assert batch.ok, batch.detail

    entry = PublishedLedgerEntry.objects.get(case__building=seed.building)
    assert entry.snapshot_id == snapshot.pk
    snapshot.outbox_event.refresh_from_db()
    assert snapshot.outbox_event.status == Status.LOCAL
    assert snapshot.outbox_event.transaction_hash == ""
    assert snapshot.outbox_event.confirmed_at is None
    assert snapshot.anchoring_backend == "disabled"
    assert snapshot.settled_evidence_level == EvidenceLevel.LOCAL_SIGNED

    # Nothing queued in disabled mode ever became CONFIRMED, nothing is pending.
    flow_events = BlockchainOutboxEvent.objects.filter(building=seed.building)
    assert not flow_events.filter(status=Status.PENDING).exists()
    assert not (
        flow_events.filter(status=Status.CONFIRMED)
        .exclude(pk__in=preconfirmed)
        .exists()
    )

    # Resident visibility with the honest off-chain label.
    assert entry.pk in [row.pk for row in published_ledger_entries(seed.building.pk)]
    web = Client()
    web.force_login(seed.users["resident"])
    response = web.get(reverse("web:ledger-detail", kwargs={"pk": entry.pk}))
    body = response.content.decode()
    assert "anchoring is off for this deployment" in body
    assert "Blockchain anchored" not in body

    # Integrity observation: documents checked, chain skipped, never faked.
    observation = verify_published_entry(entry.pk)
    assert observation.result == VerificationObservation.Result.VERIFIED
    assert observation.details.get("anchoring_backend") == "disabled"
    assert {c["result"] for c in observation.details["chain_checks"]} == {
        "SKIPPED_ANCHORING_DISABLED"
    }

    balance_after_publication = fund_balance(seed.building.pk, verified_only=True)

    # --- Fund flow (maker-checker stays mandatory) ------------------------
    fund = get_or_create_fund(seed.building)
    recorder = seed.roles["fund_recorder"]
    verifier = seed.roles["fund_verifier"]
    original, redacted = seed.document_pair(
        Document.Kind.CONTRACT, recorder.user, "offchain-inflow"
    )
    entry_id = allocate_fund_entry_id()
    event_id = new_event_id()
    ts = timezone.now()
    typed = build_fund_source_evidence_typed_data(
        fund,
        recorder,
        entry_id,
        MaintenanceFundEntry.EntryType.INFLOW,
        5_000_000,
        original,
        redacted,
        event_id,
        timestamp=ts,
    )
    inflow = record_fund_source(
        fund,
        MaintenanceFundEntry.EntryType.INFLOW,
        5_000_000,
        original,
        redacted,
        recorder,
        seed.sign_typed(recorder, typed),
        event_id,
        fund_entry_id=entry_id,
        timestamp=ts,
    )
    verify_event = new_event_id()
    verify_typed = build_fund_verification_evidence_typed_data(
        inflow, verifier, verify_event, timestamp=inflow.recorded_at
    )
    verify_fund_source(
        inflow,
        verifier,
        seed.sign_typed(verifier, verify_typed),
        verify_event,
        timestamp=inflow.recorded_at,
    )
    # Unsettled source does not count yet; LOCAL settlement makes it count.
    assert fund_balance(seed.building.pk, verified_only=True) == balance_after_publication
    _settle_locally()
    assert (
        fund_balance(seed.building.pk, verified_only=True)
        == balance_after_publication + 5_000_000
    )
