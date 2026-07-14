"""Resident API serializers (spec 3). Later tasks append to this module."""

from rest_framework import serializers


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


class LedgerEntryDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    contractor_name = serializers.CharField()
    actual_cost_vnd = serializers.IntegerField()
    published_at = serializers.DateTimeField()
    proposed_amount_vnd = serializers.IntegerField(allow_null=True)
    integrity_status = serializers.CharField()
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
