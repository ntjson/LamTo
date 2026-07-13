from django.core.exceptions import ValidationError
from django.db import models

from lamto.accounts.models import OrganizationMembership, SignerWallet
from lamto.documents.models import DocumentVersion
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.maintenance.models import WorkOrder


class InsertOnlyModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Proposal versions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Proposal versions are append-only.")


class Proposal(models.Model):
    class Mode(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        EMERGENCY = "EMERGENCY", "Emergency"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        NORMAL_AUTHORIZED = "NORMAL_AUTHORIZED", "Normal authorized"
        EMERGENCY_EVIDENCE = "EMERGENCY_EVIDENCE", "Emergency evidence"
        REJECTED = "REJECTED", "Rejected"

    work_order = models.OneToOneField(WorkOrder, on_delete=models.PROTECT, related_name="proposal")
    creator_membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    current_version = models.ForeignKey(
        "ProposalVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous_mode = type(self).objects.filter(pk=self.pk).values_list("mode", flat=True).first()
            if previous_mode is not None and previous_mode != self.mode:
                raise ValueError("Proposal mode is immutable.")
        return super().save(*args, **kwargs)


class ProposalVersion(InsertOnlyModel):
    proposal = models.ForeignKey(Proposal, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    amount_vnd = models.BigIntegerField()
    contractor_name = models.CharField(max_length=255)
    fund_code = models.CharField(max_length=32, default="MAINTENANCE")
    purpose = models.TextField()
    snapshot = models.JSONField()
    snapshot_hash = models.CharField(max_length=64)
    creator_membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT)
    creator_wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    creator_signature = models.CharField(max_length=132)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent, on_delete=models.PROTECT, related_name="proposal_version"
    )
    quotations = models.ManyToManyField(
        DocumentVersion, through="ProposalDocument", related_name="proposal_versions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["proposal", "number"], name="proposal_version_once"),
            models.CheckConstraint(condition=models.Q(amount_vnd__gt=0), name="proposal_amount_positive"),
        ]


class ProposalDocument(models.Model):
    proposal_version = models.ForeignKey(ProposalVersion, on_delete=models.PROTECT)
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Proposal quotation links are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Proposal quotation links are append-only.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proposal_version", "document_version"], name="proposal_document_once"
            )
        ]
