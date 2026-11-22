from rest_framework import serializers

from common.models import (AuditLog, DataRetentionExecution,
                           DataRetentionPolicy, HealthCheckResult,
                           NotificationOutboxEvent,
                           OperationalAlert, OperationalErrorEvent,
                           OperationalIncident, Notification,
                           PrivacyErasureRequest,
                           SavedReport, ScheduledReport,
                           ScheduledReportRun,
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
        read_only_fields = ["id", "title", "body", "entity_type",
                            "object_id", "created_at", "is_deleted"]


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
        """Ensure categories is a dict of str->bool with known keys only."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Categories must be an object.")
        allowed = {key for key, _label in UserNotificationPreference.EMAIL_CATEGORIES}
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, bool):
                raise serializers.ValidationError(
                    "Each category must map to a boolean.")
            if k not in allowed:
                raise serializers.ValidationError(
                    f"Unknown category '{k}'. Allowed: {sorted(allowed)}.")
        return value


class PrivacyErasureRequestSerializer(serializers.ModelSerializer):
    """Read serializer for privacy erasure requests (list + detail)."""

    requested_by_email = serializers.CharField(
        source="requested_by.email", read_only=True)
    requested_by_id = serializers.CharField(
        source="requested_by.employee_id", read_only=True)
    reviewer_email = serializers.CharField(
        source="reviewed_by.email", read_only=True, allow_null=True)
    reviewer_id = serializers.CharField(
        source="reviewed_by.employee_id", read_only=True, allow_null=True)
    executor_email = serializers.CharField(
        source="executed_by.email", read_only=True, allow_null=True)

    class Meta:
        model = PrivacyErasureRequest
        fields = [
            "id", "entity_type", "object_id", "scope", "reason", "status",
            "requested_by", "requested_by_email", "requested_by_id",
            "reviewed_by", "reviewer_email", "reviewer_id",
            "reviewed_at", "review_decision", "review_reason",
            "executed_by", "executor_email", "executed_at",
            "cancellation_reason", "created_at", "decided_at", "result",
        ]
        read_only_fields = fields


class PrivacyErasureCreateSerializer(serializers.Serializer):
    """Create serializer for a new erasure request."""

    entity_type = serializers.CharField()
    object_id = serializers.CharField()
    scope = serializers.CharField(trim_whitespace=True)
    reason = serializers.CharField(trim_whitespace=True)
    confirm = serializers.CharField()

    def validate_confirm(self, value):
        object_id = self.initial_data.get("object_id")
        if value != str(object_id):
            raise serializers.ValidationError(
                "Confirmation required: re-enter the record ID.")
        return value

    def validate(self, attrs):
        if not attrs.get("scope") or not attrs.get("scope").strip():
            raise serializers.ValidationError(
                {"scope": "Scope is required."})
        if not attrs.get("reason") or not attrs.get("reason").strip():
            raise serializers.ValidationError(
                {"reason": "Reason is required."})
        return attrs


class PrivacyErasureReviewSerializer(serializers.Serializer):
    """Approve / reject serializer (independent reviewer)."""

    decision = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs.get("decision") == "reject" and not attrs.get("reason"):
            raise serializers.ValidationError(
                {"reason": "A reason is required when rejecting."})
        return attrs


class PrivacyErasureExecuteSerializer(serializers.Serializer):
    """Execution confirmation serializer."""

    confirm = serializers.CharField()

    def validate_confirm(self, value):
        object_id = self.context.get("object_id")
        if value != str(object_id):
            raise serializers.ValidationError(
                "Re-enter the record ID to confirm execution.")
        return value


class DataRetentionPolicySerializer(serializers.ModelSerializer):
    """Serializer for data-retention policies."""

    responsible_admin_email = serializers.CharField(
        source="responsible_admin.email", read_only=True, allow_null=True)

    class Meta:
        model = DataRetentionPolicy
        fields = [
            "id", "name", "data_category", "retention_duration", "enabled",
            "conditions", "description", "last_run_at", "next_run_at",
            "responsible_admin", "responsible_admin_email",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "last_run_at", "next_run_at",
                            "created_at", "updated_at"]

    def validate_retention_duration(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Retention duration must be zero or more days.")
        return value


class DataRetentionExecutionSerializer(serializers.ModelSerializer):
    """Serializer for retention execution history."""

    class Meta:
        model = DataRetentionExecution
        fields = [
            "id", "policy", "status", "started_at", "finished_at",
            "records_eligible", "records_affected", "records_excluded",
            "exclusion_reasons", "error_summary", "result", "created_at",
        ]
        read_only_fields = fields


class HealthCheckResultSerializer(serializers.ModelSerializer):
    """Serializer for health check result history."""

    class Meta:
        model = HealthCheckResult
        fields = [
            "id", "component", "state", "evaluated_at",
            "last_successful_at", "last_failure_at", "diagnostic", "details",
        ]
        read_only_fields = fields


class OperationalErrorEventSerializer(serializers.ModelSerializer):
    """Serializer for sanitized operational error events."""

    resolved_by_email = serializers.CharField(
        source="resolved_by.email", read_only=True, allow_null=True)

    class Meta:
        model = OperationalErrorEvent
        fields = [
            "id", "dedup_key", "component", "severity", "title", "message",
            "correlation_id", "endpoint", "status_code", "occurrence_count",
            "first_occurred", "last_occurred", "resolved", "resolved_at",
            "resolved_by", "resolved_by_email", "details",
        ]
        read_only_fields = fields


class OperationalAlertSerializer(serializers.ModelSerializer):
    """Serializer for operational alerts."""

    acknowledged_by_email = serializers.CharField(
        source="acknowledged_by.email", read_only=True, allow_null=True)
    resolved_by_email = serializers.CharField(
        source="resolved_by.email", read_only=True, allow_null=True)

    class Meta:
        model = OperationalAlert
        fields = [
            "id", "dedup_key", "component", "severity", "status", "title",
            "description", "created_at", "last_occurred",
            "occurrence_count", "acknowledged", "acknowledged_at",
            "acknowledged_by", "acknowledged_by_email", "resolved",
            "resolved_at", "resolved_by", "resolved_by_email", "details",
        ]
        read_only_fields = fields


class NotificationOutboxEventSerializer(serializers.ModelSerializer):
    """Read-only serializer for outbox delivery events.

    ``payload`` is intentionally excluded from list output: it may contain email
    bodies (user content). It is exposed only through the dedicated detail
    action, which is gated to administrators.
    """

    recipient_email = serializers.CharField(read_only=True)

    class Meta:
        model = NotificationOutboxEvent
        fields = [
            "id", "event_type", "channel", "recipient", "recipient_email",
            "category", "status", "attempts", "max_attempts",
            "next_attempt_at", "last_attempt_at", "delivered_at",
            "lease_expires_at", "claimed_by", "last_error", "cancel_reason",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class OperationalIncidentSerializer(serializers.ModelSerializer):
    """Serializer for operational incidents."""

    assigned_to_email = serializers.CharField(
        source="assigned_to.email", read_only=True, allow_null=True)

    class Meta:
        model = OperationalIncident
        fields = [
            "id", "title", "description", "severity", "status",
            "affected_component", "assigned_to", "assigned_to_email",
            "created_at", "resolved_at", "closed_at", "related_ticket",
            "related_alerts", "internal_notes",
        ]
        read_only_fields = ["id", "created_at", "assigned_to_email"]

