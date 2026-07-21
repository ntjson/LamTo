import hashlib
from pathlib import Path
import secrets
import tempfile
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.storage import storages
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import Building, ManagementMembership, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.acceptance import accept_work, build_acceptance_evidence_typed_data
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
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

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

    def make_published_entry(self):
        tag = self._unique("int")
        building = Building.objects.create(name=f"Integrity Building {tag}")
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
        payment_verifier, payment_verifier_account = self.make_signer(
            building, None, None, "pay-verifier"
        )
        publisher, publisher_account = self.make_signer(
            building, None, None, "publisher"
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
            acceptance.outbox_event,
            payment.outbox_event,
            verification.outbox_event,
        )

        fund = get_or_create_fund(building)
        fund_recorder, fund_recorder_account = self.make_signer(
            building, None, None, "fund-rec"
        )
        fund_verifier, fund_verifier_account = self.make_signer(
            building, None, None, "fund-ver"
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
        prerequisite_event_hashes = [
            version.outbox_event.payload_hash,
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


    def test_verify_published_entry_routes_to_database_alias(self):
        entry, _version = self.make_published_entry()
        aliases = []
        real_ple = PublishedLedgerEntry.objects.using
        real_vo = VerificationObservation.objects.using

        def ple_using(alias):
            aliases.append(("PublishedLedgerEntry", alias))
            return real_ple(alias)

        def vo_using(alias):
            aliases.append(("VerificationObservation", alias))
            return real_vo(alias)

        with (
            patch.object(PublishedLedgerEntry.objects, "using", side_effect=ple_using),
            patch.object(VerificationObservation.objects, "using", side_effect=vo_using),
        ):
            observation = verify_published_entry(entry.id, using="default")

        self.assertEqual(observation.result, VerificationObservation.Result.VERIFIED)
        self.assertIn(("PublishedLedgerEntry", "default"), aliases)
        self.assertIn(("VerificationObservation", "default"), aliases)

    def test_verify_integrity_command_passes_database_alias(self):
        entry, _version = self.make_published_entry()
        mock_obs = MagicMock()
        mock_obs.pk = 12345
        mock_obs.result = VerificationObservation.Result.VERIFIED
        mock_obs.observed_at = timezone.now()
        with patch(
            "lamto.finance.management.commands.verify_integrity.verify_published_entry",
            return_value=mock_obs,
        ) as mock_verify:
            out = StringIO()
            call_command(
                "verify_integrity",
                f"--entry-id={entry.pk}",
                "--database=default",
                stdout=out,
            )
            mock_verify.assert_called_once_with(entry.pk, using="default")
            self.assertIn(str(entry.pk), out.getvalue())


_ANCHOR_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-integrity-anchor-")


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _ANCHOR_TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _ANCHOR_TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class AnchoringAwareIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="Integrity Anchor Building", create_sample_report=False
        )
        driver = PilotDomainDriver(cls.seed)
        driver.prepare_local_normal_work(None)
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()
        driver.sign_publication_snapshot()
        driver.confirm_all_chain_events()
        cls.entry = PublishedLedgerEntry.objects.get(
            case__building=cls.seed.building
        )

    def test_disabled_mode_skips_chain_checks_without_faking(self):
        with override_settings(EVIDENCE_ANCHORING_BACKEND="disabled"):
            observation = verify_published_entry(self.entry.pk)

        self.assertEqual(
            observation.result, VerificationObservation.Result.VERIFIED
        )
        self.assertEqual(observation.details.get("anchoring_backend"), "disabled")
        results = {check["result"] for check in observation.details["chain_checks"]}
        self.assertEqual(results, {"SKIPPED_ANCHORING_DISABLED"})

    def test_local_events_are_skipped_not_faked_in_besu_mode(self):
        snapshot_event_id = self.entry.snapshot.outbox_event_id
        BlockchainOutboxEvent.objects.filter(pk=snapshot_event_id).update(
            status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None
        )

        observation = verify_published_entry(self.entry.pk)

        by_event = {
            check["event_id"]: check["result"]
            for check in observation.details["chain_checks"]
        }
        self.assertEqual(
            by_event[self.entry.snapshot.outbox_event.event_id], "SKIPPED_LOCAL"
        )
        # Documents verified and every event settled: VERIFIED even though the
        # chain is unreachable in the test environment.
        self.assertEqual(
            observation.result, VerificationObservation.Result.VERIFIED
        )

    def test_unsettled_event_downgrades_to_unavailable(self):
        snapshot_event_id = self.entry.snapshot.outbox_event_id
        BlockchainOutboxEvent.objects.filter(pk=snapshot_event_id).update(
            status=BlockchainOutboxEvent.Status.PENDING, confirmed_at=None
        )

        with override_settings(EVIDENCE_ANCHORING_BACKEND="disabled"):
            observation = verify_published_entry(self.entry.pk)

        self.assertEqual(
            observation.result, VerificationObservation.Result.UNAVAILABLE
        )
