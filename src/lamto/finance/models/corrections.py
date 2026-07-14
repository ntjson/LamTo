from django.db import models

from lamto.accounts.models import OrganizationMembership, SignerWallet
from lamto.documents.models import DocumentVersion
from lamto.evidence.models import BlockchainOutboxEvent, is_settled

from .ledger import PublishedLedgerEntry
from .proposals import InsertOnlyModel


class Correction(InsertOnlyModel):
    original_entry = models.ForeignKey(
        PublishedLedgerEntry,
        on_delete=models.PROTECT,
        related_name="corrections",
    )
    operator = models.ForeignKey(
        OrganizationMembership,
        on_delete=models.PROTECT,
        related_name="created_corrections",
    )
    reason = models.TextField()
    replacement_payload = models.JSONField()
    replacement_payload_hash = models.CharField(max_length=64)
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="correction",
    )
    created_at = models.DateTimeField()

    @property
    def is_resident_visible(self):
        try:
            snapshot = self.publication_snapshot
        except CorrectionPublicationSnapshot.DoesNotExist:
            return False
        if not is_settled(snapshot.outbox_event.status):
            return False
        if self.amount_changed and not self.fund_entries.filter(
            entry_type__in=["REVERSAL", "REPLACEMENT"]
        ).exists():
            return False
        return self.board_and_rep_approved

    @property
    def amount_changed(self):
        original = self.original_entry.actual_cost_vnd
        replacement = self.replacement_payload.get("actual_cost_vnd")
        return type(replacement) is int and replacement != original

    @property
    def board_and_rep_approved(self):
        decisions = {
            row.stage: row.decision for row in self.decisions.all()
        }
        return (
            decisions.get(CorrectionDecision.Stage.BOARD)
            == CorrectionDecision.Decision.APPROVE
            and decisions.get(CorrectionDecision.Stage.RESIDENT_REP)
            == CorrectionDecision.Decision.APPROVE
        )

    @property
    def status(self):
        decisions = list(self.decisions.all())
        if any(d.decision == CorrectionDecision.Decision.REJECT for d in decisions):
            return "REJECTED"
        if self.is_resident_visible:
            return "PUBLISHED"
        if self.board_and_rep_approved:
            try:
                snap = self.publication_snapshot
            except CorrectionPublicationSnapshot.DoesNotExist:
                return "APPROVED"
            if is_settled(snap.outbox_event.status):
                return "APPROVED"
            return "PUBLICATION_PENDING"
        return "PENDING"


class CorrectionDocument(InsertOnlyModel):
    correction = models.ForeignKey(
        Correction, on_delete=models.PROTECT, related_name="documents"
    )
    version = models.ForeignKey(
        DocumentVersion, on_delete=models.PROTECT, related_name="+"
    )
    role = models.CharField(max_length=32, default="EVIDENCE")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["correction", "version"],
                name="correction_document_once",
            )
        ]


class CorrectionDecision(InsertOnlyModel):
    class Stage(models.TextChoices):
        BOARD = "BOARD", "Management Board"
        RESIDENT_REP = "RESIDENT_REP", "Resident representative"

    class Decision(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"

    correction = models.ForeignKey(
        Correction, on_delete=models.PROTECT, related_name="decisions"
    )
    stage = models.CharField(max_length=16, choices=Stage.choices)
    decision = models.CharField(max_length=8, choices=Decision.choices)
    reason = models.TextField()
    membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT)
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="correction_decision",
    )
    decided_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.decided_at

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["correction", "stage"],
                name="correction_decision_once_per_stage",
            )
        ]


class CorrectionPublicationSnapshot(InsertOnlyModel):
    correction = models.OneToOneField(
        Correction, on_delete=models.PROTECT, related_name="publication_snapshot"
    )
    resident_payload = models.JSONField()
    resident_payload_hash = models.CharField(max_length=64)
    publisher = models.ForeignKey(
        OrganizationMembership,
        on_delete=models.PROTECT,
        related_name="correction_publication_snapshots",
    )
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="correction_publication_snapshot",
    )
    prepared_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.prepared_at

    @property
    def status(self):
        return self.outbox_event.status


class VerificationObservation(InsertOnlyModel):
    class Result(models.TextChoices):
        VERIFIED = "VERIFIED", "Verified"
        MISMATCH = "MISMATCH", "Mismatch"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"

    published_entry = models.ForeignKey(
        PublishedLedgerEntry,
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
