"""Shared soft-deletion infrastructure + protected audit log.

Policy enforced here (code-level):
- Normal ``delete()`` / ``QuerySet.delete()`` NEVER hard-deletes.
  It only flips ``is_deleted`` and stores deletion metadata.
- Real removal is ONLY via ``hard_delete()`` and MUST be gated by the
  System-Admin-only permission at the view layer (see tickets/assets/
  accounts views + recycle-bin API). This model layer intentionally does
  NOT check roles so tests/scripts can call it directly; views enforce.
- Soft deletion never cascades: related tickets/assets/history are kept.
  Hard deletion is blocked by PROTECT FKs when history exists.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
import uuid


class SoftDeleteQuerySet(models.QuerySet):
    """Default queryset hides soft-deleted rows."""

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    def soft_delete(self, by_user=None, reason=""):
        """Bulk soft-delete without loading rows one by one."""
        return self.alive().update(
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by=by_user,
            deletion_reason=reason or "",
        )

    def delete(self):
        """Override: bulk QuerySet.delete() soft-deletes instead of removing."""
        return self.soft_delete()

    def hard_delete(self):
        """Real bulk removal. Call ONLY from System-Admin recycle-bin flow."""
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Default manager: ordinary queries exclude deleted records."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            is_deleted=False
        )

    def with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            is_deleted=True
        )


class SoftDeleteModel(models.Model):
    """Abstract base adding consistent soft-deletion fields.

    Concrete models get:
      objects      -> hides deleted (use everywhere operationally)
      all_objects  -> includes deleted (recycle bin / admin only)
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted",
    )
    deletion_reason = models.TextField(blank=True, default="")

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self, by_user=None, reason=""):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.deletion_reason = reason or ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def restore(self):
        """Restore preserving PK + history. Callers validate FKs/uniqueness."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.deletion_reason = ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def delete(self, using=None, keep_parents=False, by_user=None, reason=""):
        """Single-object delete() soft-deletes. Never hard-deletes."""
        self.soft_delete(
            by_user=by_user if hasattr(by_user, "pk") else None,
            reason=reason or "",
        )
        return (1, {self._meta.label: 1})

    def hard_delete(self, using=None, keep_parents=False):
        """Real removal. Views must enforce System-Admin-only + audit."""
        return super().delete(using=using, keep_parents=keep_parents)


class AuditLog(models.Model):
    """Protected, append-only log. NEVER soft-deleted, NEVER edited via API.

    ``object_id`` is a string so the log survives hard deletion of the target.
    """

    ACTION_CHOICES = [
        ("create", "Create"),
        ("update", "Update"),
        ("soft_delete", "Soft delete"),
        ("restore", "Restore"),
        ("hard_delete", "Permanent delete"),
        ("bulk_create", "Bulk create"),
        ("bulk_update", "Bulk update"),
        ("bulk_soft_delete", "Bulk soft delete"),
        ("status_change", "Status change"),
        ("assignment", "Assignment change"),
        ("deactivate", "Deactivate"),
        ("reactivate", "Reactivate"),
        ("retire", "Retire"),
        ("note", "Note / comment"),
        ("password_reset", "Password reset"),
        ("export", "Export"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=100)  # e.g. "tickets.Ticket"
    object_id = models.CharField(max_length=100)
    object_repr = models.CharField(max_length=255, blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    reason = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        permissions = [
            ("view_audit_logs", "Can view audit logs"),
        ]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.actor} {self.action} {self.entity_type}:{self.object_id}"


class Notification(SoftDeleteModel):
    """In-app notification. Soft-deletable; never hard-deleted except by Admin."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    is_read = models.BooleanField(default=False)
    entity_type = models.CharField(max_length=100, blank=True, default="")
    object_id = models.CharField(max_length=100, blank=True, default="")
    dedupe_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Deterministic fingerprint for active-notification deduplication. "
                  "NULL for rows created outside the dedup-aware path. "
                  "Uniqueness for active rows is enforced by the conditional "
                  "unique constraint in Meta (db_index is therefore redundant).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=Q(is_deleted=False),
                name="unique_active_dedupe_key",
            ),
        ]

    def __str__(self):
        return f"To {self.recipient_id}: {self.title[:60]}"


