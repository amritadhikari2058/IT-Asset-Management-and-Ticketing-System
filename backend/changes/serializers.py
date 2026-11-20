"""Serializers for the Change Management application."""

from rest_framework import serializers

from changes.models import (
    ChangeRequest,
    ChangeTemplate,
    ChangeTask,
    ChangeHistory,
    ChangeAssetImpact,
    ChangeServiceImpact,
    ChangeDependency,
    ChangeRiskAssessment,
    ChangeApproval,
    ChangeReviewMeeting,
    ChangeReviewItem,
    MaintenanceWindow,
    ChangeConflict,
    ChangeAttachment,
    ChangeStakeholder,
    ChangeCommunication,
    ChangeImplementation,
    PostImplementationReview,
    ChangeTicketLink,
    ChangeKnowledgeLink,
    BlackoutPeriod,
    ChangeSchedulingException,
)
from tickets.serializers import TicketLinkSerializer
from accounts.serializers import UserSerializer  # may not exist; fallback below


# ---------------------------------------------------------------------------
# Fallback: define minimal inline user serializers if accounts.serializers
# does not export UserSerializer, to avoid import errors.
# ---------------------------------------------------------------------------
try:  # noqa: F401
    from accounts.serializers import UserSerializer as _AccountUserSerializer
except Exception:  # pragma: no cover - accounts app may shape serializers differently
    class _AccountUserSerializer(serializers.ModelSerializer):
        class Meta:
            model = None
            fields = ["id", "email", "employee_id", "role"]


