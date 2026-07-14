"""Resident API serializers (spec 3). Later tasks append to this module."""

from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Email or Vietnamese phone number.")
    # trim_whitespace=False: passwords may legitimately contain spaces.
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    expiry = serializers.DateTimeField()
