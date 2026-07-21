import hashlib
from pathlib import Path
import secrets
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import storages
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import Building, ManagementMembership, Unit
from lamto.audit.models import AuditEvent
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.acceptance import accept_work, build_acceptance_evidence_typed_data
from lamto.finance.fund import fund_balance, get_or_create_fund, record_fund_source, verify_fund_source
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
)
from lamto.finance.models import (
    MaintenanceFundEntry,
    PublicationGateFailure,
    PublicationSnapshot,
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
    WorkUpdate,
    WorkUpdateEvidence,
)
from lamto.maintenance.workorders import complete_work_order, start_work_order


_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-pub-")


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
class PublicationTests(TestCase):
    def _unique(self, base):
        n = getattr(self, "_fixture_seq", 0) + 1
        self._fixture_seq = n
        return f"{base}-{n}"

    def make_signer(self, building, role, access, suffix):
        suffix = self._unique(suffix)
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        membership = ManagementMembership.objects.create(user=user, building=building)
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

    def make_ready_proposal_and_publisher(self):
        tag = self._unique("pub")
        building = Building.objects.create(name=f"Publication Building {tag}")
        location = BuildingLocation.objects.create(building=building, name="Lobby")
        unit = Unit.objects.create(building=building, label="A-1")
        operator, operator_account = self.make_signer(
            building, None, None, "operator"
        )
        maintenance_user = get_user_model().objects.create_user(
            email=f"maint-{tag}@example.test", password="secret", display_name="Maint"
        )
        ManagementMembership.objects.create(user=maintenance_user, building=building)
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

        board_actor, board_account = self.make_signer(
            building, None, None, "board-actor"
        )
        self.accounts = {
            operator.pk: operator_account,
            board_actor.pk: board_account,
        }

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
            board_actor,
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
            board_actor,
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
            building, None, None, "pay-recorder"
        )
        # Same user as board_acceptor is allowed for payment record, but use distinct for dual-control clarity.
        # Actually we can use board_acceptor as recorder. For publisher exclusion we need distinct publisher.
        payment_verifier, payment_verifier_account = self.make_signer(
            building, None, None, "pay-verifier"
        )
        publisher, publisher_account = self.make_signer(
            building, None, None, "publisher"
        )
        # Publisher may equal payment verifier - grant both on publisher as alternative path tested separately.
        self.accounts[payment_recorder.pk] = payment_recorder_account
        self.accounts[payment_verifier.pk] = payment_verifier_account
        self.accounts[publisher.pk] = publisher_account

        proof_original, proof_redacted = self.document_pair(
            building, Document.Kind.PAYMENT_PROOF, payment_recorder.user, "proof"
        )
        payment_id = allocate_payment_id()
        payment_event = "0x" + secrets.token_hex(32)
        completed_at = timezone.now()
        bank_ref = f"BANK-PUB-{tag.upper()}"
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

        # Confirm all prerequisite outbox events.
        self.confirm_chain(
            version.outbox_event,
            acceptance.outbox_event,
            payment.outbox_event,
            verification.outbox_event,
        )

        publication_id = allocate_publication_id()
        pub_event = "0x" + secrets.token_hex(32)
        # Build typed data via the service helper; prepare will recompute hashes.
        # We need prerequisite hashes and resident payload matching prepare_publication.
        from lamto.finance.publication import (
            _collect_document_checks,
            _resident_payload,
        )

        # Seed fund so balance can absorb outflow.
        fund = get_or_create_fund(building)
        fund_recorder, fund_recorder_account = self.make_signer(
            building, None, None, "fund-rec"
        )
        fund_verifier, fund_verifier_account = self.make_signer(
            building, None, None, "fund-ver"
        )
        self.accounts[fund_recorder.pk] = fund_recorder_account
        self.accounts[fund_verifier.pk] = fund_verifier_account
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

        proposal.refresh_from_db()
        version = proposal.current_version
        checks = _collect_document_checks(proposal, version, acceptance, payment, verification)
        document_hashes = sorted({doc.sha256 for doc, expected, _ in checks})
        # Ensure stream matches (already stored).
        for doc, expected, gate in checks:
            assert doc.sha256 == expected
        resident_payload = _resident_payload(
            proposal, version, acceptance, payment, verification, document_hashes
        )
        prerequisite_event_hashes = [
            version.outbox_event.payload_hash,
            acceptance.outbox_event.payload_hash,
            payment.outbox_event.payload_hash,
            verification.outbox_event.payload_hash,
        ]
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
        return (
            proposal,
            publisher,
            pub_sig,
            pub_event,
            publication_id,
            pub_ts,
            payment_recorder,
            board_actor,
            payment_verifier,
            building,
        )

    def test_publication_waits_for_its_own_chain_confirmation_then_posts_once(self):
        (
            proposal,
            publisher,
            signature,
            event_id,
            publication_id,
            pub_ts,
            _payment_recorder,
            _board_actor,
            _payment_verifier,
            building,
        ) = self.make_ready_proposal_and_publisher()
        snapshot = prepare_publication(
            proposal,
            publisher,
            signature,
            event_id,
            publication_id=publication_id,
            timestamp=pub_ts,
        )

        self.assertFalse(PublishedLedgerEntry.objects.filter(proposal=proposal).exists())
        self.assertFalse(MaintenanceFundEntry.objects.filter(proposal=proposal).exists())
        self.assertEqual(snapshot.outbox_event.event_type, EvidenceType.PUBLICATION_SNAPSHOT)
        self.assertEqual(snapshot.outbox_event.status, BlockchainOutboxEvent.Status.PENDING)
        with self.assertRaises(ValidationError):
            finalize_publication(snapshot.id)

        balance_before = fund_balance(building.pk, verified_only=True)
        snapshot.outbox_event.status = "CONFIRMED"
        snapshot.outbox_event.confirmed_at = timezone.now()
        snapshot.outbox_event.save(update_fields=["status", "confirmed_at"])
        first = finalize_publication(snapshot.id)
        second = finalize_publication(snapshot.id)

        self.assertEqual(first.id, second.id)
        self.assertEqual(MaintenanceFundEntry.objects.filter(proposal=proposal).count(), 1)
        outflow = MaintenanceFundEntry.objects.get(proposal=proposal)
        self.assertEqual(outflow.entry_type, MaintenanceFundEntry.EntryType.OUTFLOW)
        self.assertEqual(outflow.amount_vnd, -18_500_000)
        self.assertEqual(
            fund_balance(building.pk, verified_only=True), balance_before - 18_500_000
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="publication.finalize", target_id=str(first.pk), result="accepted"
            ).exists()
        )

    def test_publisher_dual_control_blocks_creator_and_recorder(self):
        (
            proposal,
            publisher,
            signature,
            event_id,
            publication_id,
            pub_ts,
            payment_recorder,
            board_actor,
            payment_verifier,
            building,
        ) = self.make_ready_proposal_and_publisher()

        # Payment recorder cannot publish.
        # Need a signature from payment_recorder wallet — rebuild typed data for them.
        from lamto.finance.publication import (
            _collect_document_checks,
            _resident_payload,
        )

        proposal.refresh_from_db()
        version = proposal.current_version
        acceptance = proposal.work_order.acceptance
        payment = acceptance.payment
        verification = payment.verification
        checks = _collect_document_checks(proposal, version, acceptance, payment, verification)
        document_hashes = sorted({doc.sha256 for doc, _, _ in checks})
        resident_payload = _resident_payload(
            proposal, version, acceptance, payment, verification, document_hashes
        )
        prerequisite_event_hashes = [
            version.outbox_event.payload_hash,
            acceptance.outbox_event.payload_hash,
            payment.outbox_event.payload_hash,
            verification.outbox_event.payload_hash,
        ]
        pub_id = allocate_publication_id()
        pub_event = "0x" + secrets.token_hex(32)
        pub_ts = timezone.now()
        previous_hash = "0x" + verification.outbox_event.payload_hash
        typed = build_publication_evidence_typed_data(
            proposal,
            payment_recorder,
            pub_id,
            prerequisite_event_hashes,
            resident_payload,
            document_hashes,
            pub_event,
            timestamp=pub_ts,
            previous_hash=previous_hash,
        )
        bad_sig = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[payment_recorder.pk].key
        ).signature.hex()
        with self.assertRaises(PermissionDenied):
            prepare_publication(
                proposal,
                payment_recorder,
                bad_sig,
                pub_event,
                publication_id=pub_id,
                timestamp=pub_ts,
            )
        self.assertTrue(
            PublicationGateFailure.objects.filter(
                proposal=proposal, gate_code="PUBLISHER_INELIGIBLE"
            ).exists()
        )

        # Payment verifier may publish.
        pub_id = allocate_publication_id()
        pub_event = "0x" + secrets.token_hex(32)
        typed = build_publication_evidence_typed_data(
            proposal,
            payment_verifier,
            pub_id,
            prerequisite_event_hashes,
            resident_payload,
            document_hashes,
            pub_event,
            timestamp=pub_ts,
            previous_hash=previous_hash,
        )
        good_sig = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[payment_verifier.pk].key
        ).signature.hex()
        snapshot = prepare_publication(
            proposal,
            payment_verifier,
            good_sig,
            pub_event,
            publication_id=pub_id,
            timestamp=pub_ts,
        )
        self.assertEqual(snapshot.publisher_id, payment_verifier.pk)
        snapshot.resident_payload_hash = "0" * 64
        with self.assertRaises(ValueError):
            snapshot.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PublicationSnapshot.objects.filter(pk=snapshot.pk).update(
                resident_payload_hash="0" * 64
            )

    def test_db_trigger_rejects_ineligible_publisher_insert(self):
        (
            proposal,
            publisher,
            signature,
            event_id,
            publication_id,
            pub_ts,
            payment_recorder,
            _board_actor,
            _payment_verifier,
            _building,
        ) = self.make_ready_proposal_and_publisher()
        from lamto.accounts.models import SignerWallet

        # Queue a throwaway publication snapshot event with the eligible publisher, then try to
        # attach an ineligible publisher row via SQL (bypassing the application service).
        from lamto.accounts.models import SignerWallet
        from lamto.evidence.services import queue_signed_event
        from lamto.evidence.canonical import payload_hash
        from eth_account.messages import encode_typed_data
        from eth_account import Account
        from lamto.evidence.signatures import build_evidence_typed_data
        from lamto.evidence.services import utc_rfc3339

        throwaway_event = "0x" + secrets.token_hex(32)
        throwaway_pub_id = allocate_publication_id()
        payload = {
            "publication_id": throwaway_pub_id,
            "prerequisite_event_hashes": ["a" * 64],
            "resident_payload_hash": "b" * 64,
            "document_hashes": ["c" * 64],
            "publication_timestamp": utc_rfc3339(timezone.now()),
        }
        previous = "0x" + "00" * 32
        typed = build_evidence_typed_data(
            throwaway_event,
            EvidenceType.PUBLICATION_SNAPSHOT,
            "0x" + payload_hash(payload),
            previous,
        )
        throwaway_sig = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[publisher.pk].key
        ).signature.hex()
        with transaction.atomic():
            event = queue_signed_event(
                throwaway_event,
                EvidenceType.PUBLICATION_SNAPSHOT,
                payload,
                previous,
                publisher,
                throwaway_sig,
            )
        wallet = SignerWallet.objects.get(membership=payment_recorder, active=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO finance_publicationsnapshot
                    (resident_payload, resident_payload_hash, signature, prepared_at,
                     outbox_event_id, proposal_id, publisher_id, wallet_id)
                    VALUES (%s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        "{}",
                        "c" * 64,
                        "0x" + "cd" * 65,
                        timezone.now().isoformat(),
                        event.pk,
                        proposal.pk,
                        payment_recorder.pk,
                        wallet.pk,
                    ],
                )

    def test_document_hash_mismatch_freezes_with_gate_failure(self):
        (
            proposal,
            publisher,
            signature,
            event_id,
            publication_id,
            pub_ts,
            _payment_recorder,
            _board_acceptor,
            _payment_verifier,
            _building,
        ) = self.make_ready_proposal_and_publisher()
        # Tamper stored bytes for payment proof.
        payment = proposal.work_order.acceptance.payment
        storage = storages["private"]
        with storage.open(payment.proof_original.storage_key, "wb") as handle:
            handle.write(b"tampered-payment-proof-bytes")
        with self.assertRaises(ValidationError):
            prepare_publication(
                proposal,
                publisher,
                signature,
                event_id,
                publication_id=publication_id,
                timestamp=pub_ts,
            )
        self.assertTrue(
            PublicationGateFailure.objects.filter(
                proposal=proposal, gate_code__contains="MISMATCH"
            ).exists()
        )
        self.assertFalse(PublicationSnapshot.objects.filter(proposal=proposal).exists())
