"""Serializers for advanced ticket operations (queues, watchers, merge, etc.).

Kept in a separate module to avoid colliding with concurrent work on
tickets/serializers.py.
"""
from rest_framework import serializers

from accounts.models import Department, User
from tickets.models import (
    Ticket, TicketQueue, TicketQueueMembership, TicketWatcher,
    CannedResponse, TicketTemplate, TicketRelation, TicketResolutionCode,
    TicketSlaPause, TicketSatisfactionSurvey, SavedTicketView,
    TicketMergeRecord,
)


class TicketQueueSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True)
    manager_email = serializers.CharField(
        source="manager.email", read_only=True, allow_null=True)
    ticket_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = TicketQueue
        fields = ["id", "name", "code", "description", "department",
                  "department_name", "default_category", "default_priority",
                  "is_active", "email_address", "assignment_strategy",
                  "allow_self_claim", "manager", "manager_email",
                  "ticket_count", "created_at", "updated_at"]
        read_only_fields = ["id", "code", "ticket_count",
                            "created_at", "updated_at"]


class TicketQueueCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketQueue
        fields = ["name", "code", "description", "department",
                  "default_category", "default_priority", "is_active",
                  "email_address", "assignment_strategy", "allow_self_claim",
                  "manager"]

    def validate_code(self, value):
        value = (value or "").strip().upper()
        if not value:
            raise serializers.ValidationError("Queue code is required.")
        return value

    def validate_manager(self, user):
        if user is None:
            return user
        from tickets.queue_services import TicketQueue as _Q
        if not _Q._manager_eligible(user):
            raise serializers.ValidationError(
                "Manager must be an active IT Manager or System Admin.")
        return user

class TicketQueueMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = TicketQueueMembership
        fields = ["id", "queue", "user", "user_email", "user_role", "role",
                  "is_active", "can_claim", "can_assign_others", "can_view_all",
                  "joined_at", "created_at", "updated_at"]
        read_only_fields = ["id", "joined_at", "created_at", "updated_at"]


class TicketQueueMembershipCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketQueueMembership
        fields = ["user", "role", "can_claim", "can_assign_others",
                  "can_view_all"]

    def validate_user(self, user):
        from tickets.queue_services import TicketQueueMembership as _M
        if not _M._staff_eligible(user):
            raise serializers.ValidationError(
                "Only active IT staff can be queue members.")
        return user

    def validate_role(self, value):
        if value not in dict(TicketQueueMembership.ROLE_CHOICES):
            raise serializers.ValidationError("Unknown membership role.")
        return value


class TicketWatcherSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    added_by_email = serializers.CharField(
        source="added_by.email", read_only=True, allow_null=True)
    is_muted = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TicketWatcher
        fields = ["id", "ticket", "user", "user_email", "watch_type",
                  "added_by", "added_by_email", "is_active", "muted_until",
                  "is_muted", "created_at", "updated_at"]
        read_only_fields = ["id", "added_by", "is_muted", "created_at",
                            "updated_at"]

    def get_is_muted(self, obj):
        return obj.is_muted()


class TicketWatcherCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketWatcher
        fields = ["user", "watch_type"]

    def validate_watch_type(self, value):
        if value not in dict(TicketWatcher.WATCH_TYPE_CHOICES):
            raise serializers.ValidationError("Unknown watch type.")
        return value


class CannedResponseSerializer(serializers.ModelSerializer):
    owner_email = serializers.CharField(source="owner.email", read_only=True,
                                        allow_null=True)
    queue_name = serializers.CharField(source="queue.name", read_only=True,
                                       allow_null=True)

    class Meta:
        model = CannedResponse
        fields = ["id", "title", "code", "body", "visibility", "category",
                  "queue", "queue_name", "owner", "owner_email", "is_shared",
                  "is_active", "usage_count", "last_used_at", "created_at",
                  "updated_at"]
        read_only_fields = ["id", "owner", "usage_count", "last_used_at",
                            "created_at", "updated_at"]


class CannedResponseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CannedResponse
        fields = ["title", "code", "body", "visibility", "category", "queue",
                  "is_shared"]

    def validate_code(self, value):
        value = (value or "").strip()
        if value and CannedResponse.objects.filter(code=value).exists():
            raise serializers.ValidationError("Code already exists.")
        return value or None


class CannedResponseApplySerializer(serializers.Serializer):
    canned_response_id = serializers.IntegerField()
    visibility = serializers.ChoiceField(
        choices=["public_reply", "internal_note", "both"],
        default="internal_note")
    additional_text = serializers.CharField(required=False, allow_blank=True,
                                            max_length=2000)
    expected_ticket_version = serializers.IntegerField(required=False,
                                                       allow_null=True)


class TicketTemplateSerializer(serializers.ModelSerializer):
    owner_email = serializers.CharField(source="owner.email", read_only=True,
                                        allow_null=True)
    category_name = serializers.CharField(source="category.name",
                                          read_only=True, allow_null=True)
    queue_name = serializers.CharField(source="queue.name", read_only=True,
                                       allow_null=True)

    class Meta:
        model = TicketTemplate
        fields = ["id", "name", "code", "title_template",
                  "description_template", "category", "category_name", "queue",
                  "queue_name", "priority", "default_assignee",
                  "default_status", "required_asset", "note_templates",
                  "custom_fields", "owner", "owner_email", "is_shared",
                  "is_active", "version", "created_at", "updated_at"]
        read_only_fields = ["id", "owner", "version", "created_at",
                            "updated_at"]


class TicketTemplateCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketTemplate
        fields = ["name", "code", "title_template", "description_template",
                  "category", "queue", "priority", "default_assignee",
                  "default_status", "required_asset", "note_templates",
                  "custom_fields", "is_shared"]

    def validate_code(self, value):
        value = (value or "").strip()
        if value and TicketTemplate.objects.filter(code=value).exists():
            raise serializers.ValidationError("Code already exists.")
        return value or None


class TicketFromTemplateSerializer(serializers.Serializer):
    template_id = serializers.IntegerField()
    title = serializers.CharField(required=False, allow_blank=True,
                                  max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    category = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.none(), required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from tickets.models import TicketCategory
        self.fields["category"].queryset = TicketCategory.objects.filter(
            is_deleted=False, is_active=True)


class TicketRelationSerializer(serializers.ModelSerializer):
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, allow_null=True)

    class Meta:
        model = TicketRelation
        fields = ["id", "source_ticket", "target_ticket", "relation_type",
                  "created_by", "created_by_email", "created_at", "notes"]
        read_only_fields = ["id", "created_by", "created_at"]


class TicketRelationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketRelation
        fields = ["target_ticket", "relation_type", "notes"]

    def validate_relation_type(self, value):
        if value not in dict(TicketRelation.RELATION_TYPE_CHOICES):
            raise serializers.ValidationError("Unknown relation type.")
        return value


class TicketChildCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField()
    category = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.none())
    priority = serializers.ChoiceField(
        choices=Ticket.PRIORITY_CHOICES, default="medium")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from tickets.models import TicketCategory
        self.fields["category"].queryset = TicketCategory.objects.filter(
            is_deleted=False, is_active=True)


class DuplicateCheckSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    category = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.none(), required=False, allow_null=True)
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True)
    requester = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True)
    asset = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.none(), required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from tickets.models import TicketCategory
        from assets.models import Asset
        self.fields["category"].queryset = TicketCategory.objects.filter(
            is_deleted=False, is_active=True)
        self.fields["asset"].queryset = Asset.objects.filter(is_deleted=False)


class DuplicateSuggestionSerializer(serializers.Serializer):
    ticket_id = serializers.IntegerField()
    ticket_number = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    score = serializers.IntegerField()
    reason_summary = serializers.CharField()
    may_view = serializers.BooleanField()


class TicketMergeSerializer(serializers.Serializer):
    duplicate_ticket_id = serializers.IntegerField()
    reason = serializers.CharField(trim_whitespace=False)
    transfer_watchers = serializers.BooleanField(default=True)
    include_merge_summary = serializers.BooleanField(default=True)
    expected_primary_version = serializers.IntegerField(required=False,
                                                        allow_null=True)
    expected_duplicate_version = serializers.IntegerField(required=False,
                                                          allow_null=True)


