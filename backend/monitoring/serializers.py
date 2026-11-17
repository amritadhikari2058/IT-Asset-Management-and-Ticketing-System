"""Serializers for monitoring module."""

from rest_framework import serializers
from .models import MonitoringSource, MonitoringEvent, MonitoringAlert


class MonitoringSourceListSerializer(serializers.ModelSerializer):
    """Serializer for MonitoringSource list view."""

    class Meta:
        model = MonitoringSource
        fields = ["id", "name", "code", "source_type", "status", "health_status", "is_active"]
        read_only_fields = ["code"]


class MonitoringSourceCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating MonitoringSource."""

    secret = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = MonitoringSource
        fields = ["name", "code", "source_type", "description", "secret"]

    def create(self, validated_data):
        import hashlib
        secret = validated_data.pop("secret", None)
        instance = super().create(validated_data)
        if secret:
            instance.secret_hash = hashlib.sha256(secret.encode()).hexdigest()
            instance.save(update_fields=["secret_hash"])
            instance._plaintext_secret = secret
        elif not instance.secret_hash:
            import secrets
            generated = secrets.token_urlsafe(32)
            instance.secret_hash = hashlib.sha256(generated.encode()).hexdigest()
            instance.save(update_fields=["secret_hash"])
            instance._plaintext_secret = generated
        return instance


class MonitoringSourceDetailSerializer(serializers.ModelSerializer):
    """Serializer for MonitoringSource detail view."""

    class Meta:
        model = MonitoringSource
        exclude = ["secret_hash", "previous_secret_hash", "previous_secret_valid_until"]
        read_only_fields = ["created_at", "updated_at"]


class MonitoringEventSerializer(serializers.ModelSerializer):
    """Serializer for MonitoringEvent list view."""

    source_name = serializers.CharField(source="source.name", read_only=True)

    class Meta:
        model = MonitoringEvent
        fields = ["event_id", "source", "source_name", "event_type", "event_state", "severity", "title"]
        read_only_fields = ["event_id", "fingerprint"]


class MonitoringAlertSerializer(serializers.ModelSerializer):
    """Serializer for MonitoringAlert list view."""

    source_name = serializers.CharField(source="source.name", read_only=True)
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MonitoringAlert
        fields = ["alert_number", "title", "severity", "status", "source_name", "event_count"]
        read_only_fields = ["alert_number"]
