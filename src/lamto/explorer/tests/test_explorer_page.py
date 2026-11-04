import hashlib
import re
import secrets
import tempfile

from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from lamto.accounts.models import Building, ManagementMembership, User
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.chain import ChainRecord
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import Proposal, VerificationObservation
from lamto.finance.proposals import (
    create_standalone_proposal,
    decide_proposal,
    publish_proposal_version,
)
from lamto.finance.publication import publish_settlement_entry
from lamto.finance.settlements import record_settlement
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world


@override_settings(
    STORAGES={
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tempfile.gettempdir() + "/lamto-explorer-page-tests"},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class EvidenceExplorerPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Tòa nhà Sen Vàng")
        cls.manager = User.objects.create_user(
            email="manager@sen-vang.vn",
            password="pw",
            display_name="Nguyễn Văn Quản Lý",
        )
        cls.membership = ManagementMembership.objects.create(
            user=cls.manager, building=cls.building
        )

    def stored_version(self, kind, tag, payload):
        storage = storages["private"]
        key = f"{tag}-{secrets.token_hex(8)}"
        storage.save(key, ContentFile(payload))
        return DocumentVersion.objects.create(
            document=Document.objects.create(building=self.building, kind=kind),
            version=1,
            storage_key=key,
            provider_version_id=key,
            filename=f"{tag}.pdf",
            content_type="application/pdf",
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            uploader=self.manager,
        )

    def published_proposal(self, **kwargs):
        quotation = self.stored_version(
            Document.Kind.QUOTATION, "bao-gia", b"%PDF-1.7 quotation"
        )
        proposal = create_standalone_proposal(self.building, self.membership)
        publish_proposal_version(
            proposal,
            self.membership,
            amount_vnd=kwargs.get("amount_vnd", 50_000_000),
            contractor_name=kwargs.get("contractor_name", "Công ty Thang máy Việt Nam"),
            purpose=kwargs.get("purpose", "Bảo trì định kỳ hệ thống thang máy"),
            proposed_action=kwargs.get("proposed_action", "Thay thế cáp tải và kiểm định an toàn"),
            expected_schedule=kwargs.get("expected_schedule", "Tháng 8/2026"),
            quotation_versions=[quotation],
            event_id="0x" + secrets.token_hex(32),
        )
        proposal.refresh_from_db()
        return proposal

    def settled_proposal(self, settle_event=True, **kwargs):
        proposal = self.published_proposal(**kwargs)
        proof = self.stored_version(
            Document.Kind.PAYMENT_PROOF,
            "uy-nhiem-chi",
            b"%PDF-1.7 transfer-proof",
        )
        Proposal.objects.filter(pk=proposal.pk).update(
            status=Proposal.Status.COMPLETED, completed_at=timezone.now()
        )
        proposal.refresh_from_db()
        settlement = record_settlement(
            proposal,
            self.membership,
            transfer=proof,
            event_id="0x" + secrets.token_hex(32),
        )
        if settle_event:
            BlockchainOutboxEvent.objects.filter(pk=settlement.outbox_event_id).update(
                status=BlockchainOutboxEvent.Status.LOCAL
            )
        return proposal, proof

    def explorer_url(self, token):
        return reverse("explorer:detail", kwargs={"public_token": token})

    def test_unknown_token_returns_not_found(self):
        response = self.client.get(self.explorer_url("not-a-real-token"))
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_get_with_valid_token_returns_ok(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)

    def test_subtitle_names_building_and_proposal_and_excludes_public_token(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # The token addresses the page and its documents, so it lives in hrefs;
        # what it must never be is content the reader is shown.
        visible = re.sub(r'href="[^"]*"', "", content)
        self.assertNotIn(proposal.public_token, visible)
        self.assertNotIn("Mã truy cập công khai", content)
        self.assertIn("Tòa nhà Sen Vàng", content)
        self.assertIn(f"Đề xuất #{proposal.pk}", content)
        self.assertIn(f"Tòa nhà Sen Vàng · Đề xuất #{proposal.pk}", content)

    def test_subtitle_includes_publication_date_when_published_to_ledger(self):
        proposal, _ = self.settled_proposal()
        entry = publish_settlement_entry(proposal.settlement)
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        expected_date = timezone.localtime(entry.published_at).strftime("%d/%m/%Y")
        self.assertIn(
            f"Tòa nhà Sen Vàng · Đề xuất #{proposal.pk} · {expected_date}",
            content,
        )

    def test_proposal_summary_renders_parity_fields(self):
        proposal = self.published_proposal(
            amount_vnd=50_000_000,
            contractor_name="Công ty Thang máy Việt Nam",
            purpose="Bảo trì định kỳ hệ thống thang máy",
            proposed_action="Thay thế cáp tải và kiểm định an toàn",
        )
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Tòa nhà Sen Vàng", content)
        self.assertIn("Công ty Thang máy Việt Nam", content)
        self.assertIn("50.000.000", content)
        self.assertIn("Bảo trì định kỳ hệ thống thang máy", content)
        self.assertIn("Thay thế cáp tải và kiểm định an toàn", content)

    def test_proceed_decider_named_when_proceeding(self):
        proposal = self.published_proposal()
        decide_proposal(proposal, self.manager, proceed=True, note="Triển khai")
        proposal.refresh_from_db()

        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Người quyết định triển khai", content)
        self.assertIn("Nguyễn Văn Quản Lý", content)
        self.assertNotIn("phê duyệt", content.lower())

    def test_decider_line_absent_without_proceed_decision(self):
        proposal = self.published_proposal()

        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("Người quyết định triển khai", content)
        self.assertNotIn("phê duyệt", content.lower())
        # No fallback naming the management board in the decider's place.
        self.assertNotIn("<dd>Ban quản lý</dd>", content)

    def test_decider_line_absent_after_decision_not_to_proceed(self):
        proposal = self.published_proposal()
        decide_proposal(proposal, self.manager, proceed=False, note="Không làm")
        proposal.refresh_from_db()

        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("Người quyết định triển khai", content)

    def test_timeline_lists_multiple_published_versions_in_order(self):
        proposal = self.published_proposal(
            purpose="Phiên bản đầu tiên",
            amount_vnd=30_000_000,
        )
        quote2 = self.stored_version(
            Document.Kind.QUOTATION, "quote-v2", b"%PDF-1.7 quotation v2"
        )
        # Note: to publish a new version after v1, proposal must be in DRAFT/PUBLISHED state
        publish_proposal_version(
            proposal,
            self.membership,
            amount_vnd=45_000_000,
            contractor_name="Công ty Thang máy Miền Nam",
            purpose="Phiên bản điều chỉnh kinh phí",
            proposed_action="Thay thế thêm cáp phụ",
            expected_schedule="Tháng 9/2026",
            quotation_versions=[quote2],
            event_id="0x" + secrets.token_hex(32),
        )

        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        v1_idx = content.find("Phiên bản đề xuất #1")
        v2_idx = content.find("Phiên bản đề xuất #2")
        self.assertNotEqual(v1_idx, -1)
        self.assertNotEqual(v2_idx, -1)
        self.assertLess(v1_idx, v2_idx)
        self.assertIn("Phiên bản đầu tiên", content)
        self.assertIn("Phiên bản điều chỉnh kinh phí", content)

    def test_quotation_documents_are_linked_for_download(self):
        proposal = self.published_proposal()
        quotation = proposal.current_version.quotations.get()

        response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Tài liệu báo giá:", content)
        self.assertIn(quotation.filename, content)
        expected_doc_url = reverse(
            "explorer:document-download",
            kwargs={"public_token": proposal.public_token, "sha256": quotation.sha256},
        )
        self.assertIn(f'href="{expected_doc_url}"', content)

    def test_unsettled_proposal_shows_pending_settlement_step(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Nghiệm thu và thanh toán", content)
        self.assertIn("Đang chờ neo blockchain", content)
        self.assertIn("chưa thực hiện thanh toán", content)
        self.assertIn("ủy nhiệm chi", content)

    def test_settled_proposal_shows_settlement_step_and_document_link(self):
        proposal, proof = self.settled_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Nghiệm thu và thanh toán", content)
        self.assertIn("Chứng từ thanh toán:", content)
        self.assertNotIn("Chứng từ chuyển khoản", content)
        self.assertIn(proof.filename, content)
        expected_doc_url = reverse(
            "explorer:document-download",
            kwargs={"public_token": proposal.public_token, "sha256": proof.sha256},
        )
        self.assertIn(expected_doc_url, content)

    def test_transfer_proof_withheld_until_the_settlement_event_settles(self):
        proposal, proof = self.settled_proposal(settle_event=False)

        response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn(proof.sha256, content)
        self.assertNotIn(proof.filename, content)
        self.assertNotIn("Chứng từ thanh toán:", content)
        self.assertIn("Chứng từ thanh toán sẽ được công khai", content)

    def test_transfer_proof_listed_once_the_settlement_event_settles(self):
        proposal, proof = self.settled_proposal(settle_event=False)
        BlockchainOutboxEvent.objects.filter(
            pk=proposal.settlement.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.CONFIRMED)

        response = self.client.get(self.explorer_url(proposal.public_token))

        content = response.content.decode("utf-8")
        self.assertIn("Chứng từ thanh toán:", content)
        self.assertIn(proof.sha256, content)
        self.assertNotIn("Chứng từ thanh toán sẽ được công khai", content)

    def test_live_chain_confirmed_renders_with_chain_timestamp_and_verified_badge(self):
        proposal = self.published_proposal()
        event = proposal.current_version.outbox_event
        fake_time = 1770000000

        def fake_find(ev):
            return ChainRecord(
                payload_hash="0x" + ev.payload_hash,
                previous_hash="0x" + "00" * 32,
                event_type=int(ev.event_type),
                signer=ev.signer_address,
                recorded_at=fake_time,
            )

        with patch("lamto.evidence.chain.EvidenceRegistryClient") as client_cls:
            client_cls.return_value.find.side_effect = fake_find
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Đã neo trên blockchain", content)
        self.assertIn("status-verified", content)
        self.assertIn(event.payload_hash, content)

    def test_live_chain_mismatch_renders_with_mismatch_badge_and_never_verified_or_pending(self):
        proposal, _ = self.settled_proposal()

        def fake_find(ev):
            return ChainRecord(
                payload_hash="0x" + "deadbeef" * 8,
                previous_hash="0x" + "00" * 32,
                event_type=int(ev.event_type),
                signer=ev.signer_address,
                recorded_at=1770000000,
            )

        with patch("lamto.evidence.chain.EvidenceRegistryClient") as client_cls:
            client_cls.return_value.find.side_effect = fake_find
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Phát hiện sai lệch dữ liệu", content)
        self.assertIn("status-mismatch", content)
        # MISMATCH must never dress as verified or pending on mismatched steps
        self.assertNotIn("status-verified", content)
        self.assertNotIn("Đang chờ neo blockchain", content)

    def test_published_amount_edited_alone_renders_mismatch_though_chain_agrees_with_stored_hash(self):
        proposal = self.published_proposal()
        version = proposal.current_version
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE finance_proposalversion DISABLE TRIGGER USER")
            cursor.execute(
                "UPDATE finance_proposalversion SET amount_vnd = 65000000 WHERE id = %s",
                [version.pk],
            )
            cursor.execute("ALTER TABLE finance_proposalversion ENABLE TRIGGER USER")

        def fake_find(ev):
            return ChainRecord(
                payload_hash="0x" + ev.payload_hash,
                previous_hash="0x" + "00" * 32,
                event_type=int(ev.event_type),
                signer=ev.signer_address,
                recorded_at=1770000000,
            )

        with patch("lamto.evidence.chain.EvidenceRegistryClient") as client_cls:
            client_cls.return_value.find.side_effect = fake_find
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Phát hiện sai lệch dữ liệu", content)
        self.assertIn("status-mismatch", content)
        self.assertNotIn("Đã neo trên blockchain", content)

    def test_locally_signed_evidence_renders_with_local_signed_badge_and_info_tone(self):
        proposal = self.published_proposal()
        BlockchainOutboxEvent.objects.filter(
            pk=proposal.current_version.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.LOCAL)

        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Đã ký — chưa bật neo blockchain", content)
        self.assertIn("status-info", content)

    def test_integrity_observation_honestly_absent_when_none_exists(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("evidence-observation-panel", content)

    def observed_proposal(self, *, chain_consulted):
        proposal, proof = self.settled_proposal()
        entry = publish_settlement_entry(proposal.settlement)
        VerificationObservation.objects.create(
            published_entry=entry,
            result=VerificationObservation.Result.VERIFIED,
            checked_document_hashes=[proof.sha256],
            checked_chain_event_ids=[proposal.current_version.outbox_event.event_id],
            chain_consulted=chain_consulted,
            observed_at=timezone.now(),
        )
        return proposal

    def integrity_panel(self, proposal):
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        match = re.search(
            r'<section class="panel evidence-observation-panel".*?</section>',
            content,
            re.S,
        )
        self.assertIsNotNone(match, "integrity panel missing")
        return match.group(0)

    def test_integrity_panel_reads_as_self_check_when_chain_not_consulted(self):
        proposal = self.observed_proposal(chain_consulted=False)

        panel = self.integrity_panel(proposal)

        self.assertIn("Hệ thống LamTo tự kiểm tra", panel)
        self.assertIn("Các tài liệu đã công bố", panel)
        self.assertIn("Bản ghi đã xác minh", panel)
        self.assertIn("status-verified", panel)
        self.assertNotIn("độc lập", panel.lower())
        self.assertNotIn("Người xác minh", panel)
        self.assertNotIn(self.manager.display_name, panel)

    def test_integrity_panel_reads_as_independent_only_when_chain_consulted(self):
        proposal = self.observed_proposal(chain_consulted=True)

        panel = self.integrity_panel(proposal)

        self.assertIn("Xác thực tính toàn vẹn độc lập", panel)
        self.assertIn("blockchain", panel)
        self.assertNotIn("Hệ thống LamTo tự kiểm tra", panel)
        self.assertNotIn("Người xác minh", panel)
        self.assertNotIn(self.manager.display_name, panel)

    def test_integrity_panel_never_names_a_verifier_from_observation_details(self):
        proposal, proof = self.settled_proposal()
        entry = publish_settlement_entry(proposal.settlement)
        VerificationObservation.objects.create(
            published_entry=entry,
            result=VerificationObservation.Result.VERIFIED,
            details={"verifier": "Đoàn Kiểm Toán ABC"},
            checked_document_hashes=[proof.sha256],
            observed_at=timezone.now(),
        )

        panel = self.integrity_panel(proposal)

        self.assertNotIn("Đoàn Kiểm Toán ABC", panel)
        self.assertIn("Hệ thống LamTo tự kiểm tra", panel)

    def test_chain_unreachable_renders_stored_state_with_honest_unavailability_note(self):
        proposal = self.published_proposal()
        event = proposal.current_version.outbox_event

        with patch("lamto.evidence.chain.EvidenceRegistryClient") as client_cls:
            client_cls.return_value.find.side_effect = Exception("RPC connection failed")
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Không thể kết nối với blockchain. Đang hiển thị trạng thái đã lưu.", content)
        self.assertIn(event.payload_hash, content)

    def test_no_public_action_triggers_document_reverification(self):
        proposal, _ = self.settled_proposal()
        entry = publish_settlement_entry(proposal.settlement)

        with patch("lamto.finance.integrity.verify_published_entry") as mock_verify:
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        mock_verify.assert_not_called()

    def test_page_is_vietnamese_only_and_plain_language_above_technical_detail(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="vi"', content)
        self.assertIn("Hồ sơ minh bạch chi tiêu", content)
        self.assertIn("Chuỗi bằng chứng trách nhiệm", content)
        self.assertIn("Bằng chứng kỹ thuật", content)
        self.assertIn("details class=\"technical-proof\"", content)

    def test_transaction_hash_renders_as_link_when_chain_explorer_url_configured(self):
        proposal = self.published_proposal()
        tx_hash = "0x" + "aa" * 32
        BlockchainOutboxEvent.objects.filter(
            pk=proposal.current_version.outbox_event_id
        ).update(transaction_hash=tx_hash)

        with override_settings(CHAIN_EXPLORER_URL="https://explorer.sen-vang.vn/"):
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        expected_url = f"https://explorer.sen-vang.vn/tx/{tx_hash}"
        self.assertIn(f'href="{expected_url}"', content)
        self.assertIn(tx_hash, content)

    def test_transaction_hash_renders_as_plain_text_without_chain_explorer_url(self):
        proposal = self.published_proposal()
        tx_hash = "0x" + "bb" * 32
        BlockchainOutboxEvent.objects.filter(
            pk=proposal.current_version.outbox_event_id
        ).update(transaction_hash=tx_hash)

        with override_settings(CHAIN_EXPLORER_URL=""):
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(tx_hash, content)
        self.assertNotIn(f"/tx/{tx_hash}", content)
        self.assertNotIn('<a href=""', content)

    def test_step_without_transaction_hash_renders_no_broken_link(self):
        proposal = self.published_proposal()
        BlockchainOutboxEvent.objects.filter(
            pk=proposal.current_version.outbox_event_id
        ).update(transaction_hash="")

        with override_settings(CHAIN_EXPLORER_URL="https://explorer.sen-vang.vn"):
            response = self.client.get(self.explorer_url(proposal.public_token))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("https://explorer.sen-vang.vn", content)

    def test_explorer_extends_public_shell_with_branded_header_and_body_class(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn('<header class="site-header" role="banner">', content)
        self.assertIn('class="brand-mark"', content)
        self.assertIn('class="brand-name"', content)
        self.assertIn('Làm Tổ', content)
        self.assertIn('<body class="public">', content)
        self.assertIn('<main id="main" class="site-main" role="main">', content)

    def test_explorer_has_no_inline_style_blocks_or_inline_style_attributes(self):
        proposal, proof = self.settled_proposal()
        entry = publish_settlement_entry(proposal.settlement)
        VerificationObservation.objects.create(
            published_entry=entry,
            result=VerificationObservation.Result.VERIFIED,
            checked_document_hashes=[proof.sha256],
            checked_chain_event_ids=[proposal.current_version.outbox_event.event_id],
            observed_at=timezone.now(),
        )

        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertNotIn("<style>", content)
        self.assertNotIn("style=", content)

    def test_explorer_title_is_wrapped_in_panel(self):
        proposal = self.published_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # The title sits inside a panel section
        self.assertIn('<section class="panel', content)
        self.assertRegex(content, r'<section class="panel[^"]*">\s*<h1>Hồ sơ minh bạch chi tiêu</h1>')

    def test_explorer_uses_evidence_prefixed_classes_for_timeline_and_documents(self):
        proposal, proof = self.settled_proposal()
        response = self.client.get(self.explorer_url(proposal.public_token))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn('class="evidence-timeline"', content)
        self.assertIn('class="evidence-timeline-step"', content)
        self.assertIn('class="evidence-timeline-step-header"', content)
        self.assertIn('class="evidence-timeline-step-title"', content)
        self.assertIn('class="evidence-doc-link"', content)
        self.assertIn('class="evidence-doc-list"', content)




_WORK_DONE_STORAGE = tempfile.mkdtemp(prefix="lamto-explorer-work-done-")


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _WORK_DONE_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _WORK_DONE_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class ExplorerWorkDoneTests(TestCase):
    """The explorer never publishes the resident's report in place of work."""

    REPORT_TEXT = "Thang máy rung lắc mạnh, cư dân tầng 9 báo"
    NO_UPDATE = "Chưa có cập nhật công việc"

    def setUp(self):
        self.seed = seed_pilot_world(
            building_name="Explorer Work Done",
            email_prefix="expwd",
            create_sample_report=False,
        )
        self.driver = PilotDomainDriver(self.seed)
        self.driver.submit_report(self.REPORT_TEXT, "Lift 2")
        self.driver.confirm_triage_case()
        self.driver.publish_proposal()

    def page(self):
        proposal = self.seed.proposal
        proposal.refresh_from_db()
        response = self.client.get(
            reverse("explorer:detail", kwargs={"public_token": proposal.public_token})
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def work_done(self, content):
        match = re.search(
            r"<dt>Công việc thực hiện</dt>\s*<dd>(.*?)</dd>", content, re.S
        )
        self.assertIsNotNone(match, "work done field missing")
        return match.group(1).strip()

    def test_work_done_is_the_placeholder_before_the_first_work_update(self):
        content = self.page()

        self.assertEqual(self.work_done(content), self.NO_UPDATE)
        self.assertNotIn(self.REPORT_TEXT, content)

    def test_why_keeps_its_fallbacks_before_any_work_update(self):
        content = self.page()

        match = re.search(
            r"<dt>Báo cáo &amp; nhu cầu</dt>\s*<dd>(.*?)</dd>", content, re.S
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            match.group(1).strip(), self.seed.case.category
        )

    def test_work_done_is_the_work_updates_result_after_it_exists(self):
        self.driver.decide_proposal(proceed=True)
        self.driver.start_assigned_work()
        self.driver.publish_work_progress()

        content = self.page()

        self.assertEqual(self.work_done(content), "Cable secured")
        self.assertNotIn(self.REPORT_TEXT, content)
        why = re.search(r"<dt>Báo cáo &amp; nhu cầu</dt>\s*<dd>(.*?)</dd>", content, re.S)
        self.assertEqual(why.group(1).strip(), "Worn cable")

    def test_report_text_appears_nowhere_once_the_spend_is_published(self):
        self.driver.complete_assigned_work()
        self.driver.record_settlement()
        self.driver.confirm_all_chain_events()
        self.driver.publish_settlement_entry()
        self.driver.confirm_all_chain_events()

        content = self.page()

        self.assertEqual(self.work_done(content), "Cable secured")
        self.assertNotIn(self.REPORT_TEXT, content)
