from django.db import models

from lamto.accounts.models import SignerWallet


class EvidenceType(models.IntegerChoices):
    PROPOSAL_CREATED = 1, "Proposal created"
    BOARD_APPROVAL = 2, "Board approval"
    REPRESENTATIVE_APPROVAL = 3, "Representative approval"
    EMERGENCY_AUTHORIZATION = 4, "Emergency authorization"
    EMERGENCY_OUTCOME = 5, "Emergency outcome"
    WORK_ACCEPTANCE = 6, "Work acceptance"
    PAYMENT_RECORDED = 7, "Payment recorded"
    PAYMENT_VERIFIED = 8, "Payment verified"
    PUBLICATION_SNAPSHOT = 9, "Publication snapshot"
    CORRECTION = 10, "Correction"
    FUND_ENTRY = 11, "Fund entry"


class BlockchainOutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUBMITTED = "SUBMITTED", "Submitted"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FAILED = "FAILED", "Failed"
        MISMATCH = "MISMATCH", "Mismatch"

    event_id = models.CharField(max_length=66, unique=True)
    event_type = models.PositiveSmallIntegerField(choices=EvidenceType.choices)
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)
    previous_hash = models.CharField(max_length=66)
    signature = models.CharField(max_length=132)
    signer_wallet = models.ForeignKey(SignerWallet, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    transaction_hash = models.CharField(max_length=66, blank=True)
    receipt_status = models.IntegerField(null=True, blank=True)
    receipt = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    chain_confirmed_block = models.BigIntegerField(null=True, blank=True)
    chain_block_timestamp = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_id__regex=r"^0x[0-9a-f]{64}$"),
                name="outbox_event_id_bytes32",
            ),
            models.CheckConstraint(
                condition=models.Q(payload_hash__regex=r"^[0-9a-f]{64}$"),
                name="outbox_payload_hash_sha256",
            ),
            models.CheckConstraint(
                condition=models.Q(previous_hash__regex=r"^0x[0-9a-f]{64}$"),
                name="outbox_previous_hash_bytes32",
            ),
            models.CheckConstraint(
                condition=models.Q(event_type__gte=1, event_type__lte=11),
                name="outbox_known_event_type",
            ),
        ]
