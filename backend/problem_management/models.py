"""Problem Management domain models (PM1).

Gate 1 subset: Problem (+numbering), ticket/CI/service/asset/software links,
ProblemTask, ProblemHistory. Later gates append models via new migrations.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, models, transaction
from django.db.models import Q
from django.utils import timezone

from common.models import SoftDeleteModel


# ---------------------------------------------------------------------------
# Numbering (PRB-YYYY-NNNNNN): sequence row + select_for_update + bounded
# retry. No count()+1, no client control, no reuse, SQLite and PostgreSQL
# compatible.
# ---------------------------------------------------------------------------

class ProblemNumberSequence(models.Model):
    """Per-prefix monotonic counter (e.g. prefix ``PRB-2026-``)."""
    prefix = models.CharField(max_length=16, unique=True)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["prefix"]

    def __str__(self):
        return f"{self.prefix}{self.last_value:06d}"


def next_number(prefix, width=6):
    """Return the next sequence value for ``prefix`` under row lock.

    Bounded retry (50) around get_or_create races and transient SQLite
    shared-cache table locks (test databases); caller may be inside an outer
    atomic block (TestCase / service transaction) — a nested savepoint keeps
    the outer transaction usable after a failed attempt.
    """
    import time

    for attempt in range(50):
        try:
            with transaction.atomic():
                seq, _created = ProblemNumberSequence.objects.select_for_update().get_or_create(
                    prefix=prefix,
                )
                seq.last_value += 1
                seq.save(update_fields=["last_value"])
                return f"{prefix}{seq.last_value:0{width}d}"
        except IntegrityError:
            continue
        except OperationalError:
            time.sleep(min(0.005 * (attempt + 1), 0.25))
            continue
    raise ValidationError({"problem_number": "Number generation exhausted retries."})


def problem_year_prefix():
    return f"PRB-{timezone.localtime().year}-"


# ---------------------------------------------------------------------------
# Choices (full spec sets; used across all gates)
# ---------------------------------------------------------------------------

class Problem(SoftDeleteModel):
    PROBLEM_TYPE_CHOICES = [
        ("reactive", "Reactive"),
        ("proactive", "Proactive"),
        ("major_problem", "Major Problem"),
        ("recurring_incident", "Recurring Incident"),
        ("monitoring_pattern", "Monitoring Pattern"),
        ("risk_reduction", "Risk Reduction"),
        ("supplier_problem", "Supplier Problem"),
        ("software_problem", "Software Problem"),
        ("infrastructure_problem", "Infrastructure Problem"),
        ("process_problem", "Process Problem"),
        ("other", "Other"),
    ]
    SOURCE_CHOICES = [
        ("manual", "Manual"),
        ("ticket", "Ticket"),
        ("major_incident", "Major Incident"),
        ("monitoring", "Monitoring"),
        ("trend_analysis", "Trend Analysis"),
        ("cmdb", "CMDB"),
        ("change_review", "Change Review"),
        ("knowledge", "Knowledge"),
        ("supplier", "Supplier"),
        ("audit", "Audit"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("candidate", "Candidate"),
        ("draft", "Draft"),
        ("under_review", "Under Review"),
        ("accepted", "Accepted"),
        ("investigating", "Investigating"),
        ("root_cause_identified", "Root Cause Identified"),
        ("workaround_available", "Workaround Available"),
        ("known_error", "Known Error"),
        ("permanent_fix_planned", "Permanent Fix Planned"),
        ("fix_in_progress", "Fix In Progress"),
        ("validation", "Validation"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
        ("reopened", "Reopened"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"), ("medium", "Medium"),
        ("high", "High"), ("critical", "Critical"),
    ]
    SEVERITY_CHOICES = [
        ("minor", "Minor"), ("moderate", "Moderate"),
        ("major", "Major"), ("critical", "Critical"),
    ]
    IMPACT_CHOICES = [
        ("individual", "Individual"),
        ("department", "Department"),
        ("multiple_departments", "Multiple Departments"),
        ("organization", "Organization"),
        ("external_customer", "External Customer"),
        ("regulated_operation", "Regulated Operation"),
    ]
    URGENCY_CHOICES = [
        ("low", "Low"), ("medium", "Medium"),
        ("high", "High"), ("immediate", "Immediate"),
    ]
    CRITICALITY_CHOICES = [
        ("low", "Low"), ("medium", "Medium"),
        ("high", "High"), ("critical", "Critical"),
    ]
    ENVIRONMENT_CHOICES = [
        ("development", "Development"), ("test", "Test"),
        ("staging", "Staging"), ("production", "Production"),
        ("disaster_recovery", "Disaster Recovery"),
        ("office", "Office"), ("other", "Other"),
    ]
    DETECTION_METHOD_CHOICES = [
        ("manual", "Manual"),
        ("repeat_ticket_pattern", "Repeat Ticket Pattern"),
        ("major_incident_review", "Major Incident Review"),
        ("monitoring_correlation", "Monitoring Correlation"),
        ("sla_breach_pattern", "SLA Breach Pattern"),
        ("cmdb_impact", "CMDB Impact"),
        ("change_failure", "Change Failure"),
        ("vendor_notice", "Vendor Notice"),
        ("audit", "Audit"),
        ("other", "Other"),
    ]

    # Necessary-but-not-sufficient transition map: services additionally
    # enforce readiness/approval rules. No status PATCH anywhere.
    PROBLEM_STATUS_TRANSITIONS = {
        "candidate": {"draft", "rejected", "cancelled"},
        "draft": {"under_review", "cancelled"},
        "under_review": {"draft", "accepted", "rejected", "cancelled"},
        "accepted": {"investigating", "rejected", "cancelled"},
        "investigating": {"root_cause_identified", "rejected", "cancelled"},
        "root_cause_identified": {
            "workaround_available", "known_error", "permanent_fix_planned",
            "fix_in_progress", "cancelled",
        },
        "workaround_available": {
            "known_error", "root_cause_identified", "permanent_fix_planned",
            "validation", "resolved", "cancelled",
        },
        "known_error": {
            "permanent_fix_planned", "workaround_available",
            "fix_in_progress", "cancelled",
        },
        "permanent_fix_planned": {"fix_in_progress", "investigating", "cancelled"},
        "fix_in_progress": {"validation", "root_cause_identified", "cancelled"},
        "validation": {
            "fix_in_progress", "investigating", "resolved", "cancelled",
        },
        "resolved": {"closed", "reopened"},
        "closed": {"reopened"},
        "reopened": {
            "investigating", "root_cause_identified", "workaround_available",
            "known_error", "fix_in_progress", "validation", "resolved",
            "cancelled",
        },
        "rejected": set(),
        "cancelled": set(),
    }

    problem_number = models.CharField(
        max_length=20, unique=True, db_index=True,
        editable=False, blank=True, default="",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    problem_type = models.CharField(
        max_length=30, choices=PROBLEM_TYPE_CHOICES, default="reactive",
        db_index=True,
    )
    source = models.CharField(
        max_length=30, choices=SOURCE_CHOICES, default="manual",
    )
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default="draft",
        db_index=True,
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium",
        db_index=True,
    )
    severity = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, default="moderate",
    )
    impact = models.CharField(
        max_length=30, choices=IMPACT_CHOICES, default="department",
    )
    urgency = models.CharField(
        max_length=10, choices=URGENCY_CHOICES, default="medium",
    )
    criticality = models.CharField(
        max_length=10, choices=CRITICALITY_CHOICES, default="medium",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problems_owned",
    )
    problem_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problems_managed",
    )
    assigned_group = models.CharField(max_length=100, blank=True, default="")
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problems",
    )
    service = models.ForeignKey(
        "services.ServiceCatalogueItem", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problems",
    )
    category = models.ForeignKey(
        "tickets.TicketCategory", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problems",
    )
    subcategory = models.CharField(max_length=100, blank=True, default="")
    environment = models.CharField(
        max_length=20, choices=ENVIRONMENT_CHOICES, default="production",
    )
    detection_method = models.CharField(
        max_length=30, choices=DETECTION_METHOD_CHOICES, default="manual",
    )
    # Milestone timestamps: server-managed only (workflow services).
    first_detected_at = models.DateTimeField(null=True, blank=True, db_index=True)
    investigation_started_at = models.DateTimeField(null=True, blank=True)
    root_cause_identified_at = models.DateTimeField(null=True, blank=True)
    workaround_available_at = models.DateTimeField(null=True, blank=True)
    known_error_at = models.DateTimeField(null=True, blank=True)
    permanent_fix_planned_at = models.DateTimeField(null=True, blank=True)
    permanent_fix_implemented_at = models.DateTimeField(null=True, blank=True)
    validation_started_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    target_resolution_date = models.DateField(null=True, blank=True, db_index=True)
    next_review_at = models.DateTimeField(null=True, blank=True, db_index=True)
    recurrence_monitoring_until = models.DateTimeField(null=True, blank=True)
    # Summaries: written by workflow services only (never by ordinary PATCH).
    root_cause_summary = models.TextField(blank=True, default="")
    workaround_summary = models.TextField(blank=True, default="")
    permanent_fix_summary = models.TextField(blank=True, default="")
    resolution_summary = models.TextField(blank=True, default="")
    closure_reason = models.TextField(blank=True, default="")
    # Counters: server-maintained, not client-writable.
    recurrence_count = models.PositiveIntegerField(default=0, editable=False)
    linked_ticket_count = models.PositiveIntegerField(default=0, editable=False)
    open_ticket_count = models.PositiveIntegerField(default=0, editable=False)
    record_version = models.PositiveIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problems_created",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "problem"
        verbose_name_plural = "problems"
        indexes = [
            models.Index(fields=["status", "priority"], name="pm_prob_status_prio_idx"),
            models.Index(fields=["owner"], name="pm_prob_owner_idx"),
            models.Index(fields=["problem_manager"], name="pm_prob_manager_idx"),
            models.Index(fields=["closed_at"], name="pm_prob_closed_idx"),
            models.Index(fields=["next_review_at"], name="pm_prob_next_review_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(problem_number="") ,
                name="pm_prob_number_required",
            ),
        ]

    def __str__(self):
        return f"{self.problem_number} — {self.title}"

    @property
    def is_open(self):
        return self.status not in {"closed", "rejected", "cancelled"}

    def save(self, *args, **kwargs):
        if not self.problem_number:
            self.problem_number = next_number(problem_year_prefix())
        if not self._state.adding:
            self.record_version += 1
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "record_version" not in update_fields:
                kwargs["update_fields"] = list(update_fields) + ["record_version"]
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Links (Gate 1). problem FK is PROTECT so a Problem carrying links cannot be
# hard-deleted; target FKs mirror project convention (CASCADE keeps the link
# tidy when a target is truly hard-deleted; ProblemHistory retains the record).
# ---------------------------------------------------------------------------

class ProblemTicketLink(SoftDeleteModel):
    RELATIONSHIP_CHOICES = [
        ("caused_by", "Caused By"),
        ("symptom_of", "Symptom Of"),
        ("related_incident", "Related Incident"),
        ("major_incident", "Major Incident"),
        ("recurring_incident", "Recurring Incident"),
        ("duplicate_pattern", "Duplicate Pattern"),
        ("resolved_by_fix", "Resolved By Fix"),
        ("validation_incident", "Validation Incident"),
        ("monitoring_generated", "Monitoring Generated"),
        ("other", "Other"),
    ]
    RELEVANCE_CHOICES = [
        ("confirmed", "Confirmed"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
        ("candidate", "Candidate"),
    ]
    RECURRENCE_RELATIONSHIP_TYPES = {
        "recurring_incident", "duplicate_pattern", "related_incident",
    }

    problem = models.ForeignKey(
        Problem, on_delete=models.PROTECT, related_name="ticket_links",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.PROTECT, related_name="problem_links",
    )
    relationship_type = models.CharField(
        max_length=30, choices=RELATIONSHIP_CHOICES, default="related_incident",
    )
    relevance = models.CharField(
        max_length=12, choices=RELEVANCE_CHOICES, default="medium",
    )
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_ticket_links_created",
    )
    linked_at = models.DateTimeField(auto_now_add=True)
    is_primary = models.BooleanField(default=False)
    recurrence_fingerprint = models.CharField(max_length=64, blank=True, default="")
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-linked_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "ticket"],
                condition=Q(is_deleted=False),
                name="pm_active_problem_ticket_link",
            ),
        ]

    def __str__(self):
        return f"{self.problem_id} ↔ ticket #{self.ticket_id} ({self.relationship_type})"


class ProblemConfigurationItemLink(SoftDeleteModel):
    IMPACT_TYPE_CHOICES = [
        ("direct", "Direct"), ("indirect", "Indirect"),
        ("dependency", "Dependency"), ("suspected", "Suspected"),
        ("confirmed", "Confirmed"), ("validation", "Validation"),
        ("permanent_fix", "Permanent Fix"),
    ]
    ROLE_CHOICES = [
        ("affected", "Affected"),
        ("suspected_cause", "Suspected Cause"),
        ("root_cause", "Root Cause"),
        ("workaround_target", "Workaround Target"),
        ("fix_target", "Fix Target"),
        ("validation_target", "Validation Target"),
        ("monitoring_target", "Monitoring Target"),
    ]
    CONFIDENCE_CHOICES = [
        ("confirmed", "Confirmed"), ("high", "High"), ("medium", "Medium"),
        ("low", "Low"), ("unknown", "Unknown"),
    ]

    problem = models.ForeignKey(
        Problem, on_delete=models.PROTECT, related_name="ci_links",
    )
    configuration_item = models.ForeignKey(
        "cmdb.ConfigurationItem", on_delete=models.CASCADE,
        related_name="problem_links",
    )
    impact_type = models.CharField(
        max_length=20, choices=IMPACT_TYPE_CHOICES, default="direct",
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="affected",
    )
    confidence = models.CharField(
        max_length=12, choices=CONFIDENCE_CHOICES, default="medium",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_ci_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "configuration_item"],
                condition=Q(is_deleted=False),
                name="pm_active_problem_ci_link",
            ),
        ]

    def __str__(self):
        return f"{self.problem_id} ↔ CI {self.configuration_item_id}"


class ProblemServiceLink(SoftDeleteModel):
    IMPACT_TYPE_CHOICES = ProblemConfigurationItemLink.IMPACT_TYPE_CHOICES
    ROLE_CHOICES = ProblemConfigurationItemLink.ROLE_CHOICES
    CONFIDENCE_CHOICES = ProblemConfigurationItemLink.CONFIDENCE_CHOICES

    problem = models.ForeignKey(
        Problem, on_delete=models.PROTECT, related_name="service_links",
    )
    service = models.ForeignKey(
        "services.ServiceCatalogueItem", on_delete=models.CASCADE,
        related_name="problem_links",
    )
    impact_type = models.CharField(
        max_length=20, choices=IMPACT_TYPE_CHOICES, default="direct",
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="affected",
    )
    confidence = models.CharField(
        max_length=12, choices=CONFIDENCE_CHOICES, default="medium",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_service_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "service"],
                condition=Q(is_deleted=False),
                name="pm_active_problem_service_link",
            ),
        ]

    def __str__(self):
        return f"{self.problem_id} ↔ service {self.service_id}"


class ProblemAssetLink(SoftDeleteModel):
    IMPACT_TYPE_CHOICES = ProblemConfigurationItemLink.IMPACT_TYPE_CHOICES
    ROLE_CHOICES = ProblemConfigurationItemLink.ROLE_CHOICES
    CONFIDENCE_CHOICES = ProblemConfigurationItemLink.CONFIDENCE_CHOICES

    problem = models.ForeignKey(
        Problem, on_delete=models.PROTECT, related_name="asset_links",
    )
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.CASCADE,
        related_name="problem_links",
    )
    impact_type = models.CharField(
        max_length=20, choices=IMPACT_TYPE_CHOICES, default="direct",
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="affected",
    )
    confidence = models.CharField(
        max_length=12, choices=CONFIDENCE_CHOICES, default="medium",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_asset_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "asset"],
                condition=Q(is_deleted=False),
                name="pm_active_problem_asset_link",
            ),
        ]

    def __str__(self):
        return f"{self.problem_id} ↔ asset {self.asset_id}"


class ProblemSoftwareProductLink(SoftDeleteModel):
    IMPACT_TYPE_CHOICES = ProblemConfigurationItemLink.IMPACT_TYPE_CHOICES
    ROLE_CHOICES = ProblemConfigurationItemLink.ROLE_CHOICES
    CONFIDENCE_CHOICES = ProblemConfigurationItemLink.CONFIDENCE_CHOICES

    problem = models.ForeignKey(
        Problem, on_delete=models.PROTECT, related_name="software_links",
    )
    software_product = models.ForeignKey(
        "licensing.SoftwareProduct", on_delete=models.CASCADE,
        related_name="problem_links",
    )
    impact_type = models.CharField(
        max_length=20, choices=IMPACT_TYPE_CHOICES, default="direct",
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="affected",
    )
    confidence = models.CharField(
        max_length=12, choices=CONFIDENCE_CHOICES, default="medium",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_software_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "software_product"],
                condition=Q(is_deleted=False),
                name="pm_active_problem_software_link",
            ),
        ]

    def __str__(self):
        return f"{self.problem_id} ↔ product {self.software_product_id}"


# ---------------------------------------------------------------------------
# Problem Task (Gate 1 model; lifecycle actions arrive with readiness gates)
# ---------------------------------------------------------------------------

class ProblemTask(SoftDeleteModel):
    TASK_TYPE_CHOICES = [
        ("investigation", "Investigation"),
        ("evidence_collection", "Evidence Collection"),
        ("root_cause_analysis", "Root Cause Analysis"),
        ("workaround", "Workaround"),
        ("known_error", "Known Error"),
        ("change_request", "Change Request"),
        ("permanent_fix", "Permanent Fix"),
        ("validation", "Validation"),
        ("documentation", "Documentation"),
        ("knowledge_capture", "Knowledge Capture"),
        ("monitoring", "Monitoring"),
        ("supplier_follow_up", "Supplier Follow-up"),
        ("process_improvement", "Process Improvement"),
        ("other", "Other"),
    ]
    TASK_STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("blocked", "Blocked"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("skipped", "Skipped"),
    ]

    problem = models.ForeignKey(
        Problem, on_delete=models.PROTECT, related_name="tasks",
    )
    sequence = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    task_type = models.CharField(
        max_length=30, choices=TASK_TYPE_CHOICES, default="investigation",
    )
    status = models.CharField(
        max_length=20, choices=TASK_STATUS_CHOICES, default="not_started",
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_tasks_assigned",
    )
    assigned_group = models.CharField(max_length=100, blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_tasks_completed",
    )
    required = models.BooleanField(default=True)
    blocks_resolution = models.BooleanField(default=True)
    evidence_required = models.BooleanField(default=False)
    completion_note = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_tasks_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sequence", "created_at"]
        verbose_name = "problem task"
        verbose_name_plural = "problem tasks"
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "sequence"],
                condition=Q(is_deleted=False),
                name="pm_active_problem_task_sequence",
            ),
        ]

    def __str__(self):
        return f"#{self.sequence} {self.title} ({self.status})"

    @property
    def is_overdue(self):
        return (
            self.due_at is not None
            and self.status not in {"completed", "cancelled", "skipped"}
            and self.due_at < timezone.now()
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            self.version += 1
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "version" not in update_fields:
                kwargs["update_fields"] = list(update_fields) + ["version"]
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Immutable history (Gate 1 columns; later gates append nullable FKs)
# ---------------------------------------------------------------------------

class ProblemHistory(models.Model):
    EVENT_CHOICES = [
        ("created", "Created"),
        ("submitted", "Submitted"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("investigation_started", "Investigation Started"),
        ("ticket_linked", "Ticket Linked"),
        ("ticket_unlinked", "Ticket Unlinked"),
        ("candidate_detected", "Candidate Detected"),
        ("candidate_promoted", "Candidate Promoted"),
        ("root_cause_analysis_created", "Root Cause Analysis Created"),
        ("root_cause_identified", "Root Cause Identified"),
        ("workaround_created", "Workaround Created"),
        ("workaround_published", "Workaround Published"),
        ("known_error_linked", "Known Error Linked"),
        ("permanent_fix_planned", "Permanent Fix Planned"),
        ("change_linked", "Change Linked"),
        ("fix_started", "Fix Started"),
        ("fix_implemented", "Fix Implemented"),
        ("validation_started", "Validation Started"),
        ("validation_passed", "Validation Passed"),
        ("validation_failed", "Validation Failed"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
        ("reopened", "Reopened"),
        ("cancelled", "Cancelled"),
        ("task_created", "Task Created"),
        ("task_completed", "Task Completed"),
        ("action_created", "Action Created"),
        ("action_completed", "Action Completed"),
        ("exception_approved", "Exception Approved"),
        ("major_review_started", "Major Review Started"),
        ("major_review_approved", "Major Review Approved"),
        ("evidence_added", "Evidence Added"),
        ("linked", "Linked"),
        ("unlinked", "Unlinked"),
        ("metrics_refreshed", "Metrics Refreshed"),
        ("other", "Other"),
    ]

    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="history_records",
    )
    task = models.ForeignKey(
        ProblemTask, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="history_records",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="problem_history_events",
    )
    event_type = models.CharField(max_length=40, choices=EVENT_CHOICES)
    previous_status = models.CharField(max_length=30, blank=True, default="")
    new_status = models.CharField(max_length=30, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    changed_fields = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["problem", "created_at"],
                name="pm_history_problem_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.problem_id}: {self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Problem history records are immutable.")
        if len(self.detail or "") > 4000:
            raise ValidationError({"detail": "History detail is bounded to 4000 characters."})
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise ValidationError("Problem history records cannot be deleted.")


# ---------------------------------------------------------------------------
# Gate 2 models
# ---------------------------------------------------------------------------

class ProblemEvidence(SoftDeleteModel):
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="evidence",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    evidence_type = models.CharField(
        max_length=30, default="other",
    )
    source = models.CharField(max_length=100, blank=True, default="")
    file = models.FileField(upload_to="problem_evidence/", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="evidence_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "problem evidence"
        verbose_name_plural = "problem evidence"

    def __str__(self):
        return f"{self.problem_id}: {self.title}"


class RootCauseAnalysis(SoftDeleteModel):
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="root_cause_analyses",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    analysis_method = models.CharField(
        max_length=30, default="five_whys",
    )
    findings = models.TextField(blank=True, default="")
    concluded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="rca_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "root cause analysis"
        verbose_name_plural = "root cause analyses"

    def __str__(self):
        return f"{self.problem_id}: {self.title}"


class RootCauseWhy(SoftDeleteModel):
    analysis = models.ForeignKey(
        RootCauseAnalysis, on_delete=models.CASCADE,
        related_name="whys",
    )
    question_number = models.PositiveIntegerField()
    question_text = models.TextField()
    answer = models.TextField()
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="whys_answered",
    )
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["question_number"]
        verbose_name = "root cause why"
        verbose_name_plural = "root cause whys"

    def __str__(self):
        return f"WHY {self.question_number}: {self.answer[:50] if self.answer else ''}"


class RootCauseFactor(SoftDeleteModel):
    CATEGORY_CHOICES = [
        ("people", "People"),
        ("method", "Method"),
        ("machine", "Machine"),
        ("material", "Material"),
        ("environment", "Environment"),
        ("other", "Other"),
    ]
    analysis = models.ForeignKey(
        RootCauseAnalysis, on_delete=models.CASCADE,
        related_name="fishbone_factors",
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="people",
    )
    factor = models.CharField(max_length=200)
    contribution = models.TextField(blank=True, default="")
    identified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="factors_identified",
    )
    identified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["factor"]
        verbose_name = "root cause factor"
        verbose_name_plural = "root cause factors"

    def __str__(self):
        return f"{self.get_category_display()}: {self.factor}"


class ProblemTimelineEvent(SoftDeleteModel):
    EVENT_TYPE_CHOICES = [
        ("milestone", "Milestone"),
        ("investigation_start", "Investigation Start"),
        ("root_cause_found", "Root Cause Found"),
        ("workaround_implemented", "Workaround Implemented"),
        ("action_taken", "Action Taken"),
        ("validation_completed", "Validation Completed"),
        ("fix_implemented", "Fix Implemented"),
        ("problem_resolved", "Problem Resolved"),
        ("problem_closed", "Problem Closed"),
        ("exception_granted", "Exception Granted"),
        ("exception_denied", "Exception Denied"),
    ]
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="timeline_events",
    )
    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="timeline_events_recorded",
    )

    class Meta:
        ordering = ["occurred_at"]
        verbose_name = "problem timeline event"
        verbose_name_plural = "problem timeline events"

    def __str__(self):
        return f"{self.problem_id}: {self.get_event_type_display()} @ {self.occurred_at.strftime('%Y-%m-%d %H:%M')}"


class ProblemAction(SoftDeleteModel):
    ACTION_TYPE_CHOICES = [
        ("corrective", "Corrective Action"),
        ("preventive", "Preventive Action"),
        ("root_cause", "Root Cause Action"),
        ("validation", "Validation Action"),
        ("exception", "Exception Action"),
    ]
    STATUS_CHOICES = [
        ("planned", "Planned"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("verified", "Verified"),
        ("closed", "Closed"),
    ]
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="actions",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    action_type = models.CharField(
        max_length=20, choices=ACTION_TYPE_CHOICES, default="corrective",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="planned",
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="actions_assigned",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    root_cause_analysis = models.ForeignKey(
        RootCauseAnalysis, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="actions",
    )
    validation_status = models.CharField(
        max_length=20, blank=True, default="",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="actions_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="actions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "problem action"
        verbose_name_plural = "problem actions"

    def __str__(self):
        return f"{self.problem_id}: {self.get_action_type_display()} ({self.status})"


class ProblemWorkaround(SoftDeleteModel):
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="workarounds",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    workaround_type = models.CharField(
        max_length=30, default="temporary",
    )
    steps = models.TextField(blank=True, default="")
    effectiveness_rating = models.PositiveIntegerField(
        default=3, help_text="1-5 scale",
    )
    implemented_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    implemented_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="workarounds_implemented",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="workarounds_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "problem workaround"
        verbose_name_plural = "problem workarounds"

    def __str__(self):
        return f"{self.problem_id}: {self.title}"


class ProblemValidation(SoftDeleteModel):
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="validations",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    validation_type = models.CharField(
        max_length=30, default="functional",
    )
    test_plan = models.TextField(blank=True, default="")
    test_results = models.TextField(blank=True, default="")
    passed = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="validations_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="validations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "problem validation"
        verbose_name_plural = "problem validations"

    def __str__(self):
        return f"{self.problem_id}: {self.title} ({'passed' if self.passed else 'failed'})"


class ProblemException(SoftDeleteModel):
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="exceptions",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    exception_type = models.CharField(
        max_length=30, default="operational",
    )
    granted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="exceptions_granted",
    )
    reason = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="exceptions_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    conditions = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="exceptions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "problem exception"
        verbose_name_plural = "problem exceptions"

    def __str__(self):
        return f"{self.problem_id}: {self.title}"


def evaluate_problem_readiness(problem):
    """Evaluate if a problem is ready for a status transition.

    Returns (ready: bool, reason: str, blocking_factors: list[str]).
    """
    blocking = []

    # Must have a problem number
    if not problem.problem_number:
        blocking.append("problem_number_missing")
        return False, "Problem number is required", blocking

    # Open problems need at least one task or evidence
    if problem.is_open and not problem.tasks.exists():
        blocking.append("no_tasks")
        return False, "Open problems must have at least one task", blocking

    if problem.is_open and not problem.evidence.exists():
        blocking.append("no_evidence")
        return False, "Open problems must have at least one evidence record", blocking

    # Status-specific checks
    if problem.status == "investigating" and not problem.root_cause_identified_at:
        blocking.append("root_cause_not_identified")
        return False, "Root cause must be identified before moving from investigating", blocking

    if problem.status == "workaround_available" and not problem.workarounds.exists():
        blocking.append("no_workaround")
        return False, "Workaround must be documented before moving from workaround_available", blocking

    if problem.status == "validation" and not problem.validations.filter(passed=True).exists():
        blocking.append("no_validation_passed")
        return False, "At least one validation must pass before moving from validation", blocking

    if problem.status == "known_error" and not problem.known_error_at:
        blocking.append("known_error_date_missing")
        return False, "Known error date must be set for known_error status", blocking

    ready = len(blocking) == 0
    reason = "Problem is ready for transition" if blocking == [] else "; ".join(
        [f"Blocked: {b}" for b in blocking]
    )
    return ready, reason, blocking
