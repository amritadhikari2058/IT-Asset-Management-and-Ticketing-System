from rest_framework import serializers

from common.models import (AuditLog, Notification, SavedReport,
                           ScheduledReport, ScheduledReportRun,
                           UserNotificationPreference)


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


class SavedReportSerializer(serializers.ModelSerializer):
    """Serializer for saved report configurations."""

    user_email = serializers.CharField(source="user.email", read_only=True)
    schedule_count = serializers.IntegerField(
        source="schedules.count", read_only=True)

    class Meta:
        model = SavedReport
        fields = ["id", "user", "user_email", "report_type", "name",
                  "description", "filters", "is_shared",
                  "schedule_count", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "user_email", "schedule_count",
                            "created_at", "updated_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        report_type = attrs.get("report_type") or getattr(
            self.instance, "report_type", None)
        if report_type not in dict(SavedReport.REPORT_TYPE_CHOICES):
            raise serializers.ValidationError(
                {"report_type": "Invalid report type."})
        return attrs


class ScheduledReportSerializer(serializers.ModelSerializer):
    """Serializer for scheduled report delivery."""

    saved_report_name = serializers.CharField(
        source="saved_report.name", read_only=True)
    saved_report_type = serializers.CharField(
        source="saved_report.report_type", read_only=True)
    run_count = serializers.IntegerField(source="runs.count", read_only=True)

    class Meta:
        model = ScheduledReport
        fields = ["id", "saved_report", "saved_report_name",
                  "saved_report_type", "schedule", "recipients", "format",
                  "enabled", "next_run_at", "run_count",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "next_run_at", "run_count",
                            "created_at", "updated_at"]

    def validate(self, attrs):
        schedule = attrs.get("schedule") or getattr(
            self.instance, "schedule", None)
        if schedule not in dict(ScheduledReport.SCHEDULE_CHOICES):
            raise serializers.ValidationError(
                {"schedule": "Invalid schedule."})
        fmt = attrs.get("format") or getattr(self.instance, "format", None)
        if fmt not in dict(ScheduledReport.FORMAT_CHOICES):
            raise serializers.ValidationError(
                {"format": "Invalid format."})
        recipients = attrs.get("recipients") or getattr(
            self.instance, "recipients", None)
        if not isinstance(recipients, list) or not recipients:
            raise serializers.ValidationError(
                {"recipients": "Provide at least one recipient email."})
        return attrs


class ScheduledReportRunSerializer(serializers.ModelSerializer):
    """Serializer for scheduled report execution history."""

    class Meta:
        model = ScheduledReportRun
        fields = ["id", "scheduled_report", "status", "started_at",
                  "finished_at", "success", "error_summary",
                  "recipient_count"]
        read_only_fields = fields


class UserNotificationPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user notification preferences."""

    email_categories = serializers.SerializerMethodField()

    class Meta:
        model = UserNotificationPreference
        fields = ["id", "user", "email_enabled", "categories",
                  "email_categories", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def get_email_categories(self, obj):
        """Return the full list of categories with current opt-in state."""
        return [
            {"key": key, "label": label, "enabled": obj.email_enabled_for(key)}
            for key, label in UserNotificationPreference.EMAIL_CATEGORIES
        ]

    def validate_categories(self, value):
        """Ensure categories is a dict of str->bool."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Categories must be an object.")
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, bool):
                raise serializers.ValidationError(
                    "Each category must map to a boolean.")
        return value
