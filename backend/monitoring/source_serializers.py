"""Source write serializers for monitoring module.

Provides MonitoringSourceWriteSerializer for create and partial_update
operations on MonitoringSource. Exposes only safe business inputs;
server-controlled fields are rejected. The optional write-only ``secret``
field allows the client to provide a secret; otherwise the server generates
one. The plaintext secret is returned exactly once on create and never
exposed afterwards.
"""

import hashlib
import secrets
import ipaddress

from rest_framework import serializers

from .models import MonitoringSource


class MonitoringSourceWriteSerializer(serializers.ModelSerializer):
    """Serializer for MonitoringSource create and partial update.

    Serializer fields correspond to actual MonitoringSource model fields that
    are safe for client mutation. Server-controlled fields (secret hash,
    health state, timestamps, counters, soft-delete fields) are declared
    read-only and explicitly rejected if submitted.
    """

    secret = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = MonitoringSource
        fields = [
            "name",
            "code",
            "source_type",
            "description",
            "authentication_type",
            "allowed_ip_networks",
            "allowed_event_types",
            "allowed_target_patterns",
            "default_severity_mapping",
            "default_queue",
            "default_category",
            "rate_limit_per_minute",
            "maximum_payload_bytes",
            "timestamp_tolerance_seconds",
            "enable_ticket_creation",
            "enable_auto_resolution",
            "secret",
        ]
        read_only_fields = [
            "secret_hash",
            "previous_secret_hash",
            "previous_secret_valid_until",
            "last_event_at",
            "last_success_at",
            "last_failure_at",
            "consecutive_failures",
            "health_status",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
            "soft_delete",
            "deleted_at",
            "deleted_by",
        ]

    PROHIBITED_FIELDS = [
        "secret_hash",
        "previous_secret_hash",
        "previous_secret_valid_until",
        "last_event_at",
        "last_success_at",
        "last_failure_at",
        "consecutive_failures",
        "health_status",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
        "soft_delete",
        "deleted_at",
        "deleted_by",
    ]

    def validate_secret(self, value):
        if value is None or value == "":
            return None
        return value

    def validate_allowed_ip_networks(self, value):
        if value:
            for cidr in value.split(","):
                cidr = cidr.strip()
                if cidr:
                    try:
                        ipaddress.ip_network(cidr, strict=False)
                    except ValueError:
                        raise serializers.ValidationError(f"Invalid CIDR: '{cidr}'")
        return value

    def validate(self, attrs):
        for field in self.PROHIBITED_FIELDS:
            if field in self.initial_data:
                raise serializers.ValidationError(
                    {field: f"Field '{field}' is server-controlled and cannot be set."}
                )
        return attrs

    def create(self, validated_data):
        secret = validated_data.pop("secret", None)
        instance = super().create(validated_data)
        if secret:
            instance.secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
            instance._plaintext_secret = secret
        else:
            generated = secrets.token_urlsafe(32)
            instance.secret_hash = hashlib.sha256(generated.encode("utf-8")).hexdigest()
            instance._plaintext_secret = generated
        instance.save(update_fields=["secret_hash"])
        return instance

    def update(self, instance, validated_data):
        validated_data.pop("secret", None)
        for field in self.PROHIBITED_FIELDS:
            validated_data.pop(field, None)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.pop("secret_hash", None)
        data.pop("previous_secret_hash", None)
        data.pop("previous_secret_valid_until", None)
        # Never include plaintext secret in serialized output.
        # The create view mixin adds it to the response data once.
        return data
