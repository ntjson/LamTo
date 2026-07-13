from django.db import models

from lamto.accounts.models import OrganizationMembership, SignerWallet
from lamto.evidence.models import BlockchainOutboxEvent

from .proposals import InsertOnlyModel, ProposalVersion


class ApprovalDecision(InsertOnlyModel):
    class Stage(models.TextChoices):
        BOARD = "BOARD", "Management Board"
        RESIDENT_REP = "RESIDENT_REP", "Resident representative"

    class Decision(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"

    version = models.ForeignKey(
        ProposalVersion, on_delete=models.PROTECT, related_name="approval_decisions"
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
        related_name="approval_decision",
    )
    decided_at = models.DateTimeField()

    @property
    def created_at(self):
        return self.decided_at

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Approval decisions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Approval decisions are append-only.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "stage"], name="approval_decision_once_per_stage"
            )
        ]
