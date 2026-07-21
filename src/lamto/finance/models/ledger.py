from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from lamto.accounts.models import Building, ManagementMembership, SignerWallet
from lamto.documents.models import DocumentVersion
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
from lamto.maintenance.models import MaintenanceCase, WorkOrder

from .execution import PaymentEvidence
from .proposals import InsertOnlyModel, Proposal


class MaintenanceFund(models.Model):
    building = models.OneToOneField(
        Building, on_delete=models.PROTECT, related_name="maintenance_fund"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class MaintenanceFundEntry(InsertOnlyModel):
    class EntryType(models.TextChoices):
        OPENING_BALANCE = "OPENING_BALANCE", "Opening balance"
        INFLOW = "INFLOW", "Inflow"
        OUTFLOW = "OUTFLOW", "Outflow"
        REVERSAL = "REVERSAL", "Reversal"
        REPLACEMENT = "REPLACEMENT", "Replacement"

    fund = models.ForeignKey(
        MaintenanceFund, on_delete=models.PROTECT, related_name="entries"
    )
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    amount_vnd = models.BigIntegerField()
    evidence_original = models.ForeignKey(
        DocumentVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    evidence_redacted = models.ForeignKey(
        DocumentVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    evidence_original_hash = models.CharField(max_length=64, blank=True)
    evidence_redacted_hash = models.CharField(max_length=64, blank=True)
    recorder = models.ForeignKey(
        ManagementMembership,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="recorded_fund_entries",
    )
    wallet = models.ForeignKey(
        SignerWallet, null=True, blank=True, on_delete=models.PROTECT
    )
    signature = models.CharField(max_length=132, blank=True)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fund_entry",
    )
    proposal = models.ForeignKey(
        Proposal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fund_entries",
    )
    publication = models.ForeignKey(
        "PublicationSnapshot",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fund_entries",
    )
    source_key = models.CharField(max_length=128, unique=True)
    recorded_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.recorded_at

    def save(self, *args, **kwargs):
        if self.recorded_at > timezone.now():
            raise ValidationError(
                {"recorded_at": "Fund entries cannot be future-dated."}
            )
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        entry_type__in=["OPENING_BALANCE", "INFLOW"],
                        amount_vnd__gt=0,
                    )
                    | models.Q(entry_type="OUTFLOW", amount_vnd__lt=0)
                    | (
                        models.Q(entry_type__in=["REVERSAL", "REPLACEMENT"])
                        & ~models.Q(amount_vnd=0)
                    )
                ),
                name="fund_entry_amount_sign",
            ),
        ]


class FundEntryVerification(InsertOnlyModel):
    entry = models.OneToOneField(
        MaintenanceFundEntry, on_delete=models.PROTECT, related_name="verification"
    )
    membership = models.ForeignKey(
        ManagementMembership,
        on_delete=models.PROTECT,
        related_name="fund_verifications",
    )
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="fund_entry_verification",
    )
    verified_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.verified_at

    @property
    def verifier(self):
        return self.membership


class VerificationObservation(InsertOnlyModel):
    class Result(models.TextChoices):
        VERIFIED = "VERIFIED", "Verified"
        MISMATCH = "MISMATCH", "Mismatch"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"

    published_entry = models.ForeignKey(
        "PublishedLedgerEntry",
        on_delete=models.PROTECT,
        related_name="verification_observations",
    )
    result = models.CharField(max_length=16, choices=Result.choices)
    checked_document_hashes = models.JSONField(default=list)
    checked_chain_event_ids = models.JSONField(default=list)
    details = models.JSONField(default=dict)
    observed_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.observed_at


class PublicationSnapshot(InsertOnlyModel):
    proposal = models.OneToOneField(
        Proposal, on_delete=models.PROTECT, related_name="publication_snapshot"
    )
    resident_payload = models.JSONField()
    resident_payload_hash = models.CharField(max_length=64)
    publisher = models.ForeignKey(
        ManagementMembership,
        on_delete=models.PROTECT,
        related_name="publication_snapshots",
    )
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="publication_snapshot",
    )
    prepared_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.prepared_at

    @property
    def status(self):
        return self.outbox_event.status

    @property
    def anchoring_backend(self) -> str:
        """Backend in force at settlement, derived from the terminal outbox status.

        LOCAL and CONFIRMED are terminal, and confirmed_at survives the only
        post-settlement transition (CONFIRMED -> MISMATCH), so this is exact.
        Empty string while unsettled.
        """
        status = self.outbox_event.status
        if status == BlockchainOutboxEvent.Status.LOCAL:
            return "disabled"
        if (
            status == BlockchainOutboxEvent.Status.CONFIRMED
            or self.outbox_event.confirmed_at is not None
        ):
            return "besu"
        return ""

    @property
    def settled_evidence_level(self) -> str:
        """Evidence level at settlement (spec 5.2); empty string while unsettled."""
        status = self.outbox_event.status
        if status == BlockchainOutboxEvent.Status.LOCAL:
            return EvidenceLevel.LOCAL_SIGNED
        if (
            status == BlockchainOutboxEvent.Status.CONFIRMED
            or self.outbox_event.confirmed_at is not None
        ):
            return EvidenceLevel.CHAIN_CONFIRMED
        return ""


class PublicationGateFailure(InsertOnlyModel):
    class Severity(models.TextChoices):
        BLOCKING = "BLOCKING", "Blocking"
        WARNING = "WARNING", "Warning"

    proposal = models.ForeignKey(
        Proposal, on_delete=models.PROTECT, related_name="publication_gate_failures"
    )
    gate_code = models.CharField(max_length=64)
    expected_hash = models.CharField(max_length=64, blank=True)
    actual_hash = models.CharField(max_length=64, blank=True)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.BLOCKING
    )
    actor = models.ForeignKey(
        ManagementMembership,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)


class PublishedLedgerEntry(InsertOnlyModel):
    snapshot = models.OneToOneField(
        PublicationSnapshot, on_delete=models.PROTECT, related_name="ledger_entry"
    )
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT)
    case = models.ForeignKey(MaintenanceCase, on_delete=models.PROTECT)
    proposal = models.OneToOneField(
        Proposal, on_delete=models.PROTECT, related_name="published_ledger_entry"
    )
    payment = models.ForeignKey(PaymentEvidence, on_delete=models.PROTECT)
    actual_cost_vnd = models.BigIntegerField()
    contractor_name = models.CharField(max_length=255)
    published_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.published_at

    @property
    def effective_integrity_status(self):
        latest = (
            self.verification_observations.order_by("-observed_at", "-pk").first()
        )
        if latest is None:
            return "UNCHECKED"
        return latest.result

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actual_cost_vnd__gt=0),
                name="published_ledger_actual_cost_positive",
            ),
        ]
