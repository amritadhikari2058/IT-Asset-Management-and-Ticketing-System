"""PM1 serializers (Gate 1).

Server-managed fields (number, status, counters, milestones, summaries,
record_version, fingerprints, history) are read-only here; status movement
only through action endpoints. ``expected_record_version`` is write-only and
consumed by the service layer for 409 optimistic concurrency.
"""
from rest_framework import serializers

from assets.models import Asset
from cmdb.models import ConfigurationItem
from licensing.models import SoftwareProduct
from services.models import ServiceCatalogueItem
from tickets.models import Ticket

from .models import (
    Problem,
    ProblemAssetLink,
    ProblemConfigurationItemLink,
    ProblemHistory,
    ProblemKbArticleLink,
    ProblemServiceLink,
    ProblemSoftwareProductLink,
    ProblemTask,
    ProblemTicketLink,
)

SERVER_ONLY_PROBLEM_FIELDS = [
    "problem_number", "status", "record_version", "first_detected_at",
    "investigation_started_at", "root_cause_identified_at",
    "workaround_available_at", "known_error_at", "permanent_fix_planned_at",
    "permanent_fix_implemented_at", "validation_started_at", "resolved_at",
    "closed_at", "reopened_at", "recurrence_count", "linked_ticket_count",
    "open_ticket_count", "root_cause_summary", "workaround_summary",
    "permanent_fix_summary", "resolution_summary", "closure_reason",
    "created_by", "created_at", "updated_at", "source",
]

# Problem status lifecycle states
PROBLEM_LIFECYCLE_STATES = [
    "identified", "triage", "investigating", "investigation_complete",
    "resolving", "resolved", "closed", "rejected", "cancelled",
]

# Valid status transitions map
# Key: current status, Value: set of allowed next states
PROBLEM_VALID_TRANSITIONS = {
    "identified": {"triage", "cancelled"},
    "triage": {"investigating", "cancelled"},
    "investigating": {"investigation_complete", "cancelled"},
    "investigation_complete": {"resolving", "cancelled"},
    "resolving": {"resolved", "cancelled"},
    "resolved": {"closed", "reopened", "cancelled"},
    "closed": {},  # Closed problems cannot be directly modified
    "rejected": {},  # Rejected problems cannot be directly modified
    "cancelled": {},  # Cancelled problems cannot be directly modified
}


def _validate_lifecycle_fields(attrs, is_creation=False):
    """Validate that required lifecycle fields are present for the target status."""
    problem = attrs.get("problem")  # For update serializers
    status = attrs.get("status")
    
    if not status:
        return attrs
    
    # During creation, set initial status
    if is_creation:
        # Default to 'identified' for new problems
        if not status:
            attrs["status"] = "identified"
        return attrs
    
    # For updates, validate transition and required fields
    if problem and hasattr(problem, "status"):
        current_status = problem.status
        target_status = status
        
        # Check if transition is valid
        allowed_transitions = PROBLEM_VALID_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_transitions:
            raise serializers.ValidationError(
                f"Invalid status transition from '{current_status}' to '{target_status}'. "
                f"Allowed transitions: {', '.join(sorted(allowed_transitions))}"
            )
        
        # Require root cause identified before investigation complete
        if current_status == "investigating" and target_status == "investigation_complete":
            if not problem.root_cause_identified_at:
                raise serializers.ValidationError(
                    "Root cause must be identified before moving investigation to complete."
                )
        
        # Require resolution summary before closure
        if target_status == "closed" and not problem.resolution_summary:
            raise serializers.ValidationError(
                "Resolution summary is required before closing the problem."
            )
        
        # Require closure reason when closing
        if target_status == "closed" and not attrs.get("closure_reason"):
            raise serializers.ValidationError(
                "Closure reason is required when closing the problem."
            )
        
        # Require permanent fix planned before resolving if it's a permanent fix problem
        if current_status == "investigation_complete" and target_status == "resolving":
            # Check if permanent_fix_planned_at should be set
            if not problem.permanent_fix_planned_at and not attrs.get("permanent_fix_planned_at"):
                # This is a warning, not a hard requirement at this stage
                pass  # Could be optional depending on problem type
    
    return attrs


class ProblemUpdateSerializer(serializers.ModelSerializer):
    """Serializer for problem status updates and lifecycle management."""
    
    class Meta:
        model = Problem
        fields = [
            "status", "root_cause_identified_at", "workaround_available_at",
            "known_error_at", "permanent_fix_planned_at", "permanent_fix_implemented_at",
            "resolved_at", "closed_at", "reopened_at", "resolution_summary",
            "closure_reason", "root_cause_summary", "workaround_summary",
            "permanent_fix_summary",
        ]
        read_only_fields = [
            "problem_number", "record_version", "created_by", "created_at",
        ]
    
    def validate(self, attrs):
        """Validate lifecycle field requirements."""
        return _validate_lifecycle_fields(attrs, is_creation=False)


class ProblemCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new problems."""
    
    class Meta:
        model = Problem
        fields = [
            "title", "problem_type", "source", "severity", "priority",
            "department", "service", "category", "environment",
            "affected_ci", "affected_asset", "affected_service",
            "affected_software_product", "description",
        ]
    
    def create(self, validated_data):
        """Create problem with initial status 'identified'."""
        validated_data["status"] = "identified"
        validated_data["created_by"] = self.context["request"].user
        validated_data["problem_manager"] = self.context["request"].user
        problem = super().create(validated_data)
        return problem


class ExpectedVersionMixin(serializers.Serializer):
    expected_record_version = serializers.IntegerField(
        required=False, write_only=True, min_value=1,
    )


class OwnerField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        from accounts.models import User

        return User.objects.filter(is_active=True, role__in=[
            "system_admin", "it_manager", "it_support",
        ])


class ProblemListSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    problem_manager_username = serializers.CharField(
        source="problem_manager.username", read_only=True,
    )
    service_name = serializers.CharField(source="service.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Problem
        fields = [
            "id", "problem_number", "title", "problem_type", "source",
            "status", "priority", "severity", "criticality", "urgency",
            "owner", "owner_username", "problem_manager",
            "problem_manager_username", "service", "service_name",
            "category", "category_name", "environment",
            "target_resolution_date", "next_review_at",
            "recurrence_count", "linked_ticket_count", "open_ticket_count",
            "record_version", "is_open", "is_deleted",
            "created_at", "updated_at",
        ]


class ProblemDetailSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    problem_manager_username = serializers.CharField(
        source="problem_manager.username", read_only=True,
    )
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True,
    )
    service_name = serializers.CharField(source="service.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Problem
        fields = [
            "id", "problem_number", "title", "description", "problem_type",
            "source", "status", "priority", "severity", "impact", "urgency",
            "criticality", "owner", "owner_username", "problem_manager",
            "problem_manager_username", "assigned_group", "department",
            "department_name", "service", "service_name", "category",
            "category_name", "subcategory", "environment", "detection_method",
            "first_detected_at", "investigation_started_at",
            "root_cause_identified_at", "workaround_available_at",
            "known_error_at", "permanent_fix_planned_at",
            "permanent_fix_implemented_at", "validation_started_at",
            "resolved_at", "closed_at", "reopened_at",
            "target_resolution_date", "next_review_at",
            "recurrence_monitoring_until",
            "root_cause_summary", "workaround_summary",
            "permanent_fix_summary", "resolution_summary", "closure_reason",
            "recurrence_count", "linked_ticket_count", "open_ticket_count",
            "record_version", "is_open", "is_deleted", "deletion_reason",
            "created_by", "created_by_username", "created_at", "updated_at",
        ]


class ProblemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Problem
        fields = [
            "title", "description", "problem_type", "source", "priority",
            "severity", "impact", "urgency", "criticality", "owner",
            "problem_manager", "assigned_group", "department", "service",
            "category", "subcategory", "environment", "detection_method",
            "target_resolution_date",
        ]

    def validate_title(self, value):
        if not (value or "").strip():
            raise serializers.ValidationError("Title is required.")
        return value.strip()

    def validate_description(self, value):
        if not (value or "").strip():
            raise serializers.ValidationError("Description is required.")
        return value.strip()

    def validate_source(self, value):
        # Client-creatable sources only; monitoring/trend/cmdb are detection-set.
        allowed = {
            "manual", "ticket", "major_incident", "change_review",
            "knowledge", "supplier", "audit", "other",
        }
        if value not in allowed:
            raise serializers.ValidationError(
                "Source is not client-assignable."
            )
        return value


class ProblemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Problem
        fields = [
            "title", "description", "priority", "severity", "impact",
            "urgency", "criticality", "owner", "problem_manager",
            "assigned_group", "department", "service", "category",
            "subcategory", "environment", "detection_method",
            "target_resolution_date", "next_review_at",
        ]


class SubmitProblemSerializer(ExpectedVersionMixin):
    pass


class AcceptProblemSerializer(ExpectedVersionMixin):
    pass


class RejectProblemSerializer(ExpectedVersionMixin):
    reason = serializers.CharField(required=True, allow_blank=False)


class StartInvestigationSerializer(ExpectedVersionMixin):
    pass


class CancelProblemSerializer(ExpectedVersionMixin):
    reason = serializers.CharField(required=True, allow_blank=False)


class ReopenProblemSerializer(ExpectedVersionMixin):
    reason = serializers.CharField(required=True, allow_blank=False)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

class ProblemTicketLinkSerializer(serializers.ModelSerializer):
    ticket_display = serializers.SerializerMethodField()
    ticket_title = serializers.CharField(source="ticket.title", read_only=True)
    ticket_status = serializers.CharField(source="ticket.status", read_only=True)
    ticket_priority = serializers.CharField(source="ticket.priority", read_only=True)
    ticket_category_name = serializers.CharField(
        source="ticket.category.name", read_only=True, default=None)

    class Meta:
        model = ProblemTicketLink
        fields = [
            "id", "problem", "ticket", "ticket_display", "ticket_title",
            "ticket_status", "ticket_priority", "ticket_category_name",
            "relationship_type", "relevance", "is_primary", "note",
            "linked_by", "linked_at", "is_deleted",
        ]
        read_only_fields = [
            "id", "linked_by", "linked_at", "is_deleted",
            "ticket_title", "ticket_status", "ticket_priority",
            "ticket_category_name",
        ]
        # Model UniqueConstraint includes condition on is_deleted (read-only).
        # DRF's auto validator breaks partial updates with KeyError; create
        # duplicates are validated explicitly below and enforced by DB.
        validators = []

    def get_ticket_display(self, obj):
        return f"#{obj.ticket_id}"

    def validate(self, attrs):
        if self.instance is None:
            problem = attrs.get("problem")
            ticket = attrs.get("ticket")
            if problem and ticket and ProblemTicketLink.objects.filter(
                problem=problem, ticket=ticket, is_deleted=False,
            ).exists():
                raise serializers.ValidationError(
                    "This ticket is already linked to the problem."
                )
        return attrs


class ProblemKbArticleLinkSerializer(serializers.ModelSerializer):
    """Links a KB article to a Problem, exposing article metadata for display."""

    article_title = serializers.CharField(source="article.title", read_only=True)
    article_status = serializers.CharField(source="article.status", read_only=True)
    article_slug = serializers.CharField(source="article.slug", read_only=True)

    class Meta:
        model = ProblemKbArticleLink
        fields = [
            "id", "problem", "article", "article_title", "article_status",
            "article_slug", "relation_type", "relevance", "note",
            "linked_by", "linked_at", "is_deleted",
        ]
        read_only_fields = [
            "id", "linked_by", "linked_at", "is_deleted",
            "article_title", "article_status", "article_slug",
        ]

    def validate(self, attrs):
        if self.instance is None:
            problem = attrs.get("problem")
            article = attrs.get("article")
            if problem and article and ProblemKbArticleLink.objects.filter(
                problem=problem, article=article, is_deleted=False,
            ).exists():
                raise serializers.ValidationError(
                    {"article": "This KB article is already linked to the problem."}
                )
        return attrs


def _link_serializer(model, target_field, target_model, label):
    model_cls = model

    class _Serializer(serializers.ModelSerializer):
        target_display = serializers.SerializerMethodField()

        class Meta:
            model = model_cls
            fields = [
                "id", "problem", target_field, "target_display",
                "impact_type", "role", "confidence", "notes",
                "created_by", "created_at", "is_deleted",
            ]
            read_only_fields = [
                "id", "created_by", "created_at", "is_deleted",
            ]

        def get_target_display(self, obj):
            target = getattr(obj, target_field)
            if target is None:
                return None
            return getattr(target, "ci_number", None) or \
                getattr(target, "asset_tag", None) or \
                getattr(target, "name", None) or str(target.pk)

        def validate(self, attrs):
            if self.instance is None:
                problem = attrs.get("problem")
                target = attrs.get(target_field)
                if problem and target and model.objects.filter(
                    problem=problem, **{target_field: target, "is_deleted": False},
                ).exists():
                    raise serializers.ValidationError(
                        "This object is already linked to the problem."
                    )
            return attrs

    _Serializer.__name__ = f"Problem{label}LinkSerializer"
    return _Serializer


ProblemConfigurationItemLinkSerializer = _link_serializer(
    ProblemConfigurationItemLink, "configuration_item",
    ConfigurationItem, "ConfigurationItem",
)
ProblemServiceLinkSerializer = _link_serializer(
    ProblemServiceLink, "service", ServiceCatalogueItem, "Service",
)
ProblemAssetLinkSerializer = _link_serializer(
    ProblemAssetLink, "asset", Asset, "Asset",
)
ProblemSoftwareProductLinkSerializer = _link_serializer(
    ProblemSoftwareProductLink, "software_product",
    SoftwareProduct, "SoftwareProduct",
)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class ProblemTaskSerializer(serializers.ModelSerializer):
    is_overdue = serializers.BooleanField(read_only=True)
    assigned_to_username = serializers.CharField(
        source="assigned_to.username", read_only=True,
    )
    completed_by_username = serializers.CharField(
        source="completed_by.username", read_only=True,
    )
    status = serializers.CharField(read_only=True)
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProblemTask
        fields = [
            "id", "problem", "sequence", "title", "description", "task_type",
            "status", "assigned_to", "assigned_to_username",
            "assigned_group", "due_at", "started_at", "completed_at",
            "completed_by", "completed_by_username", "required",
            "blocks_resolution", "evidence_required", "completion_note",
            "version", "is_overdue", "is_deleted",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "sequence", "status", "started_at", "completed_at",
            "completed_by", "completion_note", "version", "is_deleted",
            "created_by", "created_at", "updated_at",
        ]


# ---------------------------------------------------------------------------
# History (read-only)
# ---------------------------------------------------------------------------

class ProblemHistorySerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(
        source="actor.username", read_only=True,
    )

    class Meta:
        model = ProblemHistory
        fields = [
            "id", "problem", "task", "actor", "actor_username", "event_type",
            "previous_status", "new_status", "detail", "changed_fields",
            "created_at",
        ]
        read_only_fields = fields
