import hashlib
import secrets
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import storages
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import Building, ManagementMembership
from lamto.audit.models import AuditEvent
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import begin_wallet_registration, register_wallet, utc_rfc3339
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
    fund_balance,
    get_or_create_fund,
    record_fund_source,
    verify_fund_source,
)
from lamto.finance.models import FundEntryVerification, MaintenanceFundEntry


_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-fund-")


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
class FundSourceTests(TestCase):
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

    def document_pair(self, building, uploader, prefix):
        tag = self._unique(prefix)
        document = Document.objects.create(
            building=building, kind=Document.Kind.CONTRACT
        )
        original_bytes = f"{tag}-original-bytes".encode()
        redacted_bytes = f"{tag}-redacted-bytes".encode()
        original_key = f"fund/{tag}-original"
        redacted_key = f"fund/{tag}-redacted"
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

    def setUp(self):
        self.building = Building.objects.create(name=self._unique("Fund Building"))
        self.recorder, self.recorder_account = self.make_signer(
            self.building, None, None, "fund-recorder"
        )
        self.verifier, self.verifier_account = self.make_signer(
            self.building, None, None, "fund-verifier"
        )
        self.accounts = {
            self.recorder.pk: self.recorder_account,
            self.verifier.pk: self.verifier_account,
        }
        self.fund = get_or_create_fund(self.building)
        self.original, self.redacted = self.document_pair(
            self.building, self.recorder.user, "source"
        )

    def sign_source(
        self,
        membership,
        entry_type="INFLOW",
        amount_vnd=50_000_000,
        fund_entry_id=None,
        event_id=None,
        timestamp=None,
        original=None,
        redacted=None,
    ):
        event_id = event_id or ("0x" + secrets.token_hex(32))
        fund_entry_id = fund_entry_id or allocate_fund_entry_id()
        timestamp = timestamp or timezone.now()
        original = original or self.original
        redacted = redacted or self.redacted
        typed = build_fund_source_evidence_typed_data(
            self.fund,
            membership,
            fund_entry_id,
            entry_type,
            amount_vnd,
            original,
            redacted,
            event_id,
            timestamp=timestamp,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[membership.pk].key
        ).signature.hex()
        return signature, event_id, fund_entry_id, timestamp

    def sign_verify(self, entry, membership, event_id=None, timestamp=None):
        event_id = event_id or ("0x" + secrets.token_hex(32))
        timestamp = timestamp or entry.recorded_at
        typed = build_fund_verification_evidence_typed_data(
            entry, membership, event_id, timestamp=timestamp
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[membership.pk].key
        ).signature.hex()
        return signature, event_id, timestamp

    def confirm(self, event):
        event.status = BlockchainOutboxEvent.Status.CONFIRMED
        event.confirmed_at = timezone.now()
        event.save(update_fields=["status", "confirmed_at"])

    def test_recorder_cannot_verify_own_source_and_balance_requires_confirmation(self):
        signature, event_id, fund_entry_id, timestamp = self.sign_source(self.recorder)
        entry = record_fund_source(
            self.fund,
            MaintenanceFundEntry.EntryType.INFLOW,
            50_000_000,
            self.original,
            self.redacted,
            self.recorder,
            signature,
            event_id,
            fund_entry_id=fund_entry_id,
            timestamp=timestamp,
        )
        self.assertEqual(entry.outbox_event.event_type, EvidenceType.FUND_ENTRY)
        self.assertEqual(entry.outbox_event.payload["entry_type"], "INFLOW")
        self.assertNotIn("checker_membership_id", entry.outbox_event.payload)
        self.assertEqual(fund_balance(self.building.pk, verified_only=True), 0)
        self.assertEqual(fund_balance(self.building.pk, verified_only=False), 50_000_000)

        verify_signature, verify_event, verify_ts = self.sign_verify(entry, self.recorder)
        with self.assertRaises(PermissionDenied):
            verify_fund_source(
                entry, self.recorder, verify_signature, verify_event, timestamp=verify_ts
            )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="fund.verify", target_id=str(entry.pk), result="denied"
            ).exists()
        )

        verify_signature, verify_event, verify_ts = self.sign_verify(entry, self.verifier)
        verification = verify_fund_source(
            entry, self.verifier, verify_signature, verify_event, timestamp=verify_ts
        )
        self.assertEqual(verification.outbox_event.payload["checker_membership_id"], self.verifier.pk)
        self.assertEqual(fund_balance(self.building.pk, verified_only=True), 0)
        self.confirm(entry.outbox_event)
        self.confirm(verification.outbox_event)
        self.assertEqual(fund_balance(self.building.pk, verified_only=True), 50_000_000)

    def test_opening_balance_and_insert_only(self):
        original, redacted = self.document_pair(self.building, self.recorder.user, "opening")
        signature, event_id, fund_entry_id, timestamp = self.sign_source(
            self.recorder,
            entry_type=MaintenanceFundEntry.EntryType.OPENING_BALANCE,
            amount_vnd=100_000_000,
            original=original,
            redacted=redacted,
        )
        entry = record_fund_source(
            self.fund,
            MaintenanceFundEntry.EntryType.OPENING_BALANCE,
            100_000_000,
            original,
            redacted,
            self.recorder,
            signature,
            event_id,
            fund_entry_id=fund_entry_id,
            timestamp=timestamp,
        )
        self.assertEqual(entry.outbox_event.payload["entry_type"], "OPENING")
        entry.amount_vnd = 1
        with self.assertRaises(ValueError):
            entry.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaintenanceFundEntry.objects.filter(pk=entry.pk).update(amount_vnd=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaintenanceFundEntry.objects.filter(pk=entry.pk).delete()
        entry.refresh_from_db()

        verify_signature, verify_event, verify_ts = self.sign_verify(entry, self.verifier)
        verification = verify_fund_source(
            entry, self.verifier, verify_signature, verify_event, timestamp=verify_ts
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            FundEntryVerification.objects.filter(pk=verification.pk).update(
                signature="0x" + "ab" * 65
            )

    def test_rejects_non_positive_and_db_blocks_self_verify(self):
        with self.assertRaises(ValidationError):
            build_fund_source_evidence_typed_data(
                self.fund,
                self.recorder,
                allocate_fund_entry_id(),
                MaintenanceFundEntry.EntryType.INFLOW,
                0,
                self.original,
                self.redacted,
                "0x" + secrets.token_hex(32),
            )
        with self.assertRaises(ValidationError):
            build_fund_source_evidence_typed_data(
                self.fund,
                self.recorder,
                allocate_fund_entry_id(),
                MaintenanceFundEntry.EntryType.INFLOW,
                10.5,
                self.original,
                self.redacted,
                "0x" + secrets.token_hex(32),
            )
        signature, event_id, fund_entry_id, timestamp = self.sign_source(self.recorder)
        entry = record_fund_source(
            self.fund,
            MaintenanceFundEntry.EntryType.INFLOW,
            50_000_000,
            self.original,
            self.redacted,
            self.recorder,
            signature,
            event_id,
            fund_entry_id=fund_entry_id,
            timestamp=timestamp,
        )
        # Queue a throwaway FUND_ENTRY outbox with the verifier so the maker-checker trigger
        # can be exercised without going through verify_fund_source.
        from lamto.accounts.models import SignerWallet
        from lamto.evidence.services import queue_signed_event
        from lamto.finance.fund import build_fund_verification_evidence_payload
        from lamto.evidence.canonical import payload_hash
        from eth_account.messages import encode_typed_data
        from eth_account import Account
        from lamto.evidence.signatures import build_evidence_typed_data

        throwaway_id = allocate_fund_entry_id()
        throwaway_event = "0x" + secrets.token_hex(32)
        payload = {
            "fund_entry_id": throwaway_id,
            "entry_type": "INFLOW",
            "amount_vnd": 1,
            "source_document_original_hash": self.original.sha256,
            "source_document_redacted_hash": self.redacted.sha256,
            "maker_membership_id": self.recorder.pk,
            "checker_membership_id": self.verifier.pk,
            "entry_timestamp": utc_rfc3339(timezone.now()),
        }
        previous = "0x" + entry.outbox_event.payload_hash
        typed = build_evidence_typed_data(
            throwaway_event,
            EvidenceType.FUND_ENTRY,
            "0x" + payload_hash(payload),
            previous,
        )
        throwaway_sig = Account.sign_message(
            encode_typed_data(full_message=typed), self.accounts[self.verifier.pk].key
        ).signature.hex()
        with transaction.atomic():
            event = queue_signed_event(
                throwaway_event,
                EvidenceType.FUND_ENTRY,
                payload,
                previous,
                self.verifier,
                throwaway_sig,
            )
        wallet = SignerWallet.objects.get(membership=self.recorder, active=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO finance_fundentryverification
                    (signature, verified_at, entry_id, membership_id, outbox_event_id, wallet_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        "0x" + "cd" * 65,
                        timezone.now().isoformat(),
                        entry.pk,
                        self.recorder.pk,
                        event.pk,
                        wallet.pk,
                    ],
                )
