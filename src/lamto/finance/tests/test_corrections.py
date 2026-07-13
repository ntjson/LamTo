import hashlib
from pathlib import Path
import secrets
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import storages
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import (
    CORRECTION_APPROVE,
    CORRECTION_CREATE,
    FUND_RECORD,
    FUND_VERIFY,
    LEDGER_PUBLISH,
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    PROPOSAL_APPROVE,
    PROPOSAL_CREATE,
    WORK_ACCEPT,
    WORK_ASSIGN,
)
from lamto.accounts.models import Building, Organization, OrganizationMembership, Unit
from lamto.accounts.services import grant_capability
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.acceptance import accept_work, build_acceptance_evidence_typed_data
from lamto.finance.approvals import build_approval_evidence_payload, decide_proposal
from lamto.finance.corrections import (
    allocate_correction_id,
    allocate_correction_publication_id,
    build_correction_evidence_typed_data,
    create_correction,
    decide_correction,
    finalize_correction_publication,
    prepare_correction_publication,
)
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
    fund_balance,
    get_or_create_fund,
    record_fund_source,
    verify_fund_source,
)
from lamto.finance.models import (
    Correction,
    CorrectionDecision,
    MaintenanceFundEntry,
    PublishedLedgerEntry,
)
from lamto.finance.payments import (
    allocate_payment_id,
    build_payment_evidence_typed_data,
    build_payment_verification_evidence_typed_data,
    record_payment,
    verify_payment,
)
from lamto.finance.proposals import build_proposal_evidence_payload, create_proposal, submit_proposal_version
from lamto.finance.publication import (
    allocate_publication_id,
    build_publication_evidence_typed_data,
    finalize_publication,
    prepare_publication,
)
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    TriageJob,
    WorkOrder,
)
from lamto.maintenance.workorders import complete_work_order, start_work_order

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-corr-")
ZERO = "0x" + "00" * 32
ZERO_BARE = "00" * 32


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
    }
)
class CorrectionTests(TestCase):
    def _unique(self, base):
        n = getattr(self, "_fixture_seq", 0) + 1
        self._fixture_seq = n
        return f"{base}-{n}"

    def make_signer(self, building, role, capability, suffix):
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
        grant_capability(membership, capability)
        account = Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        register_wallet(membership, account.address, proof)
        return membership, account

    def document_pair(self, building, kind, uploader, prefix):
        tag = self._unique(prefix)
        document = Document.objects.create(building=building, kind=kind)
        original_bytes = f"{tag}-original-content".encode()
        redacted_bytes = f"{tag}-redacted-content".encode()
        original_key = f"docs/{tag}-original"
        redacted_key = f"docs/{tag}-redacted"
        storage = storages["private"]
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
            sha256=hashlib.sha256(original_bytes).hexdigest(),
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
            sha256=hashlib.sha256(redacted_bytes).hexdigest(),
            uploader=uploader,
            redacts=original,
        )
        return original, redacted

    def photo(self, building, kind, uploader, prefix):
        tag = self._unique(prefix)
        content = f"{tag}-photo".encode()
        key = f"photos/{tag}"
        storage = storages["private"]
        Path(storage.path(key)).parent.mkdir(parents=True, exist_ok=True)
        with storage.open(key, "wb") as handle:
            handle.write(content)
        return DocumentVersion.objects.create(
            document=Document.objects.create(building=building, kind=kind),
            version=1,
            variant=DocumentVersion.Variant.ORIGINAL,
            storage_key=key,
            provider_version_id=key,
            filename=f"{tag}.jpg",
            content_type="image/jpeg",
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            uploader=uploader,
        )

    def confirm(self, event):
        event.status = BlockchainOutboxEvent.Status.CONFIRMED
        event.confirmed_at = timezone.now()
        event.save(update_fields=["status", "confirmed_at"])

    def confirm_chain(self, *events):
        for event in events:
            self.confirm(event)

    def make_published_context(self, amount=18_500_000):
        tag = self._unique("corr")
        building = Building.objects.create(name=f"Correction Building {tag}")
        location = BuildingLocation.objects.create(building=building, name="Lobby")
        unit = Unit.objects.create(building=building, label="A-1")
        operator, operator_account = self.make_signer(
            building, OrganizationMembership.Role.OPERATOR, PROPOSAL_CREATE, "operator"
        )
        grant_capability(operator, WORK_ASSIGN)
        grant_capability(operator, CORRECTION_CREATE)
        maintenance_user = get_user_model().objects.create_user(
            email=f"maint-{tag}@example.test", password="secret", display_name="Maint"
        )
        OrganizationMembership.objects.create(
            user=maintenance_user,
            organization=operator.organization,
            role=OrganizationMembership.Role.MAINTENANCE,
        )
        report = IssueReport.objects.create(
            reporter=get_user_model().objects.create_user(
                email=f"res-{tag}@example.test", password="secret", display_name="Res"
            ),
            unit=unit,
            text="Elevator shakes",
            selected_location=location,
            location_path_snapshot="Lobby",
        )
        TriageJob.objects.create(report=report)
        decision = TriageDecision.objects.create(
            report=report,
            suggestion=None,
            operator=operator.user,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_minutes=240,
        )
        case = MaintenanceCase.objects.create(
            decision=decision,
            building=building,
            category="Elevator",
            urgency="HIGH",
            location=location,
            department="Maintenance",
            deadline_at="2026-07-20T12:00:00Z",
        )
        work_order = WorkOrder.objects.create(
            case=case,
            assignee=maintenance_user,
            priority="HIGH",
            deadline_at=case.deadline_at,
            requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.PENDING,
        )
        quotation_original, _ = self.document_pair(
            building, Document.Kind.QUOTATION, operator.user, "quotation"
        )
        proposal = create_proposal(work_order, operator)
        event_id = "0x" + secrets.token_hex(32)
        payload = build_proposal_evidence_payload(
            proposal, amount, "Company X", [quotation_original]
        )
        typed = build_evidence_typed_data(
            event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), ZERO
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), operator_account.key
        ).signature.hex()
        version = submit_proposal_version(
            proposal, amount, "Company X", [quotation_original], signature, event_id
        )

        board_approver, board_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, PROPOSAL_APPROVE, "board-approve"
        )
        grant_capability(board_approver, WORK_ACCEPT)
        grant_capability(board_approver, PAYMENT_RECORD)
        grant_capability(board_approver, CORRECTION_APPROVE)
        representative, rep_account = self.make_signer(
            building,
            OrganizationMembership.Role.RESIDENT_REP,
            PROPOSAL_APPROVE,
            "representative",
        )
        grant_capability(representative, CORRECTION_APPROVE)
        board_event = "0x" + secrets.token_hex(32)
        rep_event = "0x" + secrets.token_hex(32)
        board_payload = build_approval_evidence_payload(version, board_approver, "APPROVE")
        board_typed = build_evidence_typed_data(
            board_event,
            EvidenceType.BOARD_APPROVAL,
            "0x" + payload_hash(board_payload),
            "0x" + version.outbox_event.payload_hash,
        )
        board_sig = Account.sign_message(
            encode_typed_data(full_message=board_typed), board_account.key
        ).signature.hex()
        rep_payload = build_approval_evidence_payload(version, representative, "APPROVE")
        rep_typed = build_evidence_typed_data(
            rep_event,
            EvidenceType.REPRESENTATIVE_APPROVAL,
            "0x" + payload_hash(rep_payload),
            "0x" + payload_hash(board_payload),
        )
        rep_sig = Account.sign_message(
            encode_typed_data(full_message=rep_typed), rep_account.key
        ).signature.hex()
        decide_proposal(version, board_approver, "APPROVE", "Within budget", board_sig, board_event)
        decide_proposal(
            version, representative, "APPROVE", "Evidence checked", rep_sig, rep_event
        )

        work_order.refresh_from_db()
        start_work_order(work_order, maintenance_user)
        before = self.photo(building, Document.Kind.BEFORE_PHOTO, maintenance_user, "before")
        after = self.photo(building, Document.Kind.AFTER_PHOTO, maintenance_user, "after")
        complete_work_order(
            work_order, maintenance_user, "Worn cable", "Cable secured", [before], [after]
        )
        work_order.refresh_from_db()

        invoice_original, invoice_redacted = self.document_pair(
            building, Document.Kind.INVOICE, operator.user, "invoice"
        )
        acceptance_original, acceptance_redacted = self.document_pair(
            building, Document.Kind.ACCEPTANCE_REPORT, operator.user, "acceptance"
        )
        accept_event = "0x" + secrets.token_hex(32)
        accept_typed = build_acceptance_evidence_typed_data(
            work_order,
            board_approver,
            amount,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            accept_event,
            timestamp=work_order.completed_at,
        )
        accept_sig = Account.sign_message(
            encode_typed_data(full_message=accept_typed), board_account.key
        ).signature.hex()
        acceptance = accept_work(
            work_order,
            board_approver,
            amount,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            accept_sig,
            accept_event,
            timestamp=work_order.completed_at,
        )

        payment_recorder, payment_recorder_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, PAYMENT_RECORD, "pay-recorder"
        )
        payment_verifier, payment_verifier_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, PAYMENT_VERIFY, "pay-verifier"
        )
        publisher, publisher_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, LEDGER_PUBLISH, "publisher"
        )
        # Separate correction publisher (may not be correction board approver).
        corr_publisher, corr_publisher_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, LEDGER_PUBLISH, "corr-publisher"
        )
        corr_board, corr_board_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, CORRECTION_APPROVE, "corr-board"
        )
        corr_rep, corr_rep_account = self.make_signer(
            building,
            OrganizationMembership.Role.RESIDENT_REP,
            CORRECTION_APPROVE,
            "corr-rep",
        )

        accounts = {
            operator.pk: operator_account,
            board_approver.pk: board_account,
            representative.pk: rep_account,
            payment_recorder.pk: payment_recorder_account,
            payment_verifier.pk: payment_verifier_account,
            publisher.pk: publisher_account,
            corr_publisher.pk: corr_publisher_account,
            corr_board.pk: corr_board_account,
            corr_rep.pk: corr_rep_account,
        }

        proof_original, proof_redacted = self.document_pair(
            building, Document.Kind.PAYMENT_PROOF, payment_recorder.user, "proof"
        )
        payment_id = allocate_payment_id()
        payment_event = "0x" + secrets.token_hex(32)
        completed_at = timezone.now()
        bank_ref = f"BANK-CORR-{tag.upper()}"
        payment_typed = build_payment_evidence_typed_data(
            acceptance,
            payment_recorder,
            payment_id,
            bank_ref,
            amount,
            "COMPLETED",
            completed_at,
            proof_original,
            proof_redacted,
            payment_event,
        )
        payment_sig = Account.sign_message(
            encode_typed_data(full_message=payment_typed), payment_recorder_account.key
        ).signature.hex()
        payment = record_payment(
            acceptance,
            payment_recorder,
            bank_ref,
            amount,
            "COMPLETED",
            completed_at,
            proof_original,
            proof_redacted,
            payment_sig,
            payment_event,
            payment_id,
        )
        verify_event = "0x" + secrets.token_hex(32)
        verify_typed = build_payment_verification_evidence_typed_data(
            payment, payment_verifier, "VERIFIED", verify_event, timestamp=payment.recorded_at
        )
        verify_sig = Account.sign_message(
            encode_typed_data(full_message=verify_typed), payment_verifier_account.key
        ).signature.hex()
        verification = verify_payment(
            payment,
            payment_verifier,
            "VERIFIED",
            "Matches accepted cost",
            verify_sig,
            verify_event,
            timestamp=payment.recorded_at,
        )
        self.confirm_chain(
            version.outbox_event,
            version.approval_decisions.get(stage="BOARD").outbox_event,
            version.approval_decisions.get(stage="RESIDENT_REP").outbox_event,
            acceptance.outbox_event,
            payment.outbox_event,
            verification.outbox_event,
        )

        fund = get_or_create_fund(building)
        fund_recorder, fund_recorder_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, FUND_RECORD, "fund-rec"
        )
        fund_verifier, fund_verifier_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, FUND_VERIFY, "fund-ver"
        )
        accounts[fund_recorder.pk] = fund_recorder_account
        accounts[fund_verifier.pk] = fund_verifier_account
        fund_original, fund_redacted = self.document_pair(
            building, Document.Kind.CONTRACT, fund_recorder.user, "fund-open"
        )
        fund_entry_id = allocate_fund_entry_id()
        fund_event = "0x" + secrets.token_hex(32)
        fund_ts = timezone.now()
        fund_typed = build_fund_source_evidence_typed_data(
            fund,
            fund_recorder,
            fund_entry_id,
            MaintenanceFundEntry.EntryType.OPENING_BALANCE,
            100_000_000,
            fund_original,
            fund_redacted,
            fund_event,
            timestamp=fund_ts,
        )
        fund_sig = Account.sign_message(
            encode_typed_data(full_message=fund_typed), fund_recorder_account.key
        ).signature.hex()
        fund_entry = record_fund_source(
            fund,
            MaintenanceFundEntry.EntryType.OPENING_BALANCE,
            100_000_000,
            fund_original,
            fund_redacted,
            fund_recorder,
            fund_sig,
            fund_event,
            fund_entry_id=fund_entry_id,
            timestamp=fund_ts,
        )
        fund_verify_event = "0x" + secrets.token_hex(32)
        fund_verify_typed = build_fund_verification_evidence_typed_data(
            fund_entry, fund_verifier, fund_verify_event, timestamp=fund_entry.recorded_at
        )
        fund_verify_sig = Account.sign_message(
            encode_typed_data(full_message=fund_verify_typed), fund_verifier_account.key
        ).signature.hex()
        fund_verification = verify_fund_source(
            fund_entry,
            fund_verifier,
            fund_verify_sig,
            fund_verify_event,
            timestamp=fund_entry.recorded_at,
        )
        self.confirm_chain(fund_entry.outbox_event, fund_verification.outbox_event)

        from lamto.finance.publication import _collect_document_checks, _resident_payload

        proposal.refresh_from_db()
        version = proposal.current_version
        checks = _collect_document_checks(proposal, version, acceptance, payment, verification)
        document_hashes = sorted({doc.sha256 for doc, expected, _ in checks})
        resident_payload = _resident_payload(
            proposal, version, acceptance, payment, verification, document_hashes
        )
        board_decision = version.approval_decisions.get(stage="BOARD")
        rep_decision = version.approval_decisions.get(stage="RESIDENT_REP")
        prerequisite_event_hashes = [
            version.outbox_event.payload_hash,
            board_decision.outbox_event.payload_hash,
            rep_decision.outbox_event.payload_hash,
            acceptance.outbox_event.payload_hash,
            payment.outbox_event.payload_hash,
            verification.outbox_event.payload_hash,
        ]
        publication_id = allocate_publication_id()
        pub_event = "0x" + secrets.token_hex(32)
        pub_ts = timezone.now()
        previous_hash = "0x" + verification.outbox_event.payload_hash
        pub_typed = build_publication_evidence_typed_data(
            proposal,
            publisher,
            publication_id,
            prerequisite_event_hashes,
            resident_payload,
            document_hashes,
            pub_event,
            timestamp=pub_ts,
            previous_hash=previous_hash,
        )
        pub_sig = Account.sign_message(
            encode_typed_data(full_message=pub_typed), publisher_account.key
        ).signature.hex()
        snapshot = prepare_publication(
            proposal,
            publisher,
            pub_sig,
            pub_event,
            publication_id=publication_id,
            timestamp=pub_ts,
        )
        self.confirm(snapshot.outbox_event)
        entry = finalize_publication(snapshot.pk)
        return {
            "building": building,
            "entry": entry,
            "operator": operator,
            "accounts": accounts,
            "corr_board": corr_board,
            "corr_rep": corr_rep,
            "corr_publisher": corr_publisher,
            "board_approver": board_approver,
            "payment_recorder": payment_recorder,
            "amount": amount,
        }

    def correction_evidence_doc(self, building, uploader):
        original, _ = self.document_pair(
            building, Document.Kind.CORRECTION_EVIDENCE, uploader, "corr-evidence"
        )
        return original

    def sign_correction(self, membership, account, **kwargs):
        event_id = kwargs.pop("event_id", "0x" + secrets.token_hex(32))
        typed = build_correction_evidence_typed_data(
            event_id=event_id,
            actor_organization_id=membership.organization_id,
            **kwargs,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()
        return signature, event_id

    def test_correction_flow_reverses_and_replaces_without_mutating_original(self):
        ctx = self.make_published_context()
        entry = ctx["entry"]
        building = ctx["building"]
        operator = ctx["operator"]
        original_cost = entry.actual_cost_vnd
        original_published_at = entry.published_at
        original_outflow = MaintenanceFundEntry.objects.get(
            proposal=entry.proposal, entry_type=MaintenanceFundEntry.EntryType.OUTFLOW
        )
        balance_before = fund_balance(building.pk, verified_only=True)

        evidence = self.correction_evidence_doc(building, operator.user)
        new_amount = 17_000_000
        correction_id = allocate_correction_id()
        create_ts = timezone.now()
        replacement_hashes = [evidence.sha256]
        sig, event_id = self.sign_correction(
            operator,
            ctx["accounts"][operator.pk],
            correction_id=correction_id,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="Invoice reissued after supplier credit",
            decision="APPROVE",
            publisher_snapshot_hash=ZERO_BARE,
            timestamp=create_ts,
            previous_hash="0x" + entry.snapshot.outbox_event.payload_hash,
        )
        correction = create_correction(
            entry,
            operator,
            "Invoice reissued after supplier credit",
            {"actual_cost_vnd": new_amount, "contractor_name": "Company X"},
            [evidence],
            sig,
            event_id,
            correction_id=correction_id,
            timestamp=create_ts,
        )
        self.assertEqual(correction.outbox_event.event_type, EvidenceType.CORRECTION)
        self.confirm(correction.outbox_event)

        # Board then rep approvals.
        board = ctx["corr_board"]
        board_ts = timezone.now()
        board_sig, board_event = self.sign_correction(
            board,
            ctx["accounts"][board.pk],
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="Board accepts supplier credit",
            decision="APPROVE",
            publisher_snapshot_hash=ZERO_BARE,
            timestamp=board_ts,
            previous_hash="0x" + correction.outbox_event.payload_hash,
        )
        board_decision = decide_correction(
            correction,
            board,
            CorrectionDecision.Stage.BOARD,
            "APPROVE",
            "Board accepts supplier credit",
            board_sig,
            board_event,
            timestamp=board_ts,
        )
        self.confirm(board_decision.outbox_event)

        rep = ctx["corr_rep"]
        rep_ts = timezone.now()
        rep_sig, rep_event = self.sign_correction(
            rep,
            ctx["accounts"][rep.pk],
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="Representative co-approves",
            decision="APPROVE",
            publisher_snapshot_hash=ZERO_BARE,
            timestamp=rep_ts,
            previous_hash="0x" + board_decision.outbox_event.payload_hash,
        )
        rep_decision = decide_correction(
            correction,
            rep,
            CorrectionDecision.Stage.RESIDENT_REP,
            "APPROVE",
            "Representative co-approves",
            rep_sig,
            rep_event,
            timestamp=rep_ts,
        )
        self.confirm(rep_decision.outbox_event)

        # Prior-hash linkage: create -> board -> rep chain.
        self.assertEqual(
            board_decision.outbox_event.previous_hash,
            "0x" + correction.outbox_event.payload_hash,
        )
        self.assertEqual(
            rep_decision.outbox_event.previous_hash,
            "0x" + board_decision.outbox_event.payload_hash,
        )
        self.assertEqual(
            correction.outbox_event.previous_hash,
            "0x" + entry.snapshot.outbox_event.payload_hash,
        )

        # Publish with eligible correction publisher.
        publisher = ctx["corr_publisher"]
        snapshot_id = allocate_correction_publication_id()
        pub_ts = timezone.now()
        # prepare will recompute resident payload hash; sign with the same helper fields
        # that prepare uses. Build typed data after a dry compute of the payload hash via
        # prepare's private helper through a trial sign matching service expectations.
        from lamto.finance.corrections import _correction_resident_payload

        resident_payload = _correction_resident_payload(correction)
        resident_payload_hash = payload_hash(resident_payload)
        pub_sig, pub_event = self.sign_correction(
            publisher,
            ctx["accounts"][publisher.pk],
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason=correction.reason,
            decision="APPROVE",
            publisher_snapshot_hash=resident_payload_hash,
            timestamp=pub_ts,
            previous_hash="0x" + rep_decision.outbox_event.payload_hash,
        )
        snapshot = prepare_correction_publication(
            correction,
            publisher,
            pub_sig,
            pub_event,
            snapshot_id=snapshot_id,
            timestamp=pub_ts,
        )
        self.assertEqual(snapshot.resident_payload_hash, resident_payload_hash)
        with self.assertRaises(ValidationError):
            finalize_correction_publication(snapshot.pk)

        self.confirm(snapshot.outbox_event)
        first = finalize_correction_publication(snapshot.pk)
        second = finalize_correction_publication(snapshot.pk)
        self.assertEqual(first.pk, second.pk)

        entry.refresh_from_db()
        original_outflow.refresh_from_db()
        self.assertEqual(entry.actual_cost_vnd, original_cost)
        self.assertEqual(entry.published_at, original_published_at)
        self.assertEqual(original_outflow.amount_vnd, -original_cost)

        reverse = MaintenanceFundEntry.objects.get(
            correction=correction, entry_type=MaintenanceFundEntry.EntryType.REVERSAL
        )
        replacement = MaintenanceFundEntry.objects.get(
            correction=correction, entry_type=MaintenanceFundEntry.EntryType.REPLACEMENT
        )
        self.assertEqual(reverse.amount_vnd, original_cost)
        self.assertEqual(replacement.amount_vnd, -new_amount)
        self.assertEqual(
            MaintenanceFundEntry.objects.filter(correction=correction).count(), 2
        )
        # Net: opening 100M - original + reverse - replacement = 100M - new
        self.assertEqual(
            fund_balance(building.pk, verified_only=True),
            balance_before + original_cost - new_amount,
        )
        correction.refresh_from_db()
        self.assertTrue(correction.is_resident_visible)

        # Original remains immutable at ORM layer.
        with self.assertRaises(ValueError):
            entry.actual_cost_vnd = 1
            entry.save()

    def test_correction_board_approver_cannot_publish(self):
        ctx = self.make_published_context()
        entry = ctx["entry"]
        building = ctx["building"]
        operator = ctx["operator"]
        evidence = self.correction_evidence_doc(building, operator.user)
        correction_id = allocate_correction_id()
        create_ts = timezone.now()
        replacement_hashes = [evidence.sha256]
        sig, event_id = self.sign_correction(
            operator,
            ctx["accounts"][operator.pk],
            correction_id=correction_id,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="Typo in contractor",
            decision="APPROVE",
            publisher_snapshot_hash=ZERO_BARE,
            timestamp=create_ts,
            previous_hash="0x" + entry.snapshot.outbox_event.payload_hash,
        )
        correction = create_correction(
            entry,
            operator,
            "Typo in contractor",
            {"actual_cost_vnd": entry.actual_cost_vnd, "contractor_name": "Company Y"},
            [evidence],
            sig,
            event_id,
            correction_id=correction_id,
            timestamp=create_ts,
        )
        self.confirm(correction.outbox_event)

        board = ctx["corr_board"]
        grant_capability(board, LEDGER_PUBLISH)
        board_ts = timezone.now()
        board_sig, board_event = self.sign_correction(
            board,
            ctx["accounts"][board.pk],
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="ok",
            decision="APPROVE",
            publisher_snapshot_hash=ZERO_BARE,
            timestamp=board_ts,
            previous_hash="0x" + correction.outbox_event.payload_hash,
        )
        board_decision = decide_correction(
            correction,
            board,
            CorrectionDecision.Stage.BOARD,
            "APPROVE",
            "ok",
            board_sig,
            board_event,
            timestamp=board_ts,
        )
        self.confirm(board_decision.outbox_event)

        rep = ctx["corr_rep"]
        rep_ts = timezone.now()
        rep_sig, rep_event = self.sign_correction(
            rep,
            ctx["accounts"][rep.pk],
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="ok",
            decision="APPROVE",
            publisher_snapshot_hash=ZERO_BARE,
            timestamp=rep_ts,
            previous_hash="0x" + board_decision.outbox_event.payload_hash,
        )
        rep_decision = decide_correction(
            correction,
            rep,
            CorrectionDecision.Stage.RESIDENT_REP,
            "APPROVE",
            "ok",
            rep_sig,
            rep_event,
            timestamp=rep_ts,
        )
        self.confirm(rep_decision.outbox_event)

        from lamto.finance.corrections import _correction_resident_payload

        pub_ts = timezone.now()
        resident_payload_hash = payload_hash(_correction_resident_payload(correction))
        # Board approver tries to publish.
        pub_sig, pub_event = self.sign_correction(
            board,
            ctx["accounts"][board.pk],
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason=correction.reason,
            decision="APPROVE",
            publisher_snapshot_hash=resident_payload_hash,
            timestamp=pub_ts,
            previous_hash="0x" + rep_decision.outbox_event.payload_hash,
        )
        with self.assertRaises(PermissionDenied):
            prepare_correction_publication(
                correction,
                board,
                pub_sig,
                pub_event,
                timestamp=pub_ts,
            )