class TicketMergeRecordSerializer(serializers.ModelSerializer):
    merged_by_email = serializers.CharField(
        source="merged_by.email", read_only=True, allow_null=True)

    class Meta:
        model = TicketMergeRecord
        fields = ["id", "primary_ticket", "merged_ticket", "merged_by",
                  "merged_by_email", "merged_at", "reason", "merge_summary",
                  "transferred_notes_count", "transferred_attachments_count",
                  "transferred_watchers_count", "previous_status",
                  "created_at"]
        read_only_fields = fields


class TicketResolutionCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketResolutionCode
        fields = ["id", "name", "code", "description", "category", "is_active",
                  "requires_summary", "requires_kb_link", "marks_known_error",
                  "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]


class ResolveTicketSerializer(serializers.Serializer):
    resolution_code = serializers.PrimaryKeyRelatedField(
        queryset=TicketResolutionCode.objects.filter(is_deleted=False))
    resolution_summary = serializers.CharField(required=False, allow_blank=True)
    requester_visible_note = serializers.CharField(
        required=False, allow_blank=True, max_length=4000)
    expected_ticket_version = serializers.IntegerField(required=False,
                                                       allow_null=True)
    knowledge_base_article_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True)


class CloseTicketSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True,
                                   max_length=1000)
    expected_ticket_version = serializers.IntegerField(required=False,
                                                       allow_null=True)


class ReopenTicketSerializer(serializers.Serializer):
    reason = serializers.CharField(trim_whitespace=False)
    expected_ticket_version = serializers.IntegerField(required=False,
                                                       allow_null=True)


class RequestInformationSerializer(serializers.Serializer):
    message = serializers.CharField(trim_whitespace=False)
    expected_ticket_version = serializers.IntegerField(required=False,
                                                       allow_null=True)
    response_due_date = serializers.DateTimeField(required=False,
                                                  allow_null=True)


class TicketSatisfactionSurveySerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketSatisfactionSurvey
        fields = ["id", "ticket", "requester", "status", "rating",
                  "resolution_helpful", "response_time_satisfied",
                  "communication_satisfied", "comments", "offered_at",
                  "submitted_at", "expires_at", "created_at", "updated_at"]
        read_only_fields = fields


class SatisfactionSubmitSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    resolution_helpful = serializers.BooleanField(required=False,
                                                  allow_null=True)
    response_time_satisfied = serializers.BooleanField(required=False,
                                                       allow_null=True)
    communication_satisfied = serializers.BooleanField(required=False,
                                                       allow_null=True)
    comments = serializers.CharField(required=False, allow_blank=True,
                                     max_length=1000)


class SavedTicketViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedTicketView
        fields = ["id", "name", "owner", "description", "filters", "ordering",
                  "columns", "is_shared", "is_default", "created_at",
                  "updated_at"]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]


class SavedTicketViewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedTicketView
        fields = ["name", "description", "filters", "ordering", "columns",
                  "is_shared", "is_default"]

    def validate_filters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be a JSON object.")
        return value

    def validate_ordering(self, value):
        allowed = {"created_at", "updated_at", "priority", "sla_due_at",
                   "age", "resolved_at", "satisfaction_rating", "queue",
                   "assignee"}
        if value:
            field = value.lstrip("-")
            if field not in allowed:
                raise serializers.ValidationError(
                    f"Ordering '{value}' is not allowed.")
        return value

    def validate_columns(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Columns must be a list.")
        return value


class TimelineEventSerializer(serializers.Serializer):
    id = serializers.CharField()
    source = serializers.CharField()
    actor = serializers.CharField(allow_null=True)
    actor_email = serializers.CharField(allow_null=True)
    timestamp = serializers.DateTimeField()
    action = serializers.CharField()
    summary = serializers.CharField()
    internal = serializers.BooleanField(default=False)
    url = serializers.CharField(allow_null=True)

