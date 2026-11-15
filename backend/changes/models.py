"""Change Management domain models.

Implements the full IT Change lifecycle:

Draft → Submitted → Risk Assessment → Technical Review → Approval Required
→ Approved → Scheduled → Implementation In Progress → Validation → Completed
→ Post-Implementation Review → Closed

Plus Rejected, Cancelled, On Hold, Failed, Rolled Back,
Emergency Retrospective Required.

Standard, Normal and Emergency change types are supported with appropriate
approval, risk, scheduling, implementation, rollback and post-implementation
review controls. All mutations are transactional and auditable.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User, Department
from assets.models import Asset
from common.models import SoftDeleteModel
from services.models import ServiceCatalogueItem
from tickets.models import Ticket


class ChangeRequest(SoftDeleteModel):
    """A requested change to the production environment."""

    CHANGE_TYPE_CHOICES = [
        ("standard", "Standard"),
        ("normal", "Normal"),
        ("emergency", "Emergency"),
    ]

    CATEGORY_CHOICES = [
        ("application", "Application"),
        ("infrastructure", "Infrastructure"),
        ("network", "Network"),
        ("security", "Security"),
        ("database", "Database"),
        ("hardware", "Hardware"),
        ("software", "Software"),
        ("access", "Access"),
        ("configuration", "Configuration"),
        ("maintenance", "Maintenance"),
        ("deployment", "Deployment"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("risk_assessment", "Risk Assessment"),
        ("technical_review", "Technical Review"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("scheduled", "Scheduled"),
        ("in_progress", "Implementation In Progress"),
        ("validation", "Validation"),
        ("completed", "Completed"),
        ("pir_required", "Post-Implementation Review Required"),
        ("closed", "Closed"),
        ("on_hold", "On Hold"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
        ("failed", "Failed"),
        ("rolled_back", "Rolled Back"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("urgent", "Urgent"),
        ("emergency", "Emergency"),
    ]

    RISK_LEVEL_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    change_number = models.CharField(max_length=30, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    business_reason = models.TextField(blank=True, default="")
    change_type = models.CharField(max_length=20, choices=CHANGE_TYPE_CHOICES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    status = models.CharField(
        max_length=40, choices=STATUS_CHOICES, default="draft", db_index=True
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default="normal"
    )
    risk_level = models.CharField(
        max_length=20, choices=RISK_LEVEL_CHOICES, blank=True, default=""
    )
    calculated_risk_score = models.PositiveIntegerField(default=0)

    requester = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_requests_requested"
    )
    change_owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_requests_owned"
    )
    implementation_lead = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_requests_leading",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_requests",
    )

    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)

    expected_downtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    actual_downtime_minutes = models.PositiveIntegerField(null=True, blank=True)

    customer_impact = models.TextField(blank=True, default="")
    business_impact = models.TextField(blank=True, default="")
    technical_impact = models.TextField(blank=True, default="")

    scope = models.TextField(blank=True, default="")
    out_of_scope = models.TextField(blank=True, default="")

    implementation_plan = models.TextField(blank=True, default="")
    validation_plan = models.TextField(blank=True, default="")
    rollback_plan = models.TextField(blank=True, default="")
    communication_plan = models.TextField(blank=True, default="")

    test_evidence_summary = models.TextField(blank=True, default="")
    success_criteria = models.TextField(blank=True, default="")
    closure_summary = models.TextField(blank=True, default="")

    failure_reason = models.TextField(blank=True, default="")
    rollback_reason = models.TextField(blank=True, default="")
    emergency_reason = models.TextField(blank=True, default="")

    approval_required = models.BooleanField(default=True)
    current_approver = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_requests_approving",
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change_number"], name="change_number_idx"),
            models.Index(fields=["status"], name="change_status_idx"),
            models.Index(fields=["change_type"], name="change_type_idx"),
            models.Index(fields=["priority"], name="change_priority_idx"),
            models.Index(fields=["risk_level"], name="change_risk_level_idx"),
            models.Index(fields=["requester", "status"], name="change_requester_status_idx"),
            models.Index(fields=["planned_start"], name="change_planned_start_idx"),
            models.Index(fields=["planned_end"], name="change_planned_end_idx"),
            models.Index(fields=["department"], name="change_department_idx"),
        ]

    def __str__(self):
        return f"{self.change_number} - {self.title} [{self.status}]"


class ChangeTemplate(SoftDeleteModel):
    """Pre-approved, repeatable low-risk standard change template."""

    APPROVAL_POLICY_CHOICES = [
        ("auto_approve", "Auto-approve"),
        ("manager_approve", "Manager approval"),
        ("technical_review_then_approve", "Technical review then approval"),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    title_template = models.CharField(max_length=255, blank=True, default="")
    description_template = models.TextField(blank=True, default="")
    category = models.CharField(max_length=20, choices=ChangeRequest.CATEGORY_CHOICES)
    default_priority = models.CharField(
        max_length=20, choices=ChangeRequest.PRIORITY_CHOICES, default="normal"
    )
    default_risk_level = models.CharField(
        max_length=20, choices=ChangeRequest.RISK_LEVEL_CHOICES, blank=True, default=""
    )
    scope = models.TextField(blank=True, default="")
    implementation_plan = models.TextField(blank=True, default="")
    validation_plan = models.TextField(blank=True, default="")
    rollback_plan = models.TextField(blank=True, default="")
    communication_plan = models.TextField(blank=True, default="")
    expected_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    maximum_downtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    required_roles = models.JSONField(default=list, blank=True)
    required_task_definitions = models.JSONField(default=list, blank=True)
    affected_service_rules = models.JSONField(default=list, blank=True)
    approval_policy = models.JSONField(default=dict, blank=True)
    is_preapproved = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_templates_owned"
    )
    version = models.PositiveIntegerField(default=1)
    review_interval_days = models.PositiveIntegerField(default=90)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    next_review_due = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_templates_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active"], name="template_active_idx"),
            models.Index(fields=["category"], name="change_template_category_idx"),
            models.Index(fields=["next_review_due"], name="template_review_due_idx"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class ChangeTask(models.Model):
    """An individual implementation task within a change."""

    TASK_TYPE_CHOICES = [
        ("planning", "Planning"),
        ("technical_review", "Technical Review"),
        ("testing", "Testing"),
        ("backup", "Backup"),
        ("communication", "Communication"),
        ("implementation", "Implementation"),
        ("validation", "Validation"),
        ("rollback", "Rollback"),
        ("monitoring", "Monitoring"),
        ("documentation", "Documentation"),
        ("other", "Other"),
    ]

    TASK_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("ready", "Ready"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("blocked", "Blocked"),
        ("skipped", "Skipped"),
        ("cancelled", "Cancelled"),
        ("failed", "Failed"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="tasks"
    )
    sequence = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    task_type = models.CharField(max_length=20, choices=TASK_TYPE_CHOICES)
    assigned_to = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_tasks_assigned",
    )
    status = models.CharField(
        max_length=20, choices=TASK_STATUS_CHOICES, default="pending", db_index=True
    )
    required = models.BooleanField(default=True)
    blocks_implementation = models.BooleanField(default=False)
    blocks_completion = models.BooleanField(default=False)
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    completion_note = models.TextField(blank=True, default="")
    evidence_required = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sequence", "id"]
        unique_together = [("change", "sequence")]
        indexes = [
            models.Index(fields=["status"], name="task_status_idx"),
            models.Index(fields=["assigned_to", "status"], name="task_assignee_status_idx"),
            models.Index(fields=["planned_start"], name="task_planned_start_idx"),
            models.Index(fields=["change"], name="task_change_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} - Task {self.sequence}: {self.title}"


class ChangeHistory(models.Model):
    """Immutable, append-only history of a change and its tasks."""

    EVENT_TYPE_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("submitted", "Submitted"),
        ("risk_calculated", "Risk Calculated"),
        ("technical_review_started", "Technical Review Started"),
        ("technical_review_completed", "Technical Review Completed"),
        ("approval_requested", "Approval Requested"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("returned_for_correction", "Returned for Correction"),
        ("scheduled", "Scheduled"),
        ("rescheduled", "Rescheduled"),
        ("conflict_detected", "Conflict Detected"),
        ("conflict_overridden", "Conflict Overridden"),
        ("implementation_started", "Implementation Started"),
        ("task_started", "Task Started"),
        ("task_completed", "Task Completed"),
        ("task_failed", "Task Failed"),
        ("validation_started", "Validation Started"),
        ("validation_passed", "Validation Passed"),
        ("validation_failed", "Validation Failed"),
        ("rollback_started", "Rollback Started"),
        ("rollback_completed", "Rollback Completed"),
        ("failed", "Failed"),
        ("completed", "Completed"),
        ("pir_requested", "PIR Requested"),
        ("pir_completed", "PIR Completed"),
        ("closed", "Closed"),
        ("cancelled", "Cancelled"),
        ("communication_sent", "Communication Sent"),
        ("attachment_added", "Attachment Added"),
        ("attachment_deleted", "Attachment Deleted"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="history"
    )
    task = models.ForeignKey(
        ChangeTask,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="history",
    )
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_history_entries",
    )
    event_type = models.CharField(max_length=40, choices=EVENT_TYPE_CHOICES)
    previous_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change"], name="history_change_idx"),
            models.Index(fields=["event_type"], name="history_event_type_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} - {self.event_type}"


class ChangeAssetImpact(models.Model):
    """An asset affected by a change."""

    IMPACT_TYPE_CHOICES = [
        ("configuration", "Configuration"),
        ("software_update", "Software Update"),
        ("hardware_change", "Hardware Change"),
        ("network_change", "Network Change"),
        ("security_change", "Security Change"),
        ("maintenance", "Maintenance"),
        ("replacement", "Replacement"),
        ("retirement", "Retirement"),
        ("other", "Other"),
    ]

    VALIDATION_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("passed", "Passed"),
        ("failed", "Failed"),
        ("not_applicable", "Not Applicable"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="asset_impacts"
    )
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="change_impacts")
    impact_type = models.CharField(max_length=20, choices=IMPACT_TYPE_CHOICES)
    expected_state_before = models.CharField(max_length=200, blank=True, default="")
    expected_state_after = models.CharField(max_length=200, blank=True, default="")
    actual_state_after = models.CharField(max_length=200, blank=True, default="")
    downtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    validation_status = models.CharField(
        max_length=20, choices=VALIDATION_STATUS_CHOICES, default="pending"
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        unique_together = [("change", "asset")]
        indexes = [
            models.Index(fields=["change"], name="assetimpact_change_idx"),
            models.Index(fields=["asset"], name="assetimpact_asset_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} impacts {self.asset.asset_tag}"


class ChangeServiceImpact(models.Model):
    """A service affected by a change."""

    IMPACT_LEVEL_CHOICES = [
        ("none", "None"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="service_impacts"
    )
    service_catalogue_item = models.ForeignKey(
        ServiceCatalogueItem,
        on_delete=models.PROTECT,
        related_name="change_service_impacts",
    )
    service_name_snapshot = models.CharField(max_length=200, blank=True, default="")
    impact_level = models.CharField(
        max_length=20, choices=IMPACT_LEVEL_CHOICES, default="none"
    )
    expected_outage = models.TextField(blank=True, default="")
    expected_degradation = models.TextField(blank=True, default="")
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["change"], name="serviceimpact_change_idx"),
            models.Index(fields=["service_catalogue_item"], name="serviceimpact_service_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} impacts service {self.service_catalogue_item_id}"


class ChangeDependency(models.Model):
    """Dependency between two changes."""

    DEPENDENCY_TYPE_CHOICES = [
        ("blocks", "Blocks"),
        ("requires", "Requires"),
        ("related", "Related"),
        ("supersedes", "Supersedes"),
        ("conflicts_with", "Conflicts With"),
    ]

    predecessor = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="dependencies_as_predecessor"
    )
    successor = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="dependencies_as_successor"
    )
    dependency_type = models.CharField(max_length=20, choices=DEPENDENCY_TYPE_CHOICES)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_dependencies_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("predecessor", "successor")]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(predecessor=models.F("successor")),
                name="change_dependency_no_self_ref",
            ),
        ]
        indexes = [
            models.Index(fields=["predecessor"], name="dependency_predecessor_idx"),
            models.Index(fields=["successor"], name="dependency_successor_idx"),
        ]

    def __str__(self):
        return f"{self.predecessor.change_number} {self.dependency_type} {self.successor.change_number}"


class ChangeRiskAssessment(models.Model):
    """Deterministic risk assessment for a change."""

    RISK_LEVEL_CHOICES = ChangeRequest.RISK_LEVEL_CHOICES

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="risk_assessments"
    )
    assessed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="risk_assessments_assessed",
    )
    assessment_version = models.PositiveIntegerField(default=1)

    service_impact_score = models.PositiveIntegerField(default=0)
    user_impact_score = models.PositiveIntegerField(default=0)
    complexity_score = models.PositiveIntegerField(default=0)
    reversibility_score = models.PositiveIntegerField(default=0)
    test_coverage_score = models.PositiveIntegerField(default=0)
    implementation_experience_score = models.PositiveIntegerField(default=0)
    timing_risk_score = models.PositiveIntegerField(default=0)
    dependency_risk_score = models.PositiveIntegerField(default=0)
    security_risk_score = models.PositiveIntegerField(default=0)
    data_integrity_risk_score = models.PositiveIntegerField(default=0)

    total_score = models.PositiveIntegerField(default=0)
    calculated_level = models.CharField(
        max_length=20, choices=RISK_LEVEL_CHOICES, blank=True, default=""
    )
    override_level = models.CharField(
        max_length=20, choices=RISK_LEVEL_CHOICES, blank=True, default=""
    )
    override_reason = models.TextField(blank=True, default="")
    overridden_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="risk_assessments_overridden",
    )
    assessed_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assessment_version", "-assessed_at"]
        indexes = [
            models.Index(fields=["change"], name="riskassessment_change_idx"),
            models.Index(fields=["calculated_level"], name="riskassessment_level_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} risk v{self.assessment_version}"


class ChangeApproval(models.Model):
    """An approval decision on a change."""

    APPROVAL_LEVEL_CHOICES = [
        ("technical", "Technical"),
        ("manager", "Manager"),
        ("system_admin", "System Admin"),
        ("security", "Security"),
        ("business_owner", "Business Owner"),
        ("emergency_retrospective", "Emergency Retrospective"),
    ]

    APPROVAL_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
        ("superseded", "Superseded"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="approvals"
    )
    approval_level = models.CharField(max_length=24, choices=APPROVAL_LEVEL_CHOICES)
    status = models.CharField(
        max_length=20, choices=APPROVAL_STATUS_CHOICES, default="pending", db_index=True
    )
    requested_from = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_approvals_requested_from",
    )
    requester = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_approvals_requested_by"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_approvals_decided_by",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True, default="")
    change_version = models.PositiveIntegerField(default=1)
    risk_level_snapshot = models.CharField(max_length=20, blank=True, default="")
    planned_window_snapshot = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change"], name="approval_change_idx"),
            models.Index(fields=["status"], name="approval_status_idx"),
            models.Index(fields=["approval_level"], name="approval_level_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} {self.approval_level} {self.status}"


class ChangeReviewMeeting(models.Model):
    """CAB-like review meeting for changes."""

    MEETING_STATUS_CHOICES = [
        ("planned", "Planned"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    title = models.CharField(max_length=200)
    meeting_date = models.DateTimeField()
    chair = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_review_meetings_chaired"
    )
    attendees = models.ManyToManyField(User, blank=True, related_name="change_review_attendances")
    status = models.CharField(
        max_length=20, choices=MEETING_STATUS_CHOICES, default="planned"
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_review_meetings_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-meeting_date"]
        indexes = [
            models.Index(fields=["status"], name="reviewmeeting_status_idx"),
            models.Index(fields=["meeting_date"], name="reviewmeeting_date_idx"),
        ]

    def __str__(self):
        return f"Review Meeting {self.title} ({self.status})"


class ChangeReviewItem(models.Model):
    """A change item within a review meeting."""

    REVIEW_DECISION_CHOICES = [
        ("pending", "Pending"),
        ("recommended", "Recommended"),
        ("not_recommended", "Not Recommended"),
        ("deferred", "Deferred"),
        ("information_required", "Information Required"),
    ]

    meeting = models.ForeignKey(
        ChangeReviewMeeting, on_delete=models.CASCADE, related_name="review_items"
    )
    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="review_items"
    )
    sequence = models.PositiveIntegerField(default=0)
    decision = models.CharField(
        max_length=20, choices=REVIEW_DECISION_CHOICES, default="pending"
    )
    decision_reason = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_review_decisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sequence", "id"]
        unique_together = [("meeting", "change")]
        indexes = [
            models.Index(fields=["meeting"], name="reviewitem_meeting_idx"),
            models.Index(fields=["decision"], name="reviewitem_decision_idx"),
        ]

    def __str__(self):
        return f"{self.meeting.title} - {self.change.change_number} ({self.decision})"


class MaintenanceWindow(SoftDeleteModel):
    """A scheduled maintenance window in which changes may occur."""

    WINDOW_TYPE_CHOICES = [
        ("one_time", "One Time"),
        ("recurring", "Recurring"),
        ("emergency", "Emergency"),
    ]

    WINDOW_STATUS_CHOICES = [
        ("draft", "Draft"),
        ("approved", "Approved"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, default="")
    window_type = models.CharField(max_length=20, choices=WINDOW_TYPE_CHOICES)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    timezone_name = models.CharField(max_length=60, default="UTC")
    recurrence_rule = models.TextField(
        blank=True, default="",
        help_text="Bounded recurrence description (e.g. weekly Monday 02:00 for 2 hours).",
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="maintenance_windows",
    )
    service = models.ForeignKey(
        ServiceCatalogueItem, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="maintenance_windows",
    )
    status = models.CharField(
        max_length=20, choices=WINDOW_STATUS_CHOICES, default="draft", db_index=True
    )
    maximum_parallel_changes = models.PositiveIntegerField(default=1)
    blackout = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="maintenance_windows_created"
    )
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="maintenance_windows_approved",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["start_at"], name="window_start_idx"),
            models.Index(fields=["end_at"], name="window_end_idx"),
            models.Index(fields=["status"], name="window_status_idx"),
            models.Index(fields=["department"], name="window_department_idx"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name} ({self.status})"


class ChangeConflict(models.Model):
    """A detected scheduling conflict between two changes."""

    CONFLICT_TYPE_CHOICES = [
        ("asset_overlap", "Asset Overlap"),
        ("service_overlap", "Service Overlap"),
        ("department_overlap", "Department Overlap"),
        ("implementer_overlap", "Implementer Overlap"),
        ("dependency_order", "Dependency Order"),
        ("window_capacity", "Window Capacity"),
        ("blackout_window", "Blackout Window"),
        ("high_risk_overlap", "High Risk Overlap"),
        ("manual", "Manual"),
    ]

    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    CONFLICT_STATUS_CHOICES = [
        ("open", "Open"),
        ("acknowledged", "Acknowledged"),
        ("resolved", "Resolved"),
        ("accepted", "Accepted"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="conflicts_as_primary"
    )
    conflicting_change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="conflicts_as_conflicting"
    )
    conflict_type = models.CharField(max_length=20, choices=CONFLICT_TYPE_CHOICES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    status = models.CharField(
        max_length=20, choices=CONFLICT_STATUS_CHOICES, default="open", db_index=True
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_conflicts_acknowledged",
    )
    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_conflicts_resolved",
    )
    fingerprint = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-detected_at"]
        unique_together = [("change", "conflicting_change", "conflict_type")]
        indexes = [
            models.Index(fields=["change"], name="conflict_change_idx"),
            models.Index(fields=["conflicting_change"], name="chg_conflict_change2_idx"),
            models.Index(fields=["status"], name="conflict_status_idx"),
            models.Index(fields=["severity"], name="conflict_severity_idx"),
            models.Index(fields=["fingerprint"], name="conflict_fingerprint_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} conflicts {self.conflicting_change.change_number} ({self.conflict_type})"


class ChangeAttachment(models.Model):
    """An attachment uploaded for a change or task."""

    DOCUMENT_TYPE_CHOICES = [
        ("implementation_plan", "Implementation Plan"),
        ("test_evidence", "Test Evidence"),
        ("rollback_plan", "Rollback Plan"),
        ("approval_evidence", "Approval Evidence"),
        ("backup_evidence", "Backup Evidence"),
        ("communication", "Communication"),
        ("validation_evidence", "Validation Evidence"),
        ("pir_evidence", "PIR Evidence"),
        ("vendor_document", "Vendor Document"),
        ("other", "Other"),
    ]

    ATTACHMENT_STATUS_CHOICES = [
        ("active", "Active"),
        ("superseded", "Superseded"),
        ("archived", "Archived"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="attachments"
    )
    task = models.ForeignKey(
        ChangeTask, null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments",
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_attachments_uploaded"
    )
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to="change_attachments/%Y/%m/")
    content_type = models.CharField(max_length=120, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=ATTACHMENT_STATUS_CHOICES, default="active"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change"], name="attachment_change_idx"),
            models.Index(fields=["task"], name="attachment_task_idx"),
            models.Index(fields=["document_type"], name="attachment_type_idx"),
            models.Index(fields=["status"], name="attachment_status_idx"),
        ]

    def __str__(self):
        return f"{self.original_filename} on {self.change.change_number}"


class ChangeStakeholder(models.Model):
    """A stakeholder of a change."""

    STAKEHOLDER_TYPE_CHOICES = [
        ("requester", "Requester"),
        ("change_owner", "Change Owner"),
        ("implementer", "Implementer"),
        ("approver", "Approver"),
        ("service_owner", "Service Owner"),
        ("business_owner", "Business Owner"),
        ("technical_contact", "Technical Contact"),
        ("observer", "Observer"),
    ]

    NOTIFICATION_LEVEL_CHOICES = [
        ("all_updates", "All Updates"),
        ("major_updates", "Major Updates"),
        ("outage_only", "Outage Only"),
        ("none", "None"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="stakeholders"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="change_stakeholders")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_stakeholders",
    )
    stakeholder_type = models.CharField(max_length=20, choices=STAKEHOLDER_TYPE_CHOICES)
    notification_level = models.CharField(
        max_length=20, choices=NOTIFICATION_LEVEL_CHOICES, default="all_updates"
    )
    added_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_stakeholders_added"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = [("change", "user", "stakeholder_type")]
        indexes = [
            models.Index(fields=["change"], name="stakeholder_change_idx"),
            models.Index(fields=["user"], name="stakeholder_user_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} stakeholder {self.user.email} ({self.stakeholder_type})"


class ChangeCommunication(models.Model):
    """A communication sent about a change."""

    COMMUNICATION_TYPE_CHOICES = [
        ("planned_outage", "Planned Outage"),
        ("implementation_start", "Implementation Start"),
        ("implementation_complete", "Implementation Complete"),
        ("implementation_failed", "Implementation Failed"),
        ("rollback", "Rollback"),
        ("service_restored", "Service Restored"),
        ("emergency_notice", "Emergency Notice"),
        ("reminder", "Reminder"),
        ("other", "Other"),
    ]

    AUDIENCE_CHOICES = [
        ("stakeholders", "Stakeholders"),
        ("affected_department", "Affected Department"),
        ("affected_service_users", "Affected Service Users"),
        ("it_staff", "IT Staff"),
        ("custom", "Custom"),
    ]

    COMMUNICATION_STATUS_CHOICES = [
        ("draft", "Draft"),
        ("scheduled", "Scheduled"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="communications"
    )
    communication_type = models.CharField(max_length=24, choices=COMMUNICATION_TYPE_CHOICES)
    audience = models.CharField(max_length=24, choices=AUDIENCE_CHOICES)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_communications_sent",
    )
    status = models.CharField(
        max_length=20, choices=COMMUNICATION_STATUS_CHOICES, default="draft"
    )
    failure_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change"], name="communication_change_idx"),
            models.Index(fields=["status"], name="communication_status_idx"),
            models.Index(fields=["scheduled_for"], name="communication_scheduled_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} - {self.subject}"


class ChangeImplementation(models.Model):
    """The implementation record for a change."""

    IMPLEMENTATION_STATUS_CHOICES = [
        ("in_progress", "In Progress"),
        ("validation", "Validation"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("rolled_back", "Rolled Back"),
        ("partially_successful", "Partially Successful"),
    ]

    IMPLEMENTATION_OUTCOME_CHOICES = [
        ("successful", "Successful"),
        ("successful_with_issues", "Successful with Issues"),
        ("failed", "Failed"),
        ("rolled_back", "Rolled Back"),
        ("partial", "Partial"),
        ("cancelled", "Cancelled"),
    ]

    change = models.OneToOneField(
        ChangeRequest, on_delete=models.CASCADE, related_name="implementation"
    )
    started_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_implementations_started",
    )
    completed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_implementations_completed",
    )
    status = models.CharField(
        max_length=20, choices=IMPLEMENTATION_STATUS_CHOICES, default="in_progress"
    )
    outcome = models.CharField(
        max_length=24, choices=IMPLEMENTATION_OUTCOME_CHOICES, blank=True, default=""
    )
    implementation_notes = models.TextField(blank=True, default="")
    validation_result = models.TextField(blank=True, default="")
    rollback_required = models.BooleanField(default=False)
    rollback_started_at = models.DateTimeField(null=True, blank=True)
    rollback_completed_at = models.DateTimeField(null=True, blank=True)
    rollback_completed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_implementations_rollback_completed",
    )
    actual_downtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    related_incident_ticket = models.ForeignKey(
        Ticket, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_implementations_linked",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change"], name="implementation_change_idx"),
            models.Index(fields=["status"], name="implementation_status_idx"),
            models.Index(fields=["outcome"], name="implementation_outcome_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} implementation ({self.status})"


class PostImplementationReview(models.Model):
    """Post-implementation review for a change."""

    PIR_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("scheduled", "Scheduled"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("waived", "Waived"),
    ]

    PIR_OUTCOME_CHOICES = [
        ("successful", "Successful"),
        ("successful_with_issues", "Successful with Issues"),
        ("failed", "Failed"),
        ("rolled_back", "Rolled Back"),
        ("inconclusive", "Inconclusive"),
    ]

    change = models.OneToOneField(
        ChangeRequest, on_delete=models.CASCADE, related_name="pir"
    )
    status = models.CharField(
        max_length=20, choices=PIR_STATUS_CHOICES, default="pending", db_index=True
    )
    reviewer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="pirs_reviewed",
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=24, choices=PIR_OUTCOME_CHOICES, blank=True, default="")
    objectives_met = models.TextField(blank=True, default="")
    validation_successful = models.BooleanField(default=False)
    unexpected_impact = models.TextField(blank=True, default="")
    downtime_within_estimate = models.BooleanField(default=False)
    rollback_used = models.BooleanField(default=False)
    incident_created = models.BooleanField(default=False)
    lessons_learned = models.TextField(blank=True, default="")
    follow_up_actions = models.TextField(blank=True, default="")
    knowledge_article = models.ForeignKey(
        "assets.KnowledgeBaseArticle", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_pirs",
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="change_pirs_reviewed_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["change"], name="pir_change_idx"),
            models.Index(fields=["status"], name="pir_status_idx"),
            models.Index(fields=["reviewer"], name="pir_reviewer_idx"),
        ]

    def __str__(self):
        return f"PIR for {self.change.change_number} ({self.status})"


class ChangeTicketLink(models.Model):
    """A link between a change and a ticket."""

    RELATION_TYPE_CHOICES = [
        ("requested_by", "Requested By"),
        ("implements_fix_for", "Implements Fix For"),
        ("caused_incident", "Caused Incident"),
        ("related", "Related"),
        ("follow_up", "Follow Up"),
        ("validation_issue", "Validation Issue"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="ticket_links"
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="change_links"
    )
    relation_type = models.CharField(max_length=24, choices=RELATION_TYPE_CHOICES)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_ticket_links_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("change", "ticket", "relation_type")]
        indexes = [
            models.Index(fields=["change"], name="ticketlink_change_idx"),
            models.Index(fields=["ticket"], name="ticketlink_ticket_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} {self.relation_type} {self.ticket_id}"


class ChangeKnowledgeLink(models.Model):
    """A link between a change and a knowledge base article."""

    RELATION_TYPE_CHOICES = [
        ("implementation_reference", "Implementation Reference"),
        ("rollback_reference", "Rollback Reference"),
        ("validation_reference", "Validation Reference"),
        ("lesson_learned", "Lesson Learned"),
        ("known_issue", "Known Issue"),
        ("standard_procedure", "Standard Procedure"),
    ]

    change = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="knowledge_links"
    )
    article = models.ForeignKey(
        "assets.KnowledgeBaseArticle", on_delete=models.CASCADE,
        related_name="change_links",
    )
    relation_type = models.CharField(max_length=24, choices=RELATION_TYPE_CHOICES)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="change_knowledge_links_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("change", "article")]
        indexes = [
            models.Index(fields=["change"], name="knowledgelink_change_idx"),
            models.Index(fields=["article"], name="knowledgelink_article_idx"),
        ]

    def __str__(self):
        return f"{self.change.change_number} links KB article {self.article_id}"
