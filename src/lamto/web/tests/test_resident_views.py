import secrets
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.storage import storages
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    ResidentOccupancy,
    SignerWallet,
    Unit,
)
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    utc_rfc3339,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import (
    AcceptanceRecord,
    FundEntryVerification,
    MaintenanceFund,
    MaintenanceFundEntry,
    PaymentEvidence,
    PaymentVerification,
    Proposal,
    ProposalVersion,
    PublicationSnapshot,
    PublishedLedgerEntry,
    VerificationObservation,
)
from lamto.maintenance.models import (
    BuildingLocation,
    CaseReport,
    CompletionRating,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    TriageJob,
    WorkOrder,
)


_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-web-")


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class ResidentViewTests(TestCase):
    def _unique(self, base):
        n = getattr(self, "_fixture_seq", 0) + 1
        self._fixture_seq = n
        return f"{base}-{n}"

    def make_signer(self, building, role, suffix):
        suffix = self._unique(suffix)
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        organization = Organization.objects.create(
            building=building,
            name=suffix,
            kind=OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role],
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        register_wallet(membership, account.address, proof)
        if not hasattr(self, "accounts"):
            self.accounts = {}
        self.accounts[membership.pk] = account
        return membership, account

    def queue_event(self, membership, *, confirm=True):
        """Queue a valid FUND_ENTRY outbox row for fixture FKs."""
        event_id = "0x" + secrets.token_hex(32)
        payload = {
            "fund_entry_id": secrets.randbelow(10**8) + 1,
            "entry_type": "INFLOW",
            "amount_vnd": 1,
            "source_document_original_hash": secrets.token_hex(32),
            "source_document_redacted_hash": secrets.token_hex(32),
            "maker_membership_id": membership.pk,
            "entry_timestamp": utc_rfc3339(timezone.now()),
        }
        previous = "0x" + "00" * 32
        typed = build_evidence_typed_data(
            event_id,
            EvidenceType.FUND_ENTRY,
            "0x" + payload_hash(payload),
            previous,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[membership.pk].key
        ).signature.hex()
        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.FUND_ENTRY,
                payload,
                previous,
                membership,
                signature,
            )
        if confirm:
            event.status = BlockchainOutboxEvent.Status.CONFIRMED
            event.confirmed_at = timezone.now()
            event.save(update_fields=["status", "confirmed_at"])
        return event

    def document_pair(self, building, uploader, prefix):
        tag = self._unique(prefix)
        document = Document.objects.create(building=building, kind=Document.Kind.INVOICE)
        original_bytes = f"{tag}-original".encode()
        redacted_bytes = f"{tag}-redacted".encode()
        storage = storages["private"]
        original_key = f"web/{tag}-original"
        redacted_key = f"web/{tag}-redacted"
        Path(storage.path(original_key)).parent.mkdir(parents=True, exist_ok=True)
        with storage.open(original_key, "wb") as handle:
            handle.write(original_bytes)
        with storage.open(redacted_key, "wb") as handle:
            handle.write(redacted_bytes)
        original = DocumentVersion.objects.create(
            document=document,
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key=original_key,
            provider_version_id=original_key,
            filename=f"{tag}-original.pdf",
            content_type="application/pdf",
            byte_size=len(original_bytes),
            sha256=secrets.token_hex(32),
            uploader=uploader,
        )
        redacted = DocumentVersion.objects.create(
            document=document,
            version=2,
            variant=DocumentVersion.Variant.REDACTED,
            storage_key=redacted_key,
            provider_version_id=redacted_key,
            filename=f"{tag}-redacted.pdf",
            content_type="application/pdf",
            byte_size=len(redacted_bytes),
            sha256=secrets.token_hex(32),
            uploader=uploader,
            redacts=original,
        )
        return original, redacted

    def make_ledger_entry(
        self,
        *,
        building,
        resident,
        unit,
        location,
        operator_membership,
        publisher_membership,
        payment_membership,
        report_text,
        actual_cost_vnd,
        contractor_name,
        snapshot_status=BlockchainOutboxEvent.Status.CONFIRMED,
        bank_reference=None,
        integrity_result=VerificationObservation.Result.VERIFIED,
    ):
        report = IssueReport.objects.create(
            reporter=resident,
            unit=unit,
            text=report_text,
            selected_location=location,
            location_path_snapshot=location.name,
        )
        TriageJob.objects.create(report=report)
        decision = TriageDecision.objects.create(
            report=report,
            operator=operator_membership.user,
            category="Plumbing",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_minutes=120,
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Plumbing",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_at=timezone.now(),
        )
        CaseReport.objects.create(
            case=case, report=report, grouped_by=operator_membership.user
        )
        work_order = WorkOrder.objects.create(
            case=case,
            assignee=operator_membership.user,
            priority="HIGH",
            deadline_at=timezone.now(),
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED,
            status=WorkOrder.Status.ACCEPTED,
        )
        creator_wallet = SignerWallet.objects.get(
            membership=operator_membership, active=True
        )
        publisher_wallet = SignerWallet.objects.get(
            membership=publisher_membership, active=True
        )
        payment_wallet = SignerWallet.objects.get(
            membership=payment_membership, active=True
        )
        proposal = Proposal.objects.create(
            work_order=work_order,
            creator_membership=operator_membership,
            mode=Proposal.Mode.NORMAL,
            status=Proposal.Status.NORMAL_AUTHORIZED,
        )
        proposal_event = self.queue_event(operator_membership)
        version = ProposalVersion.objects.create(
            proposal=proposal,
            number=1,
            amount_vnd=actual_cost_vnd,
            contractor_name=contractor_name,
            purpose="Repair",
            snapshot={"quotation_versions": []},
            snapshot_hash=secrets.token_hex(32),
            creator_membership=operator_membership,
            creator_wallet=creator_wallet,
            creator_signature="0x" + secrets.token_hex(65),
            outbox_event=proposal_event,
        )
        proposal.current_version = version
        proposal.save(update_fields=["current_version"])

        inv_o, inv_r = self.document_pair(
            building, operator_membership.user, "invoice"
        )
        acc_o, acc_r = self.document_pair(
            building, operator_membership.user, "acceptance"
        )
        proof_o, proof_r = self.document_pair(
            building, payment_membership.user, "proof"
        )
        acceptance = AcceptanceRecord.objects.create(
            work_order=work_order,
            actual_cost_vnd=actual_cost_vnd,
            invoice_original=inv_o,
            invoice_redacted=inv_r,
            acceptance_original=acc_o,
            acceptance_redacted=acc_r,
            membership=publisher_membership,
            wallet=publisher_wallet,
            signature="0x" + secrets.token_hex(65),
            outbox_event=self.queue_event(publisher_membership),
            accepted_at=timezone.now(),
        )
        payment = PaymentEvidence.objects.create(
            acceptance=acceptance,
            bank_reference=bank_reference or f"BANK-{self._unique('ref').upper()}",
            amount_vnd=actual_cost_vnd,
            external_status=PaymentEvidence.ExternalStatus.COMPLETED,
            completed_at=timezone.now(),
            proof_original=proof_o,
            proof_redacted=proof_r,
            recorder=payment_membership,
            wallet=payment_wallet,
            signature="0x" + secrets.token_hex(65),
            outbox_event=self.queue_event(payment_membership),
            recorded_at=timezone.now(),
        )
        verification = PaymentVerification.objects.create(
            payment=payment,
            membership=publisher_membership,
            decision=PaymentVerification.Decision.VERIFIED,
            reason="Matches accepted cost",
            wallet=publisher_wallet,
            signature="0x" + secrets.token_hex(65),
            outbox_event=self.queue_event(publisher_membership),
            verified_at=timezone.now(),
        )
        payload = {
            "report_id": report.pk,
            "case_id": case.pk,
            "work_order_id": work_order.pk,
            "proposal_id": proposal.pk,
            "proposal_version": version.number,
            "proposed_amount_vnd": version.amount_vnd,
            "actual_cost_vnd": actual_cost_vnd,
            "contractor_name": contractor_name,
            "mode": proposal.mode,
            "document_hashes": [inv_r.sha256, acc_r.sha256, proof_r.sha256],
            "payment_verification": {
                "decision": verification.decision,
                "payment_id": payment.pk,
                "verification_event_hash": verification.outbox_event.payload_hash,
            },
            "approvals": {
                "board": {
                    "membership_id": publisher_membership.pk,
                    "decision": "APPROVE",
                    "user_id": publisher_membership.user_id,
                }
            },
        }
        snapshot = PublicationSnapshot.objects.create(
            proposal=proposal,
            resident_payload=payload,
            resident_payload_hash=secrets.token_hex(32),
            publisher=publisher_membership,
            wallet=publisher_wallet,
            signature="0x" + secrets.token_hex(65),
            outbox_event=self.queue_event(
                publisher_membership,
                confirm=snapshot_status == BlockchainOutboxEvent.Status.CONFIRMED,
            ),
            prepared_at=timezone.now(),
        )
        if snapshot_status != BlockchainOutboxEvent.Status.CONFIRMED:
            return report, None, acceptance
        entry = PublishedLedgerEntry.objects.create(
            snapshot=snapshot,
            work_order=work_order,
            case=case,
            proposal=proposal,
            payment=payment,
            actual_cost_vnd=actual_cost_vnd,
            contractor_name=contractor_name,
            published_at=timezone.now(),
        )
        if integrity_result is not None:
            VerificationObservation.objects.create(
                published_entry=entry,
                result=integrity_result,
                checked_document_hashes=payload["document_hashes"],
                checked_chain_event_ids=[],
                details={},
                observed_at=timezone.now(),
            )
        return report, entry, acceptance


    def make_verified_source_entry(
        self,
        *,
        fund,
        recorder_membership,
        verifier_membership,
        entry_type,
        amount_vnd,
        source_key,
    ):
        """Create a source fund entry that counts in verified_only balances/flows."""
        recorder_event = self.queue_event(recorder_membership, confirm=True)
        entry = MaintenanceFundEntry.objects.create(
            fund=fund,
            entry_type=entry_type,
            amount_vnd=amount_vnd,
            source_key=source_key,
            recorded_at=timezone.now(),
            evidence_original_hash="a" * 64,
            evidence_redacted_hash="b" * 64,
            recorder=recorder_membership,
            outbox_event=recorder_event,
        )
        verifier_wallet = SignerWallet.objects.get(
            membership=verifier_membership, active=True
        )
        FundEntryVerification.objects.create(
            entry=entry,
            membership=verifier_membership,
            wallet=verifier_wallet,
            signature="0x" + secrets.token_hex(65),
            outbox_event=self.queue_event(verifier_membership, confirm=True),
            verified_at=timezone.now(),
        )
        return entry

    def make_resident_view_fixtures(self):
        tag = self._unique("res")
        building = Building.objects.create(name=f"Resident Building {tag}")
        location = BuildingLocation.objects.create(building=building, name="Basement")
        unit = Unit.objects.create(building=building, label="A-1")
        resident = get_user_model().objects.create_user(
            email=f"resident-{tag}@example.test",
            password="secret",
            display_name="Resident User",
        )
        ResidentOccupancy.objects.create(user=resident, unit=unit)

        operator, _ = self.make_signer(
            building, OrganizationMembership.Role.OPERATOR, "operator"
        )
        publisher, _ = self.make_signer(
            building, OrganizationMembership.Role.BOARD, "publisher"
        )
        payment_recorder, _ = self.make_signer(
            building, OrganizationMembership.Role.BOARD, "pay-recorder"
        )

        own_report, published_entry, _ = self.make_ledger_entry(
            building=building,
            resident=resident,
            unit=unit,
            location=location,
            operator_membership=operator,
            publisher_membership=publisher,
            payment_membership=payment_recorder,
            report_text="Water leak in basement pipe",
            actual_cost_vnd=18_500_000,
            contractor_name="Company X",
        )
        # Second cost present as accepted work that was never finalized/published.
        _pending_report, _no_entry, unpublished_entry = self.make_ledger_entry(
            building=building,
            resident=resident,
            unit=unit,
            location=location,
            operator_membership=operator,
            publisher_membership=publisher,
            payment_membership=payment_recorder,
            report_text="Pending unpublished drain work",
            actual_cost_vnd=9_999_111,
            contractor_name="Hidden Co",
            snapshot_status=BlockchainOutboxEvent.Status.PENDING,
        )

        fund = MaintenanceFund.objects.create(building=building)
        MaintenanceFundEntry.objects.create(
            fund=fund,
            entry_type=MaintenanceFundEntry.EntryType.OPENING_BALANCE,
            amount_vnd=100_000_000,
            source_key=f"OPENING_BALANCE:{fund.pk}:fixture-{tag}",
            recorded_at=timezone.now(),
            evidence_original_hash="a" * 64,
            evidence_redacted_hash="b" * 64,
        )

        return resident, own_report, published_entry, unpublished_entry

    def test_resident_sees_own_case_and_published_redacted_ledger_only(self):
        resident, own_report, published_entry, unpublished_entry = (
            self.make_resident_view_fixtures()
        )
        self.client.force_login(resident)

        home = self.client.get(reverse("web:resident-home"))
        ledger = self.client.get(reverse("web:ledger-list"))

        self.assertContains(home, own_report.text)
        self.assertContains(ledger, str(published_entry.actual_cost_vnd))
        self.assertNotContains(ledger, str(unpublished_entry.actual_cost_vnd))
        self.assertContains(ledger, "Record verified")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("web:resident-home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response["Location"])

    def test_report_create_submits_via_service(self):
        resident, _own_report, _published, _unpublished = self.make_resident_view_fixtures()
        occupancy = ResidentOccupancy.objects.get(user=resident, active=True)
        location = BuildingLocation.objects.filter(
            building=occupancy.unit.building, active=True
        ).first()
        self.client.force_login(resident)

        response = self.client.post(
            reverse("web:report-create"),
            {
                "text": "New corridor light out",
                "location": location.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = IssueReport.objects.get(text="New corridor light out")
        self.assertEqual(created.reporter_id, resident.pk)
        self.assertEqual(created.unit_id, occupancy.unit_id)

    def test_ledger_detail_shows_links_without_private_bank_details(self):
        resident, _own_report, published_entry, _unpublished = (
            self.make_resident_view_fixtures()
        )
        self.client.force_login(resident)

        response = self.client.get(
            reverse("web:ledger-detail", kwargs={"pk": published_entry.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, published_entry.contractor_name)
        self.assertContains(response, str(published_entry.actual_cost_vnd))
        self.assertContains(response, "Record verified")
        # Private bank reference must never appear for residents.
        self.assertNotContains(response, published_entry.payment.bank_reference)
        self.assertNotContains(response, "private bank")

    def test_work_rating_form_only_when_eligible(self):
        resident, own_report, published_entry, _unpublished = (
            self.make_resident_view_fixtures()
        )
        work_order = published_entry.work_order
        work_order.status = WorkOrder.Status.CLOSED
        work_order.save(update_fields=["status"])
        self.client.force_login(resident)

        detail = self.client.get(
            reverse("web:report-detail", kwargs={"pk": own_report.pk})
        )
        self.assertContains(detail, reverse("web:work-rate", kwargs={"pk": work_order.pk}))

        response = self.client.post(
            reverse("web:work-rate", kwargs={"pk": work_order.pk}),
            {"score": "5", "comment": "Fixed well"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            CompletionRating.objects.filter(
                resident=resident, work_order=work_order, score=5
            ).exists()
        )

    def test_pwa_shell_and_manifest_are_served(self):
        resident, *_ = self.make_resident_view_fixtures()
        self.client.force_login(resident)

        home = self.client.get(reverse("web:resident-home"))
        self.assertContains(home, 'rel="manifest"')
        self.assertContains(home, "service-worker.js")
        self.assertContains(home, 'role="navigation"')
        self.assertContains(home, "Home")
        self.assertContains(home, "Report")
        self.assertContains(home, "My issues")
        self.assertContains(home, "Ledger")
        self.assertContains(home, "Account")

        manifest = self.client.get(reverse("web:manifest"))
        self.assertEqual(manifest.status_code, 200)
        self.assertIn("application/manifest+json", manifest["Content-Type"])
        self.assertContains(manifest, "LamTo")

        sw = self.client.get(reverse("web:service-worker"))
        self.assertEqual(sw.status_code, 200)
        self.assertIn("javascript", sw["Content-Type"])
        body = sw.content.decode()
        self.assertIn("caches", body)
        self.assertIn("isAuthenticatedHtmlPath", body)
        self.assertIn("isStaticAsset", body)
        # Precache list must not include authenticated resident routes.
        self.assertNotIn('"/r/report', body)
        self.assertNotIn('PRECACHE_URLS = ["/r/', body)

    def test_account_shows_profile_without_staff_roles(self):
        resident, *_ = self.make_resident_view_fixtures()
        self.client.force_login(resident)
        response = self.client.get(reverse("web:account"))
        self.assertContains(response, resident.display_name)
        self.assertContains(response, resident.email)
        self.assertNotContains(response, "OPERATOR")
        self.assertNotContains(response, "BOARD")

    def test_sign_out_post_clears_session_and_redirects_to_login(self):
        resident, *_ = self.make_resident_view_fixtures()
        self.client.force_login(resident)
        account = self.client.get(reverse("web:account"))
        self.assertContains(account, 'method="post"')
        self.assertContains(account, reverse("logout"))
        # GET logout is not allowed on Django 5 LogoutView.
        get_logout = self.client.get(reverse("logout"))
        self.assertEqual(get_logout.status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response["Location"])
        # Session is cleared — home requires auth again.
        home = self.client.get(reverse("web:resident-home"))
        self.assertEqual(home.status_code, 302)
        self.assertIn("/accounts/login", home["Location"])

    def test_integrity_labels_for_mismatch_and_unchecked(self):
        resident, *_rest = self.make_resident_view_fixtures()
        occupancy = ResidentOccupancy.objects.get(user=resident, active=True)
        building = occupancy.unit.building
        unit = occupancy.unit
        location = BuildingLocation.objects.filter(building=building).first()
        operator = OrganizationMembership.objects.filter(
            organization__building=building,
            role=OrganizationMembership.Role.OPERATOR,
        ).first()
        board_members = list(
            OrganizationMembership.objects.filter(
                organization__building=building,
                role=OrganizationMembership.Role.BOARD,
            ).order_by("pk")
        )
        publisher = board_members[0]
        payment_recorder = board_members[1]
        self.client.force_login(resident)

        _report_m, mismatch_entry, _ = self.make_ledger_entry(
            building=building,
            resident=resident,
            unit=unit,
            location=location,
            operator_membership=operator,
            publisher_membership=publisher,
            payment_membership=payment_recorder,
            report_text="Mismatch integrity case",
            actual_cost_vnd=12_100_000,
            contractor_name="Mismatch Co",
            integrity_result=VerificationObservation.Result.MISMATCH,
        )
        detail = self.client.get(
            reverse("web:ledger-detail", kwargs={"pk": mismatch_entry.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Integrity mismatch detected")
        self.assertContains(detail, "status-mismatch")
        self.assertContains(detail, 'role="alert"')
        self.assertNotContains(detail, "Record verified")
        ledger = self.client.get(reverse("web:ledger-list"))
        self.assertContains(ledger, "Integrity mismatch detected")
        self.assertContains(ledger, "status-mismatch")

        _report_u, unchecked_entry, _ = self.make_ledger_entry(
            building=building,
            resident=resident,
            unit=unit,
            location=location,
            operator_membership=operator,
            publisher_membership=publisher,
            payment_membership=payment_recorder,
            report_text="Unchecked integrity case",
            actual_cost_vnd=13_200_000,
            contractor_name="Unchecked Co",
            integrity_result=None,
        )
        detail = self.client.get(
            reverse("web:ledger-detail", kwargs={"pk": unchecked_entry.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Published — integrity not yet checked")
        self.assertContains(detail, "status-info")
        self.assertNotContains(detail, "Record verified")
        self.assertNotContains(detail, 'role="alert"')
        ledger = self.client.get(reverse("web:ledger-list"))
        self.assertContains(ledger, "Published — integrity not yet checked")
        self.assertContains(ledger, "status-info")

    def test_home_period_and_opening_use_verified_fund_filter(self):
        resident, *_ = self.make_resident_view_fixtures()
        occupancy = ResidentOccupancy.objects.get(user=resident, active=True)
        building = occupancy.unit.building
        fund = MaintenanceFund.objects.get(building=building)
        operator = OrganizationMembership.objects.filter(
            organization__building=building,
            role=OrganizationMembership.Role.OPERATOR,
        ).first()
        board_members = list(
            OrganizationMembership.objects.filter(
                organization__building=building,
                role=OrganizationMembership.Role.BOARD,
            ).order_by("pk")
        )
        recorder = board_members[0]
        verifier = board_members[1] if len(board_members) > 1 else operator

        # Unverified opening already exists from fixtures; add unverified inflow.
        MaintenanceFundEntry.objects.create(
            fund=fund,
            entry_type=MaintenanceFundEntry.EntryType.INFLOW,
            amount_vnd=7_777_000,
            source_key=f"INFLOW:unverified:{fund.pk}:{self._unique('u')}",
            recorded_at=timezone.now(),
            evidence_original_hash="c" * 64,
            evidence_redacted_hash="d" * 64,
        )
        # Verified inflow should appear in period totals and balance.
        self.make_verified_source_entry(
            fund=fund,
            recorder_membership=recorder,
            verifier_membership=verifier,
            entry_type=MaintenanceFundEntry.EntryType.INFLOW,
            amount_vnd=3_000_000,
            source_key=f"INFLOW:verified:{fund.pk}:{self._unique('v')}",
        )
        # Verified opening should drive opening_balance display.
        self.make_verified_source_entry(
            fund=fund,
            recorder_membership=recorder,
            verifier_membership=verifier,
            entry_type=MaintenanceFundEntry.EntryType.OPENING_BALANCE,
            amount_vnd=50_000_000,
            source_key=f"OPENING_BALANCE:verified:{fund.pk}:{self._unique('o')}",
        )

        self.client.force_login(resident)
        home = self.client.get(reverse("web:resident-home"))
        self.assertEqual(home.status_code, 200)
        # Unverified 100M opening and 7.777M inflow must not inflate figures.
        self.assertEqual(home.context["opening_balance"], 50_000_000)
        self.assertEqual(home.context["balance"], 53_000_000)
        # Opening was recorded in-window, so period inflows include verified opening + inflow.
        self.assertEqual(home.context["period_inflows"], 53_000_000)
        self.assertEqual(home.context["period_outflows"], 0)
        self.assertNotContains(home, "100000000")
        self.assertNotContains(home, "7777000")
