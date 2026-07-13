from django.db import models

from lamto.accounts.models import OrganizationMembership, SignerWallet
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.maintenance.models import WorkOrder

from .proposals import InsertOnlyModel


class EmergencyAuthorization(InsertOnlyModel):
    work_order = models.OneToOneField(
        WorkOrder, on_delete=models.PROTECT, related_name="emergency_authorization"
    )
    reason = models.TextField()
    estimate_vnd = models.BigIntegerField(null=True, blank=True)
    membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT)
    wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132)
    authorized_at = models.DateTimeField()
    ratification_deadline = models.DateTimeField()
    drill = models.BooleanField()
    label = models.CharField(max_length=32)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        on_delete=models.PROTECT,
        related_name="emergency_authorization",
    )

    @property
    def created_at(self):
        return self.authorized_at

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estimate_vnd__isnull=True) | models.Q(estimate_vnd__gt=0),
                name="emergency_estimate_positive",
            ),
            # Exact 24h equality is enforced in finance.0006 via PostgreSQL interval CHECK;
            # Django state keeps the weaker F-expression form for cross-backend metadata.
            models.CheckConstraint(
                condition=models.Q(ratification_deadline__gt=models.F("authorized_at")),
                name="emergency_deadline_exact_24h",
            ),
        ]


class EmergencyRatification(InsertOnlyModel):
    class Decision(models.TextChoices):
        RATIFY = "RATIFY", "Ratify"
        REJECT = "REJECT", "Reject"
        OVERDUE = "OVERDUE", "Overdue"

    class Outcome(models.TextChoices):
        RATIFIED = "RATIFIED", "Ratified"
        REJECTED = "REJECTED", "Rejected"
        OVERDUE = "OVERDUE", "Overdue"

    authorization = models.OneToOneField(
        EmergencyAuthorization, on_delete=models.PROTECT, related_name="ratification"
    )
    decision = models.CharField(max_length=8, choices=Decision.choices)
    outcome = models.CharField(max_length=8, choices=Outcome.choices)
    reason = models.TextField()
    membership = models.ForeignKey(
        OrganizationMembership, null=True, blank=True, on_delete=models.PROTECT
    )
    wallet = models.ForeignKey(SignerWallet, null=True, blank=True, on_delete=models.PROTECT)
    signature = models.CharField(max_length=132, blank=True)
    outbox_event = models.OneToOneField(
        BlockchainOutboxEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="emergency_ratification",
    )
    decided_at = models.DateTimeField()
    label = models.CharField(max_length=32)

    @property
    def created_at(self):
        return self.decided_at

    @property
    def result(self):
        return self.outcome

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        decision="OVERDUE",
                        outcome="OVERDUE",
                        membership__isnull=True,
                        wallet__isnull=True,
                        outbox_event__isnull=True,
                        signature="",
                    )
                    | (
                        models.Q(
                            membership__isnull=False,
                            wallet__isnull=False,
                            outbox_event__isnull=False,
                        )
                        & ~models.Q(signature="")
                        & (
                            models.Q(decision="RATIFY", outcome="RATIFIED")
                            | models.Q(decision="REJECT", outcome="REJECTED")
                        )
                    )
                ),
                name="emergency_ratification_provenance",
            )
        ]