class ChangeRequestSerializer(serializers.ModelSerializer):
    """Full change request serializer (detail)."""

    requester_email = serializers.CharField(source="requester.email", read_only=True)
    change_owner_email = serializers.CharField(source="change_owner.email", read_only=True)
    implementation_lead_email = serializers.CharField(
        source="implementation_lead.email", read_only=True, allow_null=True
    )
    department_name = serializers.CharField(source="department.name", read_only=True, allow_null=True)
    current_approver_email = serializers.CharField(
        source="current_approver.email", read_only=True, allow_null=True
    )
    fulfilment_ticket_id = serializers.IntegerField(
        source="fulfilment_ticket_id", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeRequest
        fields = [
            "id", "change_number", "title", "description", "business_reason",
            "change_type", "category", "status", "priority", "risk_level",
            "calculated_risk_score", "requester", "requester_email",
            "change_owner", "change_owner_email", "implementation_lead",
            "implementation_lead_email", "department", "department_name",
            "planned_start", "planned_end", "actual_start", "actual_end",
            "expected_downtime_minutes", "actual_downtime_minutes",
            "customer_impact", "business_impact", "technical_impact",
            "scope", "out_of_scope", "implementation_plan", "validation_plan",
            "rollback_plan", "communication_plan", "test_evidence_summary",
            "success_criteria", "closure_summary", "failure_reason",
            "rollback_reason", "emergency_reason", "approval_required",
            "current_approver", "current_approver_email", "submitted_at",
            "approved_at", "scheduled_at", "completed_at", "closed_at",
            "cancelled_at", "version", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "change_number", "requester", "change_owner",
            "implementation_lead", "department", "status",
            "calculated_risk_score", "current_approver",
            "submitted_at", "approved_at", "scheduled_at", "completed_at",
            "closed_at", "cancelled_at", "version", "created_at", "updated_at",
        ]


class ChangeRequestListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for change lists."""

    requester_email = serializers.CharField(source="requester.email", read_only=True)
    change_owner_email = serializers.CharField(source="change_owner.email", read_only=True)
    implementation_lead_email = serializers.CharField(
        source="implementation_lead.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeRequest
        fields = [
            "id", "change_number", "title", "change_type", "category",
            "status", "priority", "risk_level", "calculated_risk_score",
            "requester", "requester_email", "change_owner",
            "change_owner_email", "implementation_lead",
            "implementation_lead_email", "department", "planned_start",
            "planned_end", "actual_start", "actual_end",
            "expected_downtime_minutes", "version", "created_at", "updated_at",
        ]


class ChangeRequestCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a change request."""

    class Meta:
        model = ChangeRequest
        fields = [
            "title", "description", "business_reason", "change_type",
            "category", "priority", "department", "scope", "out_of_scope",
            "implementation_plan", "validation_plan", "rollback_plan",
            "communication_plan", "success_criteria", "emergency_reason",
            "approval_required",
        ]
        read_only_fields = [
            "id", "change_number", "status", "calculated_risk_score",
            "risk_level", "requester", "change_owner",
            "implementation_lead", "submitted_at", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        change_type = attrs.get("change_type")
        if change_type == "emergency" and not attrs.get("emergency_reason"):
            raise serializers.ValidationError(
                {"emergency_reason": "Emergency reason is required for emergency changes."}
            )
        return attrs


class ChangeTemplateSerializer(serializers.ModelSerializer):
    owner_email = serializers.CharField(source="owner.email", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    ticket_automation_ready = serializers.SerializerMethodField()

    def get_ticket_automation_ready(self, obj):
        return bool(obj.creates_ticket and obj.is_active)

    class Meta:
        model = ChangeTemplate
        fields = [
            "id", "name", "code", "title_template", "description_template",
            "category", "default_priority", "default_risk_level", "scope",
            "implementation_plan", "validation_plan", "rollback_plan",
            "communication_plan", "expected_duration_minutes",
            "maximum_downtime_minutes", "required_roles",
            "required_task_definitions", "affected_service_rules",
            "approval_policy", "is_preapproved", "is_active", "owner",
            "owner_email", "version", "review_interval_days",
            "last_reviewed_at", "next_review_due", "created_by",
            "created_by_email", "created_at", "updated_at",
            "ticket_automation_ready",
        ]
        read_only_fields = [
            "id", "code", "owner", "version", "last_reviewed_at",
            "next_review_due", "created_by", "created_at", "updated_at",
        ]


class ChangeTaskSerializer(serializers.ModelSerializer):
    assigned_to_email = serializers.CharField(
        source="assigned_to.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeTask
        fields = [
            "id", "sequence", "title", "description", "task_type",
            "assigned_to", "assigned_to_email", "status", "required",
            "blocks_implementation", "blocks_completion", "planned_start",
            "planned_end", "actual_start", "actual_end", "completion_note",
            "evidence_required", "version", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "sequence", "created_at", "updated_at", "version",
        ]


class ChangeHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True, allow_null=True)

    class Meta:
        model = ChangeHistory
        fields = [
            "id", "task", "actor", "actor_email", "event_type",
            "previous_status", "new_status", "detail", "created_at",
        ]
        read_only_fields = fields


class ChangeAssetImpactSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)

    class Meta:
        model = ChangeAssetImpact
        fields = [
            "id", "asset", "asset_tag", "asset_name", "impact_type",
            "expected_state_before", "expected_state_after",
            "actual_state_after", "downtime_minutes", "validation_status",
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ChangeServiceImpactSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(
        source="service_catalogue_item.name", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeServiceImpact
        fields = [
            "id", "service_catalogue_item", "service_name",
            "service_name_snapshot", "impact_level", "expected_outage",
            "expected_degradation", "start_time", "end_time", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ChangeDependencySerializer(serializers.ModelSerializer):
    predecessor_number = serializers.CharField(
        source="predecessor.change_number", read_only=True
    )
    successor_number = serializers.CharField(
        source="successor.change_number", read_only=True
    )

    class Meta:
        model = ChangeDependency
        fields = [
            "id", "predecessor", "predecessor_number", "successor",
            "successor_number", "dependency_type", "notes",
            "created_by", "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_at"]


class ChangeRiskAssessmentSerializer(serializers.ModelSerializer):
    assessed_by_email = serializers.CharField(
        source="assessed_by.email", read_only=True, allow_null=True
    )
    overridden_by_email = serializers.CharField(
        source="overridden_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeRiskAssessment
        fields = [
            "id", "change", "assessed_by", "assessed_by_email",
            "assessment_version", "service_impact_score",
            "user_impact_score", "complexity_score", "reversibility_score",
            "test_coverage_score", "implementation_experience_score",
            "timing_risk_score", "dependency_risk_score",
            "security_risk_score", "data_integrity_risk_score",
            "total_score", "calculated_level", "override_level",
            "override_reason", "overridden_by", "overridden_by_email",
            "assessed_at", "created_at",
        ]
        read_only_fields = [
            "id", "assessed_by", "assessment_version", "total_score",
            "calculated_level", "assessed_at", "created_at",
        ]


class ChangeApprovalSerializer(serializers.ModelSerializer):
    requested_by = serializers.PrimaryKeyRelatedField(
        source="requester", read_only=True
    )
    requested_by_email = serializers.CharField(
        source="requester.email", read_only=True
    )
    requested_from_email = serializers.CharField(
        source="requested_from.email", read_only=True, allow_null=True
    )
    decided_by_email = serializers.CharField(
        source="decided_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeApproval
        fields = [
            "id", "change", "approval_level", "status",
            "requested_from", "requested_from_email", "requester",
            "requested_by", "requested_by_email", "requested_at",
            "decided_by", "decided_by_email", "decided_at", "decision_reason",
            "change_version", "risk_level_snapshot",
            "planned_window_snapshot", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "requester", "requested_at", "decided_at", "created_at", "updated_at",
        ]


class ChangeReviewMeetingSerializer(serializers.ModelSerializer):
    chair_email = serializers.CharField(source="chair.email", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)

    class Meta:
        model = ChangeReviewMeeting
        fields = [
            "id", "title", "meeting_date", "chair", "chair_email",
            "attendees", "status", "notes", "created_by",
            "created_by_email", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]


class ChangeReviewItemSerializer(serializers.ModelSerializer):
    change_number = serializers.CharField(source="change.change_number", read_only=True)
    decided_by_email = serializers.CharField(
        source="decided_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeReviewItem
        fields = [
            "id", "meeting", "change", "change_number", "sequence",
            "decision", "decision_reason", "decided_at", "decided_by",
            "decided_by_email", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MaintenanceWindowSerializer(serializers.ModelSerializer):
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )
    approved_by_email = serializers.CharField(
        source="approved_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = MaintenanceWindow
        fields = [
            "id", "name", "code", "description", "window_type",
            "start_at", "end_at", "timezone_name", "recurrence_rule",
            "department", "service", "status",
            "maximum_parallel_changes", "blackout", "created_by",
            "created_by_email", "approved_by", "approved_by_email",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "code", "created_by", "created_at", "updated_at"]


class ChangeConflictSerializer(serializers.ModelSerializer):
    change_number = serializers.CharField(source="change.change_number", read_only=True)
    conflicting_change_number = serializers.CharField(
        source="conflicting_change.change_number", read_only=True
    )
    acknowledged_by_email = serializers.CharField(
        source="acknowledged_by.email", read_only=True, allow_null=True
    )
    resolved_by_email = serializers.CharField(
        source="resolved_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeConflict
        fields = [
            "id", "change", "change_number", "conflicting_change",
            "conflicting_change_number", "conflict_type", "severity",
            "status", "detected_at", "acknowledged_at",
            "acknowledged_by", "acknowledged_by_email", "resolution",
            "resolved_at", "resolved_by", "resolved_by_email",
            "fingerprint", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "detected_at", "created_at", "updated_at"]


class ChangeAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.CharField(
        source="uploaded_by.email", read_only=True
    )
    task_title = serializers.CharField(source="task.title", read_only=True, allow_null=True)

    class Meta:
        model = ChangeAttachment
        fields = [
            "id", "task", "task_title", "document_type", "uploaded_by",
            "uploaded_by_email", "original_filename", "file",
            "content_type", "size", "checksum", "description", "status",
            "created_at",
        ]
        read_only_fields = [
            "id", "uploaded_by", "size", "checksum", "created_at",
        ]

    def validate_file(self, f):
        from tickets.serializers import validate_attachment_file
        return validate_attachment_file(f)


class ChangeStakeholderSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeStakeholder
        fields = [
            "id", "user", "user_email", "department", "department_name",
            "stakeholder_type", "notification_level", "added_by",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "added_by", "created_at", "updated_at"]


class ChangeCommunicationSerializer(serializers.ModelSerializer):
    sent_by_email = serializers.CharField(
        source="sent_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeCommunication
        fields = [
            "id", "communication_type", "audience", "subject", "message",
            "scheduled_for", "sent_at", "sent_by", "sent_by_email",
            "status", "failure_summary", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "sent_by", "sent_at", "created_at", "updated_at"]


class ChangeImplementationSerializer(serializers.ModelSerializer):
    started_by_email = serializers.CharField(
        source="started_by.email", read_only=True, allow_null=True
    )
    completed_by_email = serializers.CharField(
        source="completed_by.email", read_only=True, allow_null=True
    )
    rollback_completed_by_email = serializers.CharField(
        source="rollback_completed_by.email", read_only=True, allow_null=True
    )
    related_incident_ticket_number = serializers.CharField(
        source="related_incident_ticket.pk", read_only=True,
        allow_null=True
    )

    class Meta:
        model = ChangeImplementation
        fields = [
            "id", "change", "started_by", "started_by_email",
            "completed_by", "completed_by_email", "status", "outcome",
            "implementation_notes", "validation_result",
            "rollback_required", "rollback_started_at",
            "rollback_completed_at", "rollback_completed_by",
            "rollback_completed_by_email", "actual_downtime_minutes",
            "related_incident_ticket", "related_incident_ticket_number",
            "created_at", "updated_at", "version",
        ]
        read_only_fields = [
            "id", "started_by", "completed_by", "created_at",
            "updated_at", "version",
        ]


class PostImplementationReviewSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.CharField(
        source="reviewer.email", read_only=True, allow_null=True
    )
    reviewed_by_email = serializers.CharField(
        source="reviewed_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = PostImplementationReview
        fields = [
            "id", "change", "reviewer", "reviewer_email",
            "scheduled_for", "completed_at", "outcome",
            "objectives_met", "validation_successful",
            "unexpected_impact", "downtime_within_estimate",
            "rollback_used", "incident_created", "lessons_learned",
            "follow_up_actions", "knowledge_article", "reviewed_by",
            "reviewed_by_email", "created_at", "updated_at", "version",
        ]
        read_only_fields = ["id", "reviewer", "created_at", "updated_at", "version"]


class ChangeTicketLinkSerializer(serializers.ModelSerializer):
    ticket_number = serializers.CharField(source="ticket.pk", read_only=True)
    ticket_title = serializers.CharField(source="ticket.title", read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )

    class Meta:
        model = ChangeTicketLink
        fields = [
            "id", "change", "ticket", "ticket_number", "ticket_title",
            "relation_type", "created_by", "created_by_email",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_at"]


class ChangeKnowledgeLinkSerializer(serializers.ModelSerializer):
    article_title = serializers.CharField(source="article.title", read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )

    class Meta:
        model = ChangeKnowledgeLink
        fields = [
            "id", "change", "article", "article_title", "relation_type",
            "created_by", "created_by_email", "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_at"]


# Action-specific serializers

class ChangeSubmitSerializer(serializers.Serializer):
    business_reason = serializers.CharField(required=False, allow_blank=True)
    category = serializers.ChoiceField(
        choices=ChangeRequest.CATEGORY_CHOICES, required=False
    )


class ChangeRiskQuestionnaireSerializer(serializers.Serializer):
    service_impact_score = serializers.IntegerField(min_value=1, max_value=5)
    user_impact_score = serializers.IntegerField(min_value=1, max_value=5)
    complexity_score = serializers.IntegerField(min_value=1, max_value=5)
    reversibility_score = serializers.IntegerField(min_value=1, max_value=5)
    test_coverage_score = serializers.IntegerField(min_value=1, max_value=5)
    implementation_experience_score = serializers.IntegerField(min_value=1, max_value=5)
    timing_risk_score = serializers.IntegerField(min_value=1, max_value=5)
    dependency_risk_score = serializers.IntegerField(min_value=1, max_value=5)
    security_risk_score = serializers.IntegerField(min_value=1, max_value=5)
    data_integrity_risk_score = serializers.IntegerField(min_value=1, max_value=5)
    override_level = serializers.ChoiceField(
        choices=ChangeRequest.RISK_LEVEL_CHOICES, required=False, allow_blank=True
    )
    override_reason = serializers.CharField(required=False, allow_blank=True)


class ChangeApprovalDecisionSerializer(serializers.Serializer):
    decision_reason = serializers.CharField(required=False, allow_blank=True)


class ChangeSchedulingSerializer(serializers.Serializer):
    planned_start = serializers.DateTimeField()
    planned_end = serializers.DateTimeField()
    expected_downtime_minutes = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )

    def validate(self, attrs):
        if attrs["planned_end"] <= attrs["planned_start"]:
            raise serializers.ValidationError(
                {"planned_end": "Planned end must be after planned start."}
            )
        return attrs

    def validate_planned_start(self, value):
        # Prevent scheduling in the past (unless already passed within last hour)
        from django.utils import timezone
        now = timezone.now()
        if value < now - timezone.timedelta(hours=1):
            raise serializers.ValidationError(
                "Planned start cannot be in the past."
            )
        return value


class ChangeImplementationStartSerializer(serializers.Serializer):
    pass


class ChangeCompleteSerializer(serializers.Serializer):
    validation_passed = serializers.BooleanField(default=True)
    implementation_notes = serializers.CharField(required=False, allow_blank=True)


class ChangeFailSerializer(serializers.Serializer):
    failure_reason = serializers.CharField(required=False, allow_blank=True)


class ChangeRollbackSerializer(serializers.Serializer):
    rollback_reason = serializers.CharField(required=False, allow_blank=True)


class ChangeCloseSerializer(serializers.Serializer):
    closure_summary = serializers.CharField(required=False, allow_blank=True)


class ChangeCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class ChangeConvertToEmergencySerializer(serializers.Serializer):
    emergency_reason = serializers.CharField(required=False, allow_blank=True)


class ChangeReadinessSerializer(serializers.Serializer):
    ready = serializers.BooleanField()
    blockers = serializers.ListField(child=serializers.CharField(), required=False)


# ---------------------------------------------------------------------------
# Blackout Period serializers
# ---------------------------------------------------------------------------


class BlackoutPeriodSerializer(serializers.ModelSerializer):
    """Serializer for BlackoutPeriod model."""

    class Meta:
        model = BlackoutPeriod
        fields = [
            "id", "code", "name", "period_type", "start_at", "end_at",
            "description", "status", "scope_department", "scope_service",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate(self, data):
        """Validate that end time is after start time."""
        if data.get("start_at") and data.get("end_at") and data["start_at"] >= data["end_at"]:
            raise serializers.ValidationError({"end_at": "End time must be after start time."})
        return data


# ---------------------------------------------------------------------------
# Scheduling Exception serializers
# ---------------------------------------------------------------------------


class ChangeSchedulingExceptionSerializer(serializers.ModelSerializer):
    """Serializer for ChangeSchedulingException model."""

    requesting_user_email = serializers.CharField(
        source="requesting_user.email", read_only=True
    )
    decided_by_email = serializers.CharField(
        source="decided_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeSchedulingException
        fields = [
            "id", "change", "blackout_period", "maintenance_window",
            "justification", "requesting_user", "requesting_user_email",
            "decided_by", "decided_by_email", "decision_timestamp",
            "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at", "requesting_user", "decided_by", "decision_timestamp"]

    def validate(self, data):
        """Validate exception constraints."""
        # decided_by is populated by the view on approve/reject.
        return data