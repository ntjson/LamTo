"""Role / object / file access denials for prohibited paths."""

from __future__ import annotations

from unittest.mock import patch
from urllib.error import URLError

import pytest
from django.core.exceptions import PermissionDenied

from lamto.documents.access import authorize_download
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import PublishedLedgerEntry
from lamto.finance.proposals import build_proposal_evidence_payload, submit_proposal_version
from lamto.maintenance.ai import process_triage_job
from lamto.maintenance.models import TriageJob, WorkOrder
from lamto.maintenance.workorders import start_work_order
from lamto.testing.factories import DEFAULT_AMOUNT_VND, new_event_id

pytestmark = pytest.mark.django_db


def test_role_access_denies_prohibited_document_reads(page, seeded_pilot):
    seeded_pilot.prepare_locally_approved_normal_work(page)
    seeded_pilot.complete_assigned_work()
    seeded_pilot.accept_and_record_payment()
    seeded_pilot.verify_payment()
    seeded_pilot.confirm_all_chain_events()
    seeded_pilot.sign_publication_snapshot()
    seeded_pilot.confirm_all_chain_events()
    entry = PublishedLedgerEntry.objects.get(
        case__building=seeded_pilot.seed.building
    )
    proof_original = entry.payment.proof_original

    with pytest.raises(PermissionDenied):
        authorize_download(seeded_pilot.seed.users["resident"], None, proof_original)
    with pytest.raises(PermissionDenied):
        authorize_download(
            seeded_pilot.seed.users["operator"],
            seeded_pilot.seed.roles["operator"].pk,
            proof_original,
        )
    with pytest.raises(PermissionDenied):
        authorize_download(
            seeded_pilot.seed.users["maintenance"],
            seeded_pilot.seed.roles["maintenance"].pk,
            proof_original,
        )
    with pytest.raises(PermissionDenied):
        authorize_download(
            seeded_pilot.seed.users["tech_admin"],
            seeded_pilot.seed.roles["tech_admin"].pk,
            proof_original,
        )


def test_ai_outage_preserves_manual_triage_authority(page, seeded_pilot):
    report = seeded_pilot.login(page, "resident").submit_report(
        "AI offline elevator", "Lift 2", None
    )
    with patch("lamto.maintenance.ai.urlopen", side_effect=URLError("offline")):
        job = process_triage_job(report.triage_job.id)
    assert job.status == TriageJob.Status.NEEDS_MANUAL
    work = seeded_pilot.login(page, "operator").confirm_triage_and_create_paid_work_order()
    assert work.pk is not None


def test_proposal_change_after_signature_requires_reapproval(page, seeded_pilot):
    seeded_pilot.login(page, "resident").submit_report("Elevator", "Lift 2", None)
    seeded_pilot.login(page, "operator").confirm_triage_and_create_paid_work_order()
    version1 = seeded_pilot.login(page, "operator").submit_signed_proposal(
        amount_vnd=DEFAULT_AMOUNT_VND
    )
    seeded_pilot.login(page, "board_approver").approve_proposal()
    seeded_pilot.login(page, "resident_representative").coapprove_proposal()

    operator = seeded_pilot.seed.roles["operator"]
    proposal = seeded_pilot.seed.proposal
    quotation = seeded_pilot._ctx["quotation_original"]
    event_id = new_event_id()
    payload = build_proposal_evidence_payload(
        proposal, 19_000_000, "Changed", [quotation]
    )
    typed = build_evidence_typed_data(
        event_id,
        EvidenceType.PROPOSAL_CREATED,
        "0x" + payload_hash(payload),
        "0x" + version1.outbox_event.payload_hash,
    )
    signature = seeded_pilot.seed.sign_typed(operator, typed)
    version2 = submit_proposal_version(
        proposal, 19_000_000, "Changed", [quotation], signature, event_id
    )
    work = seeded_pilot.seed.work_order
    work.refresh_from_db()
    assert version2.number == 2
    assert work.authorization_status == WorkOrder.AuthorizationStatus.PENDING
    with pytest.raises(PermissionDenied):
        start_work_order(work, seeded_pilot.seed.users["maintenance"])
