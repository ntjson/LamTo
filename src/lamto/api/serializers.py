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
