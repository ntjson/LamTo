from django.conf import settings
from django.db import models


class NotificationPreference(models.Model):
    """Per-user email preference for a material event code.

    Required in-app notices cannot be disabled; only email may be opted out.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    event_code = models.CharField(max_length=64)
    email_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event_code"],
                name="notification_preference_once",
            )
        ]


class NotificationDelivery(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In-app"
        EMAIL = "EMAIL", "Email"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        AVAILABLE = "AVAILABLE", "Available"  # in-app ready to show
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        DEAD = "DEAD", "Dead-letter"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_deliveries",
    )
    building = models.ForeignKey(
        "accounts.Building",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notification_deliveries",
    )
    event_key = models.CharField(max_length=255)
    event_code = models.CharField(max_length=64, blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event_key", "channel"],
                name="notification_delivery_once",
            )
        ]
        indexes = [
            models.Index(
                fields=["channel", "status", "next_retry_at"],
                name="notif_delivery_claim_idx",
            ),
        ]


class Device(models.Model):
    """A resident's push-capable install (spec 7.2). fcm_token is unique among
    active rows; possession of a token proves control (see register_device)."""

    class Platform(models.TextChoices):
        IOS = "IOS", "iOS"
        ANDROID = "ANDROID", "Android"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    install_id = models.CharField(max_length=64)
    fcm_token = models.CharField(max_length=512)
    platform = models.CharField(max_length=16, choices=Platform.choices)
    app_version = models.CharField(max_length=32, blank=True)
    active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "install_id"], name="device_user_install_once"
            ),
            models.UniqueConstraint(
                fields=["fcm_token"],
                condition=models.Q(active=True),
                name="device_active_fcm_token_once",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "active"], name="device_user_active_idx")
        ]

