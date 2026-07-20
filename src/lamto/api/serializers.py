"""Resident API serializers (spec 3). Later tasks append to this module."""

from rest_framework import serializers


class ProblemSerializer(serializers.Serializer):
    """RFC 9457 problem+json body with a LamTo stable machine ``code`` (spec 3.1).

    ``detail`` is developer English; the Flutter client owns Vietnamese UI copy
    keyed off ``code``. ``errors`` is present only for validation failures.
    """

    type = serializers.CharField(
        help_text="Problem type URI reference; usually about:blank.",
    )
    title = serializers.CharField(
        help_text="Short human-readable summary (HTTP status phrase).",
    )
    status = serializers.IntegerField(help_text="HTTP status code.")
    code = serializers.CharField(
        help_text=(
            "Stable machine code for client branching "
            "(e.g. validation_failed, authentication_failed, not_authenticated, "
            "permission_denied, not_found, occupancy_selection_required, throttled)."
        ),
    )
    detail = serializers.CharField(
        required=False,
        help_text="Developer-English explanation; not shown raw to residents.",
    )
    errors = serializers.DictField(
        required=False,
        help_text=(
            "Per-field validation errors when code is validation_failed. "
            "Values are lists of {message, code} objects (may nest for non-field errors)."
        ),
    )


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Email or Vietnamese phone number.")
    # trim_whitespace=False: passwords may legitimately contain spaces.
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    expiry = serializers.DateTimeField()


class OccupancySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    unit_label = serializers.CharField()
    building_name = serializers.CharField()


class NotificationPreferenceSerializer(serializers.Serializer):
    event_code = serializers.CharField()
    email_enabled = serializers.BooleanField()
    push_enabled = serializers.BooleanField()


class NotificationPreferenceUpdateItemSerializer(serializers.Serializer):
    """One preference row for PATCH /me/notification-preferences."""

    event_code = serializers.CharField(max_length=64)
    email_enabled = serializers.BooleanField(required=False)
    push_enabled = serializers.BooleanField(required=False)

    def validate(self, data):
        if "email_enabled" not in data and "push_enabled" not in data:
            raise serializers.ValidationError(
                "At least one of email_enabled or push_enabled is required."
            )
        return data


class NotificationPreferenceUpdateSerializer(serializers.Serializer):
    preferences = NotificationPreferenceUpdateItemSerializer(many=True, allow_empty=False)


class LogoutInstallIdSerializer(serializers.Serializer):
    """Optional body field for logout Device deactivation (spec 7.2)."""

    install_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="Deactivate this install's FCM Device on logout (also accepted via X-Install-Id).",
    )


class MeSerializer(serializers.Serializer):
    display_name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField(allow_null=True)
    occupancies = OccupancySerializer(many=True)
    notification_preferences = NotificationPreferenceSerializer(many=True)


class LedgerFilterSerializer(serializers.Serializer):
    year = serializers.IntegerField(required=False, min_value=2000, max_value=2100)
    month = serializers.IntegerField(required=False, min_value=1, max_value=12)

    def validate(self, data):
        if "month" in data and "year" not in data:
            raise serializers.ValidationError({"month": "month requires a year."})
        return data


class LedgerEntryListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    contractor_name = serializers.CharField()
    actual_cost_vnd = serializers.IntegerField()
    published_at = serializers.DateTimeField()
    integrity_status = serializers.CharField(source="effective_integrity_status")
    evidence_level = serializers.SerializerMethodField()

    def get_evidence_level(self, entry) -> str:
        from lamto.evidence.models import evidence_level

        return evidence_level(entry.snapshot.outbox_event.status)


class VerificationSerializer(serializers.Serializer):
    decision = serializers.CharField()
    verified_by = serializers.CharField()
    verified_at = serializers.DateTimeField()


class RedactedDocumentSerializer(serializers.Serializer):
    label = serializers.CharField()
    filename = serializers.CharField()
    sha256 = serializers.CharField()
    download_url = serializers.CharField()


class CorrectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    reason = serializers.CharField()


class ProofEventSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    event_type = serializers.IntegerField()
    status = serializers.CharField()
    evidence_level = serializers.CharField()
    transaction_hash = serializers.CharField(allow_blank=True)


class ProofSerializer(serializers.Serializer):
    evidence_level = serializers.CharField()
    anchoring_backend = serializers.CharField(allow_blank=True)
    payload_hash = serializers.CharField()
    events = ProofEventSerializer(many=True)