class NotificationOutboxEvent(models.Model):
    """Transactional outbox row for durable asynchronous notification delivery.

    Phase 66. A row is inserted inside the *same* database transaction as the
    business change that triggered it (ticket creation, status change, ...).
    It therefore commits or rolls back atomically with that change: a crash
    after commit can never erase a queued delivery, and a rolled-back business
    transaction can never leave an orphaned delivery.

    A Celery worker (``common.tasks.process_notification_outbox``) and a
    low-latency ``on_commit`` wake-up (``common.tasks.deliver_outbox_event``)
    claim pending rows, attempt the external delivery (SMTP), and persist the
    outcome. Correctness does NOT depend on the wake-up: the periodic scanner
    re-discovers any row the wake-up missed.

    Delivery semantics are **at-least-once**. A worker can hand a message to
    SMTP and crash before recording success; a retry then sends it again. The
    ``dedupe_key`` collapses duplicate *event registration* (the same logical
    email enqueued repeatedly while still active) but cannot make the external
    SMTP hand-off exactly-once.

    State machine::

        pending ──claim──▶ processing ──success──▶ delivered (terminal)
           ▲                    │
           │                 failure, attempts < max
           └──── retry ◀────────┘
                                │ failure, attempts >= max
                                ▼
                             failed (terminal)
        pending/retry ──admin cancel──▶ cancelled (terminal)

    An abandoned ``processing`` row whose lease has expired is recovered back
    to ``retry`` (or ``failed`` once attempts are exhausted) by the scanner.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("retry", "Retry scheduled"),
        ("processing", "Processing"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    #: Statuses from which a worker may claim the row for delivery.
    CLAIMABLE_STATUSES = ("pending", "retry")
    #: Terminal statuses (no further automatic delivery attempts).
    TERMINAL_STATUSES = ("delivered", "failed", "cancelled")

    CHANNEL_CHOICES = [
        ("email", "Email"),
    ]

    #: Upper bound for the structured payload (bytes, serialized JSON). Email
    #: subjects/bodies are small; an oversized payload indicates a misuse and
    #: is rejected at enqueue time rather than silently bloating the row.
    MAX_PAYLOAD_BYTES = 16 * 1024

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(
        max_length=100, db_index=True,
        help_text="Logical event/channel discriminator, e.g. "
                  "'ticket.email.created'.")
    channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default="email", db_index=True)
    # Recipient reference. SET_NULL so a deleted account never blocks retention
    # or row deletion; the snapshot email below preserves deliverability.
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="outbox_events")
    recipient_email = models.EmailField(
        max_length=254, blank=True, default="",
        help_text="Recipient address snapshot captured at enqueue time.")
    notification = models.ForeignKey(
        "common.Notification", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="outbox_events",
        help_text="Related in-app notification, when one was created.")
    category = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Notification preference category re-checked at delivery "
                  "(empty = global master switch only).")
    payload = models.JSONField(
        default=dict, blank=True,
        help_text="Structured, versionable delivery payload (subject, body, "
                  "template, context). Never secrets or credentials.")
    dedupe_key = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Idempotency fingerprint collapsing duplicate registration "
                  "of the same logical delivery while a row is still active.")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    attempts = models.PositiveIntegerField(
        default=0, help_text="Delivery attempts started (incremented on claim).")
    max_attempts = models.PositiveIntegerField(
        default=5, help_text="Attempt ceiling before the row becomes 'failed'.")
    next_attempt_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text="Earliest time the row may be claimed (retry backoff).")
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Processing lease deadline; an expired lease is recoverable.")
    claimed_by = models.CharField(
        max_length=64, blank=True, default="",
        help_text="Worker identifier owning the active claim.")
    last_error = models.TextField(
        blank=True, default="",
        help_text="Sanitized failure summary (exception type, no PII/secrets).")
    cancel_reason = models.CharField(
        max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # Collapse duplicate registration of the same logical delivery while
            # a row is still active. Delivered/failed/cancelled rows keep their
            # dedupe_key (audit trail) but no longer block a future, legitimate
            # re-send of the same logical event.
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=~Q(status__in=("delivered", "failed", "cancelled")),
                name="unique_active_outbox_dedupe"),
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"],
                         name="outbox_claim_idx"),
            models.Index(fields=["status", "lease_expires_at"],
                         name="outbox_lease_idx"),
            models.Index(fields=["recipient"],
                         name="outbox_recipient_idx"),
        ]

    def __str__(self):
        return f"{self.event_type} -> {self.recipient_email or self.recipient_id} [{self.status}]"

    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES


class PrivacyErasureRequest(models.Model):
    """Privacy erasure workflow with mandatory two-person approval.

    Not a GDPR-compliance claim. Flow:

        create (reason + scope + confirm)
            -> pending_review
            -> approve (reviewer != requester) -> approved
            -> execute (confirmation) -> executing -> completed/failed
            -> reject (reviewer != requester) -> rejected

    Execution requires an approved decision. The audit log records request
    and outcome without erased personal data. Impact assessment is recalculated
    before execution to detect stale approvals.
    """

    STATUS_CHOICES = [
        ("pending_review", "Pending review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("execution_pending", "Execution pending"),
        ("executing", "Executing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        # Legacy statuses retained for backward compatibility.
        ("pending", "Pending (legacy)"),
        ("executed", "Executed (legacy)"),
    ]

    # Request details
    entity_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    scope = models.TextField()
    reason = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending_review",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="erasure_requests",
    )

    # Independent review (two-person approval)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="erasure_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_decision = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="approved | rejected | cancelled",
    )
    review_reason = models.TextField(
        blank=True,
        default="",
        help_text="Reviewer's decision reason.",
    )

    # Execution details
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="erasure_executions",
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)

    # Impact assessment snapshot
    impact_assessment = models.JSONField(default=dict, blank=True)
    impact_assessed_at = models.DateTimeField(null=True, blank=True)

    # Safe execution and concurrency tracking
    execution_started_at = models.DateTimeField(null=True, blank=True)
    execution_outcome = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="completed | failed | cancelled",
    )
    execution_error = models.TextField(
        blank=True,
        default="",
        help_text="Sanitized failure details (no PII).",
    )
    execution_lock = models.BooleanField(
        default=False,
        help_text="Set while an execution is in flight to prevent concurrency.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="erasure_status_idx"),
            models.Index(fields=["requested_by"], name="erasure_requester_idx"),
            models.Index(fields=["reviewed_by"], name="erasure_reviewer_idx"),
            models.Index(fields=["created_at"], name="erasure_created_idx"),
        ]

    def __str__(self):
        return (
            f"Erasure {self.entity_type}:{self.object_id} "
            f"[{self.status}]"
        )

    # Lifecycle helpers

    def can_be_reviewed_by(self, user):
        """Prevent requesters from reviewing their own erasure requests."""
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if self.requested_by_id and self.requested_by_id == user.pk:
            return False

        if getattr(self, "is_deleted", False):
            return False

        return bool(
            getattr(user, "is_system_admin", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "role", "") == "system_admin"
        )

    def is_terminal(self):
        return self.status in (
            "completed",
            "failed",
            "rejected",
            "cancelled",
        )

    def is_executable(self):
        return self.status == "approved"

    def is_reviewable(self):
        return self.status == "pending_review"


class DataRetentionPolicy(models.Model):
    """Configurable data-retention policy for an operational data category.

    Policies define how long records of a category are kept before they are
    eligible for retention (anonymization / soft-delete / permanent delete
    where safe). Execution is gated: a preview must be shown first, and the
    policy must be re-validated at execution time. Audit-log records are
    explicitly excluded from generic retention operations.

    Not a GDPR-compliance claim.
    """

    DATA_CATEGORY_CHOICES = [
        ("security_events", "Security events"),
        ("notifications", "Notifications"),
        ("background_task_runs", "Background task execution records"),
        ("temporary_import_reports", "Temporary import reports"),
        ("expired_temporary_records", "Expired temporary records"),
        ("other", "Other operational data"),
    ]

    name = models.CharField(max_length=150)
    data_category = models.CharField(
        max_length=40, choices=DATA_CATEGORY_CHOICES, db_index=True)
    retention_duration = models.PositiveIntegerField(
        help_text="Retention duration in days. Records older than this are "
                  "eligible for retention when the policy runs.")
    enabled = models.BooleanField(default=True, db_index=True)
    conditions = models.JSONField(
        default=dict, blank=True,
        help_text="Additional record-level conditions (JSON) that narrow "
                  "which records of the category are eligible.")
    description = models.TextField(blank=True, default="")
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    responsible_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="retention_policies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["data_category"], name="retention_category_idx"),
            models.Index(fields=["enabled", "next_run_at"], name="retention_due_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_data_category_display()})"


class DataRetentionExecution(models.Model):
    """Execution history for a data-retention policy run.

    One row per execution attempt: eligible / affected / excluded counts,
    exclusion reasons, and a non-sensitive error summary. Used for the
    execution-history view and failure reporting.
    """

    STATUS_CHOICES = [
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]

    policy = models.ForeignKey(
        DataRetentionPolicy, on_delete=models.CASCADE,
        related_name="executions")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default="running")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    records_eligible = models.PositiveIntegerField(default=0)
    records_affected = models.PositiveIntegerField(default=0)
    records_excluded = models.PositiveIntegerField(default=0)
    exclusion_reasons = models.JSONField(default=list, blank=True)
    error_summary = models.TextField(blank=True, default="")
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["policy", "status"], name="retentexec_policy_idx"),
            models.Index(fields=["started_at"], name="retentexec_started_idx"),
        ]

    def __str__(self):
        return f"Retention {self.policy_id} {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


class EmailProcessing(models.Model):
    """Track inbound email processing to prevent duplicates and support retries.

    One record per Message-ID ensures we only process each unique email once.
    """
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("processed", "Processed"),
        ("failed", "Failed"),
    )

    message_id = models.CharField(
        max_length=255, unique=True,
        help_text="The Message-ID header from the email.")
    mailbox = models.CharField(
        max_length=100, blank=True,
        help_text="Name/identifier of the mailbox the email was received on.")
    recipient = models.EmailField(
        help_text="The email address the message was delivered to.")
    sender = models.EmailField(
        help_text="The sender's email address.")
    subject = models.CharField(max_length=255, blank=True)
    body_preview = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="email_processings",
        help_text="Ticket created from this email, if any.")
    error_details = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "processed_at"]),
        ]

    def __str__(self):
        return f"Email {self.message_id[:20]}… → {self.status}"


class BackgroundTaskRun(models.Model):
    """Operational health trail for background tasks (Celery beat/workers).

    One row per task execution attempt: started, finished, success/failure
    and a non-sensitive error summary (exception type only — never message
    bodies or credentials). Lets the operations status endpoint and simple
    logs answer "did the last SLA check run OK?" without a monitoring stack.
    """

    STATUS_CHOICES = (
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    )

    task_name = models.CharField(max_length=200, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default="running")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    success = models.BooleanField(default=False)
    error_summary = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True,
        help_text="Request/flow correlation ID propagated from the caller.")

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["task_name", "status"]),
        ]

    def __str__(self):
        return f"{self.task_name} {self.status}"


class SavedReport(SoftDeleteModel):
    """A saved report configuration: report type, name, description,
    and persisted JSON filters. Users can re-run the same report later.

    Ownership: creator owns their saved report. IT staff / admins can see
    all saved reports (for sharing / admin visibility).
    """
    REPORT_TYPE_CHOICES = [
        ("ticket_category", "Tickets by category"),
        ("ticket_sla", "SLA health"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_reports",
    )
    report_type = models.CharField(max_length=40, choices=REPORT_TYPE_CHOICES)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    filters = models.JSONField(default=dict, blank=True,
                               help_text="Persisted report filter parameters.")
    is_shared = models.BooleanField(default=False,
                                    help_text="Visible to IT staff and admins.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user"], name="savedreport_user_idx"),
            models.Index(fields=["report_type"], name="savedreport_type_idx"),
            models.Index(fields=["is_shared"], name="savedreport_shared_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.report_type})"


class ScheduledReport(SoftDeleteModel):
    """A schedule that auto-generates and emails a SavedReport.

    Supports daily / weekly / monthly cadence. On each tick, a Celery task
    renders the saved report, exports it, and emails it to the configured
    recipients. Execution history lives in ScheduledReportRun.
    """
    SCHEDULE_CHOICES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
    ]

    FORMAT_CHOICES = [
        ("csv", "CSV"),
        ("xlsx", "XLSX"),
        ("pdf", "PDF"),
        ("docx", "DOCX"),
    ]

    saved_report = models.ForeignKey(
        SavedReport, on_delete=models.CASCADE,
        related_name="schedules",
    )
    schedule = models.CharField(max_length=10, choices=SCHEDULE_CHOICES)
    recipients = models.JSONField(default=list, blank=True,
                                  help_text="Email addresses to receive the report.")
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default="csv")
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["saved_report"], name="scheduledreport_report_idx"),
            models.Index(fields=["schedule"], name="scheduledreport_schedule_idx"),
            models.Index(fields=["enabled", "next_run_at"], name="scheduledreport_due_idx"),
        ]

    def __str__(self):
        return f"Schedule {self.schedule} for '{self.saved_report.name}'"


class ScheduledReportRun(SoftDeleteModel):
    """Execution history for scheduled report delivery."""
    STATUS_CHOICES = (
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    )

    scheduled_report = models.ForeignKey(
        ScheduledReport, on_delete=models.CASCADE,
        related_name="runs",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    success = models.BooleanField(default=False)
    error_summary = models.TextField(blank=True, default="")
    recipient_count = models.PositiveIntegerField(default=0)
    execution_token = models.CharField(max_length=64, unique=False, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    occurrence_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        help_text="Stable occurrence identity across replacement execution attempts.",
    )

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["scheduled_report", "status"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["occurrence_id"], name="scheduledreportrun_occ_id_idx"),
        ]
        constraints = [
            # At most one in-flight ('running') run per scheduled report so
            # concurrent scanners cannot double-deliver the same report.
            models.UniqueConstraint(
                fields=["scheduled_report"],
                condition=models.Q(status="running"),
                name="unique_running_run_per_scheduled_report",
            ),
        ]

    def __str__(self):
        return f"Run {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


class ScheduledReportDelivery(SoftDeleteModel):
    """Per-recipient delivery record for a scheduled report run.

    Provides durable deduplication so that lease recovery, worker crashes,
    or retried Celery tasks cannot unintentionally produce duplicate
    scheduled-report emails to the same recipient within the same run.

    Because an external SMTP hand-off cannot be made atomic with a database
    transaction, exactly-once external delivery is not guaranteed: a worker
    that crashes after SMTP acceptance but before recording ``sent`` may
    cause one duplicate on recovery. That window is minimized by inserting a
    ``pending`` delivery row before SMTP and flipping to ``sent`` only after
    acceptance. Cross-run duplicates after a crash are a documented,
    accepted trade-off (see ``common.tasks.run_scheduled_reports``).
    """

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    )

    scheduled_report_run = models.ForeignKey(
        ScheduledReportRun, on_delete=models.CASCADE,
        related_name="deliveries",
    )
    recipient_email = models.EmailField()
    delivery_dedupe_key = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default="pending")
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["scheduled_report_run", "status"],
                name="schedreport_run_status_idx"),
            models.Index(
                fields=["delivery_dedupe_key"],
                name="schedreport_dedupe_key_idx"),
        ]

    def __str__(self):
        return f"Delivery {self.status} -> {self.recipient_email}"


class UserNotificationPreference(SoftDeleteModel):
    """Per-user notification channel preferences.

    One row per user (auto-created on user creation via signal or
    lazily on first access). Each channel flag controls whether the user
    wants to receive that category of notification via email (in-app
    notifications are always available). Preserves essential administrative
    and security notifications regardless of preference.
    """

    EMAIL_CATEGORIES = [
        ("ticket_assignment", "Ticket assigned to me"),
        ("ticket_status_change", "Ticket status changed"),
        ("ticket_reply", "New reply or note on my ticket"),
        ("sla_escalation", "SLA escalation / breach"),
        ("maintenance_reminder", "Maintenance reminder"),
        ("asset_assignment", "Asset assigned or returned"),
        ("system_alert", "System alerts"),
        ("kb_review", "Knowledge Base review / publication"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    email_enabled = models.BooleanField(default=True,
                                        help_text="Master switch for email notifications.")
    categories = models.JSONField(default=dict, blank=True,
                                  help_text="Per-category email opt-in map: "
                                            "{category_key: true/false}.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"], name="usernotifpref_user_idx"),
        ]

    def __str__(self):
        return f"Notification prefs for {self.user_id}"

    def email_enabled_for(self, category):
        """True if the user wants email for this category."""
        if not self.email_enabled:
            return False
        return bool(self.categories.get(category, True))


# ---------------------------------------------------------------------------
# Phase 26 — Observability, monitoring and operational governance models.
# ---------------------------------------------------------------------------

HEALTH_STATE_CHOICES = [
    ("healthy", "Healthy"),
    ("degraded", "Degraded"),
    ("unavailable", "Unavailable"),
    ("unknown", "Unknown"),
    ("not_configured", "Not configured"),
]


class HealthCheckResult(models.Model):
    """Result of a component health check.

    One row per check run: which component was checked, the resulting health
    state, when it was evaluated, the last successful check timestamp, the
    last failure timestamp and a non-sensitive diagnostic summary. Used by
    the system health dashboard and by scheduled monitoring tasks.

    Credentials, connection strings, tokens and request bodies are never
    stored here.
    """

    COMPONENT_CHOICES = [
        ("backend", "Django backend"),
        ("database", "Database"),
        ("redis", "Redis"),
        ("celery_worker", "Celery worker"),
        ("celery_beat", "Celery beat"),
        ("background_tasks", "Background tasks"),
        ("email", "Email infrastructure"),
        ("storage", "File/media storage"),
        ("application_errors", "Application errors"),
    ]

    component = models.CharField(max_length=40, choices=COMPONENT_CHOICES,
                                 db_index=True)
    state = models.CharField(max_length=20, choices=HEALTH_STATE_CHOICES,
                             db_index=True)
    evaluated_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_successful_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    diagnostic = models.TextField(blank=True, default="",
                                  help_text="Non-sensitive diagnostic summary.")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-evaluated_at"]
        indexes = [
            models.Index(fields=["component", "state"], name="health_comp_state_idx"),
            models.Index(fields=["component", "evaluated_at"],
                         name="health_comp_eval_idx"),
        ]

    def __str__(self):
        return f"{self.get_component_display()} {self.get_state_display()} @ {self.evaluated_at:%Y-%m-%d %H:%M}"


class OperationalErrorEvent(models.Model):
    """Structured, sanitized record of an operational error.

    Captures API failures, authentication failures, database errors, email
    delivery failures, storage failures and integration failures. Deduplicated
    by ``dedup_key`` so a repeating exception does not create a new row each
    time — instead ``occurrence_count`` and ``last_occurred`` are updated.

    Passwords, tokens, personal data and sensitive request bodies are never
    stored.
    """

    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    COMPONENT_CHOICES = [
        ("api", "API request"),
        ("auth", "Authentication"),
        ("database", "Database"),
        ("background_task", "Background task"),
        ("email", "Email"),
        ("storage", "Storage"),
        ("integration", "Integration"),
        ("monitoring", "Monitoring"),
        ("other", "Other"),
    ]

    dedup_key = models.CharField(max_length=128, db_index=True,
                                 help_text="Stable hash identifying the same error class.")
    component = models.CharField(max_length=30, choices=COMPONENT_CHOICES,
                                 db_index=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES,
                                default="medium")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default="",
                               help_text="Sanitized error summary — no secrets.")
    correlation_id = models.CharField(max_length=64, blank=True, default="",
                                      db_index=True)
    endpoint = models.CharField(max_length=200, blank=True, default="")
    status_code = models.PositiveIntegerField(null=True, blank=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    first_occurred = models.DateTimeField(auto_now_add=True)
    last_occurred = models.DateTimeField(auto_now=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resolved_errors")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_occurred"]
        indexes = [
            models.Index(fields=["component", "resolved"], name="err_comp_resolved_idx"),
            models.Index(fields=["dedup_key"], name="err_dedup_idx"),
            models.Index(fields=["last_occurred"], name="err_last_occurred_idx"),
        ]

    def __str__(self):
        return f"{self.title} [{self.component}] x{self.occurrence_count}"


class OperationalAlert(models.Model):
    """Operational alert for an ongoing or recurring infrastructure issue.

    Alerts are deduplicated by ``dedup_key`` so a persistent failure does not
    flood notifications. Severity drives urgency; acknowledgement and
    resolution track the human response.
    """

    SEVERITY_CHOICES = [
        ("informational", "Informational"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    ]

    STATUS_CHOICES = [
        ("open", "Open"),
        ("acknowledged", "Acknowledged"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    COMPONENT_CHOICES = [
        ("database", "Database"),
        ("redis", "Redis"),
        ("celery_worker", "Celery worker"),
        ("celery_beat", "Celery beat"),
        ("background_tasks", "Background tasks"),
        ("email", "Email"),
        ("storage", "Storage"),
        ("application_errors", "Application errors"),
        ("other", "Other"),
    ]

    dedup_key = models.CharField(max_length=128, unique=True, db_index=True,
                                 help_text="Stable key preventing alert floods.")
    component = models.CharField(max_length=30, choices=COMPONENT_CHOICES,
                                 db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES,
                                db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default="open", db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_occurred = models.DateTimeField(auto_now=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="acknowledged_alerts")
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resolved_alerts")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["component", "status"], name="alert_comp_status_idx"),
            models.Index(fields=["severity", "status"], name="alert_sev_status_idx"),
            models.Index(fields=["last_occurred"], name="alert_last_occurred_idx"),
        ]

    def __str__(self):
        return f"{self.get_severity_display()} {self.title} [{self.get_status_display()}]"


class OperationalIncident(models.Model):
    """Lightweight operational incident tracking.

    Distinct from employee support tickets: incidents track system-level
    operational issues (outages, repeated failures, degraded components) and
    may optionally be linked to an existing ticket for customer-facing
    coordination.
    """

    SEVERITY_CHOICES = [
        ("informational", "Informational"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    ]

    STATUS_CHOICES = [
        ("open", "Open"),
        ("investigating", "Investigating"),
        ("identified", "Identified"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES,
                                db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default="open", db_index=True)
    affected_component = models.CharField(max_length=80, blank=True, default="")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_incidents")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    related_ticket = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Optional existing ticket id linked for coordination.")
    related_alerts = models.JSONField(default=list, blank=True,
                                      help_text="Related alert ids.")
    internal_notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "severity"], name="incident_status_sev_idx"),
            models.Index(fields=["assigned_to"], name="incident_assigned_idx"),
            models.Index(fields=["created_at"], name="incident_created_idx"),
        ]

    def __str__(self):
        return f"{self.title} [{self.get_status_display()}]"
