from rest_framework import serializers

from common.models import AuditLog, Notification


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_email", "action", "entity_type",
                  "object_id", "object_repr", "timestamp", "reason", "details"]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "is_read", "entity_type",
                  "object_id", "created_at", "is_deleted"]
        read_only_fields = ["id", "created_at", "is_deleted"]


class RecycleBinEntrySerializer(serializers.Serializer):
    """Generic representation for deleted records across entity types."""
    entity_type = serializers.CharField()
    object_id = serializers.CharField()
    repr = serializers.CharField()
    deleted_at = serializers.DateTimeField(allow_null=True)
    deleted_by = serializers.CharField(allow_null=True)
    deletion_reason = serializers.CharField(allow_blank=True)