class LedgerApproverSerializer(serializers.Serializer):
    """Who authorized the spend (board / resident rep / emergency)."""

    role = serializers.CharField(
        help_text="Machine role: board, resident_rep, or emergency."
    )
    name = serializers.CharField(help_text="Display name of the approver.")
    decision = serializers.CharField(help_text="Decision code (e.g. APPROVE).")


class LedgerEntryDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    contractor_name = serializers.CharField()
    actual_cost_vnd = serializers.IntegerField()
    published_at = serializers.DateTimeField()
    proposed_amount_vnd = serializers.IntegerField(allow_null=True)
    integrity_status = serializers.CharField()
    # §6.3(6) plain-language story (A1): what / why / approvers alongside amount
    # and payment verification. Sourced from work/report relations, not invented.
    what_was_fixed = serializers.CharField(
        help_text="Resident-visible narrative of work completed."
    )
    why = serializers.CharField(
        help_text="Resident-visible rationale (cause / purpose / emergency reason)."
    )
    approvers = LedgerApproverSerializer(many=True)
    payload = serializers.JSONField()
    verification = VerificationSerializer(allow_null=True)
    redacted_documents = RedactedDocumentSerializer(many=True)
    corrections = CorrectionSerializer(many=True)
    proof = ProofSerializer()


class FundSummarySerializer(serializers.Serializer):
    balance_vnd = serializers.IntegerField()
    period_days = serializers.IntegerField()
    period_inflows_vnd = serializers.IntegerField()
    period_outflows_vnd = serializers.IntegerField()


class FundSeriesPointSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    inflows_vnd = serializers.IntegerField()
    outflows_vnd = serializers.IntegerField(
        help_text="Outflow-type amounts are stored negative; this is <= 0."
    )
    balance_vnd = serializers.IntegerField()


class FundSeriesSerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=("30d", "6m", "12m"))
    points = FundSeriesPointSerializer(many=True)


class ReportCreateSerializer(serializers.Serializer):
    client_ref = serializers.UUIDField(
        help_text="Client-generated UUID, unique per user (spec 3.5)."
    )
    text = serializers.CharField(max_length=5000)
    location_id = serializers.IntegerField(
        help_text="Active BuildingLocation id in the resolved occupancy building."
    )


class ReportSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    status = serializers.CharField()
    location_path_snapshot = serializers.CharField()
    created_at = serializers.DateTimeField()


class ReportPhotoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    filename = serializers.CharField()
    sha256 = serializers.CharField()
    download_url = serializers.CharField()


class ReportPhotoUploadSerializer(serializers.Serializer):
    photo = serializers.FileField(help_text="JPEG/PNG image; scanned by ClamAV before storage.")


class ReportWorkOrderSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    deadline_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField(allow_null=True)
    accepted_at = serializers.DateTimeField(allow_null=True)
    can_rate = serializers.BooleanField()


class ReportCaseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    category = serializers.CharField()
    urgency = serializers.CharField()
    deadline_at = serializers.DateTimeField()
    active = serializers.BooleanField()
    work_orders = ReportWorkOrderSerializer(many=True)


class ReportDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    status = serializers.CharField()
    location_path_snapshot = serializers.CharField()
    unit_label = serializers.CharField()
    created_at = serializers.DateTimeField()
    triage_status = serializers.CharField(allow_null=True)
    category = serializers.CharField(allow_null=True)
    photos = ReportPhotoSerializer(many=True)
    cases = ReportCaseSerializer(many=True)


class WorkRatingSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class WorkRatingResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    work_order_id = serializers.IntegerField()
    score = serializers.IntegerField()


class LocationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)


class NotificationFeedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_code = serializers.CharField()
    event_key = serializers.CharField(
        help_text=(
            "Deep-link reference '{code}:{entity}:{id}' (spec 6.3/7.4). Entity ids "
            "are resident-visible resources the API re-authorizes on fetch. "
            "Authorization-neutral and non-sensitive: codes/entity/ids only — "
            "no PII, bodies, or tokens."
        ),
    )
    subject = serializers.CharField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)


class DeviceRegisterSerializer(serializers.Serializer):
    install_id = serializers.CharField(
        max_length=64, help_text="Stable per-install client UUID (spec 7.2)."
    )
    fcm_token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=["IOS", "ANDROID"])
    app_version = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )


class DeviceSerializer(serializers.Serializer):
    install_id = serializers.CharField()
    platform = serializers.CharField()
    active = serializers.BooleanField()
