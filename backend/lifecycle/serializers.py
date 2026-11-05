"""Lifecycle serializers.

Server-protected fields are read-only; clients cannot set case_number,
progress counts, completion timestamps, version, automation results, or
audit/history fields.
"""
from rest_framework import serializers

from lifecycle import models as lm
from tickets.serializers import validate_attachment_file


class LifecycleTemplateSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(
        source="items.count", read_only=True)

    class Meta:
        model = lm.LifecycleTemplate
        fields = [
            "id", "code", "name", "case_type", "description", "department",
            "is_global", "is_active", "version", "item_count",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["code", "version", "created_by",
                            "created_at", "updated_at", "item_count"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class LifecycleTemplateItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = lm.LifecycleTemplateItem
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]


class LifecycleCaseListSerializer(serializers.ModelSerializer):
    employee_email = serializers.CharField(
        source="employee.email", read_only=True)
    employee_id = serializers.CharField(
        source="employee.employee_id", read_only=True)

    class Meta:
        model = lm.LifecycleCase
        fields = [
            "id", "case_number", "case_type", "employee", "employee_id",
            "employee_email", "department", "status", "priority",
            "assigned_coordinator", "planned_date", "effective_date",
            "completion_target", "checklist_progress", "total_tasks",
            "completed_tasks", "overdue_tasks", "source", "is_deleted",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class LifecycleCaseDetailSerializer(serializers.ModelSerializer):
    employee_email = serializers.CharField(
        source="employee.email", read_only=True)

    class Meta:
        model = lm.LifecycleCase
        fields = "__all__"
        read_only_fields = [
            "id", "case_number", "checklist_progress", "total_tasks",
            "completed_tasks", "overdue_tasks", "started_at",
            "completed_at", "cancelled_at", "version", "created_at",
            "updated_at",
        ]

    def validate_employee(self, value):
        # Employee of an existing case cannot be changed via update.
        if self.instance and self.instance.employee_id != value.pk:
            raise serializers.ValidationError(
                "Employee cannot be changed on an existing case.")
        return value


class LifecycleCaseCreateSerializer(serializers.ModelSerializer):
    template_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = lm.LifecycleCase
        fields = [
            "template_id", "employee", "department", "priority",
            "planned_date", "effective_date", "completion_target",
            "source", "source_reference", "notes",
            "assigned_coordinator",
        ]

    def validate_template_id(self, value):
        try:
            template = lm.LifecycleTemplate.objects.get(
                pk=value, is_deleted=False, is_active=True)
        except lm.LifecycleTemplate.DoesNotExist:
            raise serializers.ValidationError("Template not found or inactive.")
        self.context["template"] = template
        return value


class LifecycleCaseTransitionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(required=False)


class LifecycleTaskListSerializer(serializers.ModelSerializer):
    class Meta:
        model = lm.LifecycleTask
        fields = [
            "id", "case", "sequence", "title", "category", "responsibility",
            "assigned_to", "status", "required", "blocks_completion",
            "requires_evidence", "due_date", "started_at", "completed_at",
            "automation_type", "automation_status",
            "automation_error_summary", "version",
        ]
        read_only_fields = fields


class LifecycleTaskDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = lm.LifecycleTask
        fields = "__all__"
        read_only_fields = [
            "id", "case", "source_template_item", "sequence",
            "started_at", "completed_at", "completed_by",
            "skipped_at", "skipped_by", "automation_status",
            "automation_error_summary", "version", "created_at",
            "updated_at",
        ]


class LifecycleTaskCompleteSerializer(serializers.Serializer):
    completion_note = serializers.CharField(
        required=False, allow_blank=True, default="")
    version = serializers.IntegerField(required=False)


class LifecycleTaskAssignSerializer(serializers.Serializer):
    assigned_to = serializers.IntegerField(required=False, allow_null=True)
    version = serializers.IntegerField(required=False)


class LifecycleTaskSkipSerializer(serializers.Serializer):
    skip_reason = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(required=False)

    def validate_skip_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("A skip reason is required.")
        return value


class LifecycleTaskBlockSerializer(serializers.Serializer):
    blocked_reason = serializers.CharField(
        required=False, allow_blank=True, default="")
    version = serializers.IntegerField(required=False)

    def validate_blocked_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("A block reason is required.")
        return value


class LifecycleAssetResolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = lm.LifecycleAssetResolution
        fields = "__all__"
        read_only_fields = [
            "id", "case", "asset", "resolved_at", "resolved_by",
            "related_task", "created_at", "updated_at",
        ]


class AssetResolutionActionSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(
        choices=lm.ASSET_RESOLUTION_CHOICES)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AssetResolutionTransferSerializer(serializers.Serializer):
    new_assignee = serializers.IntegerField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class LifecycleTaskEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = lm.LifecycleTaskEvidence
        fields = [
            "id", "case", "task", "uploaded_by", "original_filename",
            "file", "content_type", "size", "description",
            "is_deleted", "created_at",
        ]
        read_only_fields = ["id", "uploaded_by", "original_filename",
                            "content_type", "size", "is_deleted", "created_at"]

    def validate_file(self, f):
        return validate_attachment_file(f)


class LifecycleHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = lm.LifecycleHistory
        fields = "__all__"
        read_only_fields = fields


class LifecycleDashboardSerializer(serializers.Serializer):
    pass  # populated in the view
