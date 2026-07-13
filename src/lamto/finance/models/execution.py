from django.db import models

from lamto.accounts.models import OrganizationMembership, SignerWallet
from lamto.documents.models import DocumentVersion
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.maintenance.models import WorkOrder

from .proposals import InsertOnlyModel


class AcceptanceRecord(InsertOnlyModel):
    work_order = models.OneToOneField(
        WorkOrder, on_delete=models.PROTECT, related_name="acceptance"
    )
    actual_cost_vnd = models.BigIntegerField()
    invoice_original = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    invoice_redacted = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    acceptance_original = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    acceptance_redacted = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT)
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="acceptance_record",
    )
    accepted_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.accepted_at

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actual_cost_vnd__gt=0),
                name="acceptance_actual_cost_positive",
            ),
        ]


class PaymentEvidence(InsertOnlyModel):
    class ExternalStatus(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        REVERSED = "REVERSED", "Reversed"

    acceptance = models.OneToOneField(
        AcceptanceRecord, on_delete=models.PROTECT, related_name="payment"
    )
    bank_reference = models.CharField(max_length=128, unique=True)
    amount_vnd = models.BigIntegerField()
    external_status = models.CharField(max_length=16, choices=ExternalStatus.choices)
    completed_at = models.DateTimeField()
    proof_original = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    proof_redacted = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    recorder = models.ForeignKey(
        OrganizationMembership,
        on_delete=models.PROTECT,
        related_name="recorded_payments",
    )
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="payment_evidence",
    )
    recorded_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.recorded_at

    @property
    def membership(self):
        return self.recorder

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_vnd__gt=0),
                name="payment_amount_positive",
            ),
        ]


class PaymentVerification(InsertOnlyModel):
    class Decision(models.TextChoices):
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"

    payment = models.OneToOneField(
        PaymentEvidence, on_delete=models.PROTECT, related_name="verification"
    )
    membership = models.ForeignKey(
        OrganizationMembership,
        on_delete=models.PROTECT,
        related_name="payment_verifications",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.TextField()
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="payment_verification",
    )
    verified_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.verified_at

    @property
    def verifier(self):
        return self.membership
