import hashlib
from pathlib import Path
import secrets
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import storages
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.capabilities import (
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
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
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

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-integrity-")


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
class IntegrityTests(TestCase):
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

    def make_published_entry(self):
        tag = self._unique("int")
        building = Building.objects.create(name=f"Integrity Building {tag}")
        location = BuildingLocation.objects.create(building=building, name="Lobby")
        unit = Unit.objects.create(building=building, label="A-1")
        operator, operator_account = self.make_signer(
            building, OrganizationMembership.Role.OPERATOR, PROPOSAL_CREATE, "operator"
        )
        grant_capability(operator, WORK_ASSIGN)
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
        quotation_original, _quotation_redacted = self.document_pair(
            building, Document.Kind.QUOTATION, operator.user, "quotation"
        )
        proposal = create_proposal(work_order, operator)
        event_id = "0x" + secrets.token_hex(32)
        payload = build_proposal_evidence_payload(
            proposal, 18_500_000, "Company X", [quotation_original]
        )
        typed = build_evidence_typed_data(
            event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), "0x" + "00" * 32
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), operator_account.key
        ).signature.hex()
        version = submit_proposal_version(
            proposal, 18_500_000, "Company X", [quotation_original], signature, event_id
        )

        board_approver, board_account = self.make_signer(
            building, OrganizationMembership.Role.BOARD, PROPOSAL_APPROVE, "board-approve"
        )
        grant_capability(board_approver, WORK_ACCEPT)
        grant_capability(board_approver, PAYMENT_RECORD)
        representative, rep_account = self.make_signer(
            building,
            OrganizationMembership.Role.RESIDENT_REP,
            PROPOSAL_APPROVE,
            "representative",
        )
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
            18_500_000,
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
            18_500_000,
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

        proof_original, proof_redacted = self.document_pair(
            building, Document.Kind.PAYMENT_PROOF, payment_recorder.user, "proof"
        )
        payment_id = allocate_payment_id()
        payment_event = "0x" + secrets.token_hex(32)
        completed_at = timezone.now()
        bank_ref = f"BANK-INT-{tag.upper()}"
        payment_typed = build_payment_evidence_typed_data(
            acceptance,
            payment_recorder,
            payment_id,
            bank_ref,
            18_500_000,
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
            18_500_000,
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
        # Return a published document version used in the publication (invoice original).
        return entry, invoice_original

    def replace_test_storage_bytes(self, storage_key, new_bytes):
        storage = storages["private"]
        with storage.open(storage_key, "wb") as handle:
            handle.write(new_bytes)

    def test_changed_document_appends_mismatch_without_mutating_entry(self):
        entry, version = self.make_published_entry()
        original_published_at = entry.published_at
        self.replace_test_storage_bytes(version.storage_key, b"tampered-copy")

        observation = verify_published_entry(entry.id)
        entry.refresh_from_db()

        self.assertEqual(observation.result, "MISMATCH")
        self.assertEqual(entry.published_at, original_published_at)
        self.assertEqual(entry.effective_integrity_status, "MISMATCH")
        self.assertEqual(
            VerificationObservation.objects.filter(published_entry=entry).count(), 1
        )
        # Observation is append-only: a second check adds another row.
        observation2 = verify_published_entry(entry.id)
        self.assertEqual(observation2.result, "MISMATCH")
        self.assertEqual(
            VerificationObservation.objects.filter(published_entry=entry).count(), 2
        )
        self.assertEqual(entry.effective_integrity_status, "MISMATCH")

    def test_intact_documents_verify_without_mutating_entry(self):
        entry, _version = self.make_published_entry()
        original_published_at = entry.published_at
        observation = verify_published_entry(entry.id)
        entry.refresh_from_db()
        self.assertEqual(observation.result, VerificationObservation.Result.VERIFIED)
        self.assertEqual(entry.published_at, original_published_at)
        self.assertEqual(entry.effective_integrity_status, "VERIFIED")
