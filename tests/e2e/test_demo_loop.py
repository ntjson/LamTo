"""The self-run demo loop, end to end over the HTTP surface a visitor uses.

One test walks the whole loop: the resident API, the Management workspace and
the Evidence explorer. It starts from the demo seed command and files the
committed demo kit. Filesystem storage, a faked scanner, anchoring disabled and
the AI provider unset. The worker runs in-process through its normal cycle, so
nothing marks an event as confirmed except the worker.

It asserts only on what the visitor or a public reader can observe: status
codes, rendered text, response JSON and downloaded bytes. It doesn't use the
domain driver.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from PIL import Image

from lamto.config.worker import run_worker_cycle
from lamto.testing.factories import DEMO_PASSWORD

pytestmark = pytest.mark.django_db

KIT = Path(__file__).resolve().parents[2] / "ops" / "demo-kit" / "files"
QUOTATION = KIT / "bao-gia-sua-thang-may-mau.pdf"
TRANSFER_PROOF = KIT / "chung-tu-thanh-toan-mau.pdf"

QUOTED_VND = 560_000_000
CONTRACTOR = "Công ty TNHH Thang máy Mẫu"


def _photo_jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


def _worker_cycle():
    """One normal cycle of the unified worker; every processor must succeed."""
    result = run_worker_cycle()
    failed = [(p.name, p.detail) for p in result.processors if not p.ok]
    assert not failed, failed


def _hidden_value(html: str, name: str) -> str:
    match = re.search(rf'<input[^>]*name="{name}"[^>]*value="([^"]*)"', html) or re.search(
        rf'<input[^>]*value="([^"]*)"[^>]*name="{name}"', html
    )
    assert match, f"no hidden input {name!r} on the page"
    return match.group(1)


@pytest.fixture
def demo_loop(temp_storage, settings):
    settings.PILOT_ALLOW_FIXTURES = True
    settings.EVIDENCE_ANCHORING_BACKEND = "disabled"
    settings.AI_TRIAGE_URL = ""
    settings.AI_TRIAGE_TOKEN = ""
    settings.LANGUAGE_CODE = "en"
    with (
        patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True),
        patch("lamto.web.staff_documents.scan_with_clamav", lambda _f: True),
    ):
        yield


def test_demo_loop_from_report_to_verified_ledger_entry(demo_loop):
    # --- The demo seed command, as the operator runs it ---------------------
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    cue_card = out.getvalue()
    manager_email = re.search(r"Management \(email\):\s+(\S+)", cue_card).group(1)
    resident_phone = re.search(r"Resident \(phone\):\s+(\S+)", cue_card).group(1)

    # --- 1. The resident signs in with the synthetic phone number ----------
    resident = Client()
    login = resident.post(
        reverse("api:auth-login"),
        {"identifier": resident_phone, "password": DEMO_PASSWORD},
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    auth = {"authorization": f"Token {login.json()['token']}"}

    # --- 2. The resident files a report with a photo through the API -------
    locations = resident.get(reverse("api:locations"), headers=auth).json()
    floor_one = next(a for a in locations if a["name"] == "Tầng 1")
    lift = next(
        c
        for c in locations
        if c["parent_id"] == floor_one["id"] and c["name"] == "Thang máy A"
    )
    filed = resident.post(
        reverse("api:reports"),
        {
            "client_ref": str(uuid.uuid4()),
            "text": "Thang máy rung lắc mạnh khi chạy",
            "location_id": lift["id"],
        },
        content_type="application/json",
        headers=auth,
    )
    assert filed.status_code == 201, filed.content
    report_id = filed.json()["id"]
    photo = resident.post(
        reverse("api:report-photos", kwargs={"pk": report_id}),
        {"photo": SimpleUploadedFile("notice.jpg", _photo_jpeg(), content_type="image/jpeg")},
        headers=auth,
    )
    assert photo.status_code == 201, photo.content

    # --- 3. After a worker cycle the report is in the Action inbox ---------
    manager = Client()
    assert manager.post(
        reverse("login"), {"username": manager_email, "password": DEMO_PASSWORD}
    ).status_code == 302
    report_url = reverse("web:staff-report-detail", kwargs={"pk": report_id})
    assert report_url not in manager.get(reverse("web:action-inbox")).content.decode()
    _worker_cycle()
    inbox = manager.get(reverse("web:action-inbox"))
    assert inbox.status_code == 200
    assert report_url in inbox.content.decode()

    # --- 4. Manual triage: Elevator, a Management queue, a Case location ---
    triage = manager.post(
        report_url,
        {
            "action": "confirm_triage",
            "category": "ELEVATOR",
            "urgency": "HIGH",
            "location": lift["id"],
            "management_queue": "MAINTENANCE",
            "deadline_minutes": 1440,
        },
    )
    assert triage.status_code == 302, triage.content.decode()
    case_url = triage["Location"]
    case_id = int(re.search(r"/s/cases/(\d+)/", case_url).group(1))
    triaged_page = manager.get(case_url).content.decode()
    assert "Elevator" in triaged_page
    assert "Thang máy A" in triaged_page

    # --- 5. A proposal from the case with the kit quotation ----------------
    compare = manager.post(
        reverse("web:proposal-price-compare", kwargs={"pk": case_id}),
        json.dumps({"amount_vnd": QUOTED_VND}),
        content_type="application/json",
    )
    assert compare.status_code == 200, compare.content
    comparison = compare.json()
    assert comparison["source"] == "fallback"
    assert comparison["is_fallback"] is True
    assert comparison["direction"] == "above"
    assert comparison["percentage"] == pytest.approx(24, abs=1)

    proposed = manager.post(
        reverse("web:proposal-create", kwargs={"pk": case_id}),
        {
            "amount_vnd": str(QUOTED_VND),
            "price_prediction_id": str(comparison["id"]),
            "contractor_name": CONTRACTOR,
            "quotation": SimpleUploadedFile(
                QUOTATION.name, QUOTATION.read_bytes(), content_type="application/pdf"
            ),
            "confirm": "on",
        },
    )
    assert proposed.status_code == 302, proposed.content.decode()
    proposal_url = proposed["Location"]
    proposal_id = int(re.search(r"/s/proposals/(\d+)/", proposal_url).group(1))
    proposal_page = manager.get(proposal_url).content.decode()
    assert "24% above the reference price" in proposal_page
    assert "Dự đoán AI không khả dụng — dùng giá tham chiếu mẫu." in proposal_page

    # --- 6. "Start work" is refused before the Proceed decision ------------
    case_page = manager.get(case_url).content.decode()
    assert 'value="start_work"' not in case_page
    assert "needs a Proceed decision" in case_page
    refused = manager.post(case_url, {"action": "start_work"})
    assert refused.status_code == 200
    assert "needs a Proceed decision" in refused.content.decode()
    still_waiting = manager.get(case_url).content.decode()
    assert "needs a Proceed decision" in still_waiting
    assert 'value="publish_progress"' not in still_waiting

    # --- 7. The Proceed decision is made, and work starts ------------------
    _worker_cycle()  # the proposal's signed evidence event settles
    decided = manager.post(
        proposal_url, {"action": "decide", "decision": "proceed", "note": "Duyệt"}
    )
    assert decided.status_code == 302
    started_page = manager.get(case_url).content.decode()
    assert 'value="publish_progress"' in started_page
    assert 'value="complete_work"' in started_page
    assert "needs a Proceed decision" not in started_page

    # --- 8. Progress is reported and the work is completed -----------------
    progress = manager.post(
        case_url,
        {"action": "publish_progress", "cause": "Cáp tải mòn", "result": "Đã vào kiểm tra"},
    )
    assert progress.status_code == 302
    completed = manager.post(
        case_url,
        {"action": "complete_work", "cause": "Cáp tải mòn", "result": "Đã thay cáp tải"},
    )
    assert completed.status_code == 302

    # --- 9. The proposal is settled with the kit's Transfer proof ----------
    record_url = reverse("web:settlement-record", kwargs={"pk": proposal_id})
    settle_form = manager.get(record_url).content.decode()
    settled = manager.post(
        record_url,
        {
            "event_id": _hidden_value(settle_form, "event_id"),
            "proof_upload": SimpleUploadedFile(
                TRANSFER_PROOF.name,
                TRANSFER_PROOF.read_bytes(),
                content_type="application/pdf",
            ),
        },
    )
    assert settled.status_code == 302, settled.content.decode()
    settlement_url = settled["Location"]

    # --- 10. The Evidence explorer withholds the Transfer proof until a worker cycle
    # settles its event; after that it serves the proof, bytes re-verified. --
    explorer_url = re.search(
        r'href="(/e/[^/"]+/)"', manager.get(settlement_url).content.decode()
    ).group(1)
    proof_sha = hashlib.sha256(TRANSFER_PROOF.read_bytes()).hexdigest()
    proof_url = f"{explorer_url}doc/{proof_sha}/"
    public = Client()  # no login: anyone with the link
    before = public.get(explorer_url)
    assert before.status_code == 200
    assert proof_url not in before.content.decode()
    assert public.get(proof_url).status_code == 404

    _worker_cycle()
    after = public.get(explorer_url)
    assert proof_url in after.content.decode()
    download = public.get(proof_url)
    assert download.status_code == 200
    assert download.content == TRANSFER_PROOF.read_bytes()

    # --- 11. The proposal is published to the ledger, then the resident
    # ledger entry shows the Proceed decision and says
    # that no chain was consulted. -------------------------------------------
    published = manager.post(proposal_url, {"action": "publish", "confirm": "on"})
    assert published.status_code == 302, published.content.decode()
    _worker_cycle()  # the Integrity observation
    ledger = resident.get(reverse("api:ledger-list"), headers=auth).json()
    (listed,) = ledger["results"]
    entry = resident.get(
        reverse("api:ledger-detail", kwargs={"pk": listed["id"]}), headers=auth
    ).json()
    assert entry["proceed_decision"]["decided_by"] == "Ban quản lý Mẫu"
    assert entry["integrity_chain_consulted"] is False
    assert entry["actual_cost_vnd"] == QUOTED_VND
    assert entry["explorer_url"].endswith(explorer_url)

    # --- 12. The Evidence explorer, as a public reader sees it ----------------------
    page = public.get(explorer_url).content.decode()
    assert re.search(
        r"Người quyết định triển khai</dt>\s*<dd>Ban quản lý Mẫu", page
    )
    assert "Hệ thống LamTo tự kiểm tra" in page
    assert "Xác thực tính toàn vẹn độc lập" not in page
    assert "Công việc thực hiện</dt>\n      <dd>Đã thay cáp tải" in page
    assert "Chưa có cập nhật công việc" not in page
    # No person is named as verifier: the manager who paid appears only as the
    # one who settled, never inside the integrity panel.
    panel = page.split('aria-labelledby="observation-heading"')[1].split("</section>")[0]
    assert "Ban quản lý Mẫu" not in panel
