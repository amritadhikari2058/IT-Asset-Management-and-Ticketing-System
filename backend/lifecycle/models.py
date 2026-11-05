"""Employee Lifecycle: onboarding, offboarding, and transfer cases.

Integrates with existing modules without modifying them:
- accounts.User / Department (employee, coordinator, heads)
- assets.Asset / Assignment (asset assignment & recovery)
- tickets.Ticket / services.ServiceRequest (automation targets)
- common.{Notification, AuditLog, BackgroundTaskRun, SoftDeleteModel}

Design notes:
- Case number is generated server-side (ONB-/OFF-/TRF- prefix + year +
  sequence), unique, concurrency-safe, never reusable.
- Case status transitions are enforced by the service layer (never via a
  raw status PATCH).
- Soft-delete fields follow the project SoftDeleteModel convention so a
  deleted case can never leak tasks/attachments/history through normal
  querysets.
- All history rows are append-only; nothing is editable/deletable via API.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from common.models import SoftDeleteModel


CASE_TYPE_CHOICES = [
    ("onboarding", "Onboarding"),
    ("offboarding", "Offboarding"),
    ("transfer", "Transfer / Role Change"),
]

CASE_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("planned", "Planned"),
    ("in_progress", "In Progress"),
    ("ready_for_employee", "Ready for Employee"),
    ("employee_started", "Employee Started"),
    ("awaiting_asset_return", "Awaiting Asset Return"),
    ("awaiting_access_revocation", "Awaiting Access Revocation"),
    ("ready_for_closure", "Ready for Closure"),
    ("access_updated", "Access Updated"),
    ("asset_changes_completed", "Asset Changes Completed"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
    ("blocked", "Blocked"),
]

TERMINAL_STATUSES = ("completed", "cancelled")

SOURCE_CHOICES = [
    ("manual", "Manual"),
    ("service_request", "Service Request"),
    ("employee_created", "Employee Created"),
    ("department_transfer", "Department Transfer"),
    ("account_deactivation", "Account Deactivation"),
]

PRIORITY_CHOICES = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("urgent", "Urgent"),
]

TASK_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("blocked", "Blocked"),
    ("skipped", "Skipped"),
    ("cancelled", "Cancelled"),
]

AUTOMATION_STATUS_CHOICES = [
    ("not_applicable", "Not Applicable"),
    ("pending", "Pending"),
    ("running", "Running"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("manual_review", "Manual Review"),
]

AUTOMATION_TYPES = [
    ("none", "None"),
    ("create_service_request", "Create Service Request"),
    ("create_ticket", "Create Ticket"),
    ("assign_asset", "Assign Asset"),
    ("return_assets", "Return Assets"),
    ("deactivate_account", "Deactivate Account"),
    ("revoke_tokens", "Revoke Tokens"),
    ("notification", "Notification"),
]

TEMPLATE_ITEM_CATEGORY_CHOICES = [
    ("account", "Account"),
    ("email", "Email"),
    ("hardware", "Hardware"),
    ("software", "Software"),
    ("access", "Access"),
    ("network", "Network"),
    ("security", "Security"),
    ("training", "Training"),
    ("asset_return", "Asset Return"),
    ("data_transfer", "Data Transfer"),
    ("documentation", "Documentation"),
    ("other", "Other"),
]

RESPONSIBILITY_CHOICES = [
    ("it", "IT"),
    ("manager", "Manager"),
    ("employee", "Employee"),
    ("hr", "HR"),
    ("security", "Security"),
    ("other", "Other"),
]

DEFAULT_ASSIGNEE_ROLE_CHOICES = [
    ("system_admin", "System Admin"),
    ("it_manager", "IT Manager"),
    ("it_support", "IT Support"),
    ("employee", "Employee"),
    ("unassigned", "Unassigned"),
]

HISTORY_EVENT_CHOICES = [
    ("case_created", "Case Created"),
    ("case_updated", "Case Updated"),
    ("case_planned", "Case Planned"),
    ("case_started", "Case Started"),
    ("case_blocked", "Case Blocked"),
    ("case_unblocked", "Case Unblocked"),
    ("case_completed", "Case Completed"),
    ("case_cancelled", "Case Cancelled"),
    ("task_created", "Task Created"),
    ("task_assigned", "Task Assigned"),
    ("task_started", "Task Started"),
    ("task_completed", "Task Completed"),
    ("task_skipped", "Task Skipped"),
    ("task_blocked", "Task Blocked"),
    ("automation_started", "Automation Started"),
    ("automation_succeeded", "Automation Succeeded"),
    ("automation_failed", "Automation Failed"),
    ("asset_assigned", "Asset Assigned"),
    ("asset_returned", "Asset Returned"),
    ("account_deactivated", "Account Deactivated"),
    ("tokens_revoked", "Tokens Revoked"),
    ("notification_sent", "Notification Sent"),
]

ASSET_RESOLUTION_CHOICES = [
    ("pending", "Pending"),
    ("returned", "Returned"),
    ("lost", "Lost"),
    ("damaged", "Damaged"),
    ("transferred", "Transferred"),
    ("approved_exception", "Approved Exception"),
]


class LifecycleTemplate(SoftDeleteModel):
    """Reusable checklist template for a case type.

    Configuration only: changing a template never mutates existing cases.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=60, unique=True, db_index=True)
    case_type = models.CharField(
        max_length=20, choices=CASE_TYPE_CHOICES, db_index=True)
    description = models.TextField(blank=True, default="")
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_templates",
        help_text="Null = global template available to all departments.")
    is_global = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_templates_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["case_type", "name"]
        indexes = [
            models.Index(fields=["case_type", "is_active"], name="lt_case_active_idx"),
            models.Index(fields=["code"], name="lt_code_idx"),
            models.Index(fields=["department"], name="lt_dept_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["code"], name="lifecycle_template_code_unique"),
        ]
        permissions = [
            ("manage_lifecycle_template", "Can manage lifecycle templates"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class LifecycleTemplateItem(SoftDeleteModel):
    """One checklist item within a template.

    Copied into LifecycleTask rows at case creation; stable thereafter.
    """
    template = models.ForeignKey(
        LifecycleTemplate, on_delete=models.CASCADE,
        related_name="items")
    sequence = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(
        max_length=20, choices=TEMPLATE_ITEM_CATEGORY_CHOICES,
        default="other")
    responsibility = models.CharField(
        max_length=20, choices=RESPONSIBILITY_CHOICES, default="it")
    default_assignee_role = models.CharField(
        max_length=20, choices=DEFAULT_ASSIGNEE_ROLE_CHOICES,
        default="unassigned")
    required = models.BooleanField(default=True)
    due_offset_days = models.IntegerField(default=0,
        help_text="Days offset from the case effective/planned date.")
    blocks_completion = models.BooleanField(default=True,
        help_text="If required and not done, case cannot complete.")
    requires_evidence = models.BooleanField(default=False)
    automation_type = models.CharField(
        max_length=30, choices=AUTOMATION_TYPES, default="none")
    automation_config = models.JSONField(default=dict, blank=True)
    service_catalogue_item = models.ForeignKey(
        "services.ServiceCatalogueItem", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_template_items")
    asset_category = models.ForeignKey(
        "assets.AssetCategory", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_template_items")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["template", "sequence", "id"]
        indexes = [
            models.Index(fields=["template", "sequence"], name="lti_template_seq_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "sequence"],
                name="lifecycle_template_item_template_sequence_unique"),
        ]

    def __str__(self):
        return f"{self.template.code}#{self.sequence} {self.title}"


class LifecycleCase(SoftDeleteModel):
    """A single employee onboarding / offboarding / transfer case."""

    case_number = models.CharField(max_length=40, unique=True, db_index=True)
    case_type = models.CharField(max_length=20, choices=CASE_TYPE_CHOICES,
                                 db_index=True)
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=False, blank=False,
        on_delete=models.PROTECT,
        related_name="lifecycle_cases")
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_cases")
    previous_department = models.ForeignKey(
        "accounts.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_cases_previous")
    new_department = models.ForeignKey(
        "accounts.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_cases_new")
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_cases_initiated")
    assigned_coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_cases_coordinated")
    status = models.CharField(
        max_length=30, choices=CASE_STATUS_CHOICES, default="draft",
        db_index=True)
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium")
    planned_date = models.DateTimeField(null=True, blank=True)
    effective_date = models.DateTimeField(null=True, blank=True)
    completion_target = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    blocked_reason = models.TextField(blank=True, default="")
    source = models.CharField(
        max_length=30, choices=SOURCE_CHOICES, default="manual")
    source_reference = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    checklist_progress = models.PositiveIntegerField(default=0,
        help_text="Server-computed percentage (0-100). Client cannot write.")
    total_tasks = models.PositiveIntegerField(default=0)
    completed_tasks = models.PositiveIntegerField(default=0)
    overdue_tasks = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1,
        help_text="Optimistic concurrency token.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["case_type", "status"], name="lc_type_status_idx"),
            models.Index(fields=["employee", "status"], name="lc_employee_status_idx"),
            models.Index(fields=["department", "status"], name="lc_dept_status_idx"),
            models.Index(fields=["assigned_coordinator"], name="lc_coordinator_idx"),
            models.Index(fields=["effective_date"], name="lc_effective_date_idx"),
            models.Index(fields=["case_number"], name="lc_case_number_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                name="lifecycle_case_progress_range",
                condition=models.Q(checklist_progress__gte=0)
                & models.Q(checklist_progress__lte=100),
            ),
        ]
        permissions = [
            ("manage_lifecycle_case", "Can manage lifecycle cases"),
            ("view_lifecycle_case", "Can view lifecycle cases"),
        ]

    def __str__(self):
        return self.case_number

    def clean(self):
        super().clean()
        if (self.completion_target and self.planned_date
                and self.completion_target < self.planned_date):
            raise ValidationError(
                {"completion_target": "Completion target should not precede "
                                      "the planned date."})
        emp = self.employee
        if emp is not None and getattr(emp, "is_deleted", False):
            raise ValidationError(
                {"employee": "A soft-deleted employee cannot receive a case."})
        return self

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES


class LifecycleTask(SoftDeleteModel):
    """A single checklist task within a case.

    Copied from a template item at case creation; stable thereafter.
    """
    case = models.ForeignKey(
        LifecycleCase, on_delete=models.CASCADE,
        related_name="tasks")
    source_template_item = models.ForeignKey(
        LifecycleTemplateItem, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="generated_tasks")
    sequence = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(
        max_length=20, choices=TEMPLATE_ITEM_CATEGORY_CHOICES,
        default="other")
    responsibility = models.CharField(
        max_length=20, choices=RESPONSIBILITY_CHOICES, default="it")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_tasks")
    status = models.CharField(
        max_length=20, choices=TASK_STATUS_CHOICES, default="pending",
        db_index=True)
    required = models.BooleanField(default=True)
    blocks_completion = models.BooleanField(default=True)
    requires_evidence = models.BooleanField(default=False)
    due_date = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_tasks_completed")
    skipped_at = models.DateTimeField(null=True, blank=True)
    skipped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_tasks_skipped")
    skip_reason = models.TextField(blank=True, default="")
    blocked_reason = models.TextField(blank=True, default="")
    automation_type = models.CharField(
        max_length=30, choices=AUTOMATION_TYPES, default="none")
    automation_config = models.JSONField(default=dict, blank=True)
    automation_status = models.CharField(
        max_length=20, choices=AUTOMATION_STATUS_CHOICES,
        default="not_applicable")
    automation_error_summary = models.TextField(blank=True, default="")
    related_ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_tasks")
    related_service_request = models.ForeignKey(
        "services.ServiceRequest", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_tasks")
    related_asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_tasks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["case", "sequence", "id"]
        indexes = [
            models.Index(fields=["case", "status"], name="lt_case_status_idx"),
            models.Index(fields=["assigned_to", "status"], name="lt_assignee_status_idx"),
            models.Index(fields=["due_date"], name="lt_due_date_idx"),
            models.Index(fields=["automation_status"], name="lt_automation_status_idx"),
            models.Index(fields=["case", "sequence"], name="lt_case_seq_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "sequence"],
                name="lifecycle_task_case_sequence_unique"),
            models.CheckConstraint(
                name="lifecycle_task_skip_reason_when_skipped",
                condition=(
                    ~models.Q(status="skipped")
                    | models.Q(skip_reason__gt="")
                ),
            ),
        ]

    def __str__(self):
        return f"{self.case.case_number}#{self.sequence} {self.title}"

    def clean(self):
        super().clean()
        if self.status == "skipped" and not self.skip_reason.strip():
            raise ValidationError(
                {"skip_reason": "A skip reason is required when skipping a task."})
        if self.assigned_to_id and getattr(self.assigned_to, "is_deleted", False):
            raise ValidationError(
                {"assigned_to": "Cannot assign a task to a soft-deleted user."})
        return self

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LifecycleHistory(SoftDeleteModel):
    """Append-only, immutable history for a case and its tasks.

    Read-only via API; never soft/hard deleted through normal operations.
    """
    case = models.ForeignKey(
        LifecycleCase, on_delete=models.CASCADE,
        related_name="history_entries")
    task = models.ForeignKey(
        LifecycleTask, null=True, blank=True,
        on_delete=models.CASCADE, related_name="history_entries")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_history_entries")
    event_type = models.CharField(
        max_length=40, choices=HISTORY_EVENT_CHOICES, db_index=True)
    previous_status = models.CharField(max_length=30, blank=True, default="")
    new_status = models.CharField(max_length=30, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["case", "created_at"], name="lh_case_created_idx"),
            models.Index(fields=["task"], name="lh_task_idx"),
            models.Index(fields=["event_type"], name="lh_event_idx"),
        ]
        permissions = [
            ("view_lifecycle_history", "Can view lifecycle history"),
        ]

    def __str__(self):
        return f"{self.case.case_number} {self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("History rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("History rows cannot be deleted.")


class LifecycleAssetResolution(SoftDeleteModel):
    """Resolution of one Asset assigned to the case employee.

    Exactly one resolution per (case, asset). Tracks the offboarding/transfer
    disposition of each assigned asset.
    """
    case = models.ForeignKey(
        LifecycleCase, on_delete=models.CASCADE,
        related_name="asset_resolutions")
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT,
        related_name="lifecycle_resolutions")
    status = models.CharField(
        max_length=20, choices=ASSET_RESOLUTION_CHOICES, default="pending",
        db_index=True)
    resolution = models.CharField(
        max_length=20, choices=ASSET_RESOLUTION_CHOICES, default="pending",
        db_index=True)
    notes = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_asset_resolutions")
    related_task = models.ForeignKey(
        LifecycleTask, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="asset_resolutions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["case", "asset"]
        indexes = [
            models.Index(fields=["case", "status"], name="lar_case_status_idx"),
            models.Index(fields=["asset"], name="lar_asset_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "asset"],
                name="lifecycle_asset_resolution_case_asset_unique"),
        ]

    def __str__(self):
        return f"{self.case.case_number} {self.asset.asset_tag} -> {self.resolution}"


class LifecycleTaskEvidence(SoftDeleteModel):
    """Evidence uploaded for a task (handover form, return receipt, ...).

    Reuses the project attachment validation + safe download headers.
    """
    case = models.ForeignKey(
        LifecycleCase, on_delete=models.CASCADE,
        related_name="evidence")
    task = models.ForeignKey(
        LifecycleTask, null=True, blank=True,
        on_delete=models.CASCADE, related_name="evidence")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_evidence_uploaded")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(upload_to="lifecycle_evidence/%Y/%m/")
    content_type = models.CharField(max_length=120, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True, default="")
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lifecycle_evidence_deleted")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["case", "task"], name="lte_case_task_idx"),
            models.Index(fields=["uploaded_by"], name="lte_uploaded_by_idx"),
        ]

    def __str__(self):
        return f"{self.original_filename or self.pk} on {self.case.case_number}"
