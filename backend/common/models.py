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
from django.utils import timezone


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"To {self.recipient_id}: {self.title[:60]}"


class PrivacyErasureRequest(models.Model):
    """System-Admin-only privacy erasure workflow (initial version).

    Not a GDPR-compliance claim. Flow: create (reason + scope + confirm) ->
    review dependencies/retention -> execute or reject. The audit log records
    request + outcome WITHOUT the erased personal data (IDs + scope only).
    ``reviewed_by``/approval fields exist so two-person approval can be added
    later; they are not enforced yet.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("executed", "Executed"),
        ("rejected", "Rejected"),
    ]

    entity_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    scope = models.TextField()  # which data to erase, e.g. "email, name, phone"
    reason = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="erasure_requests")
    reviewed_by = models.ForeignKey(  # reserved for future approval step
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="erasure_reviews")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (f"Erasure {self.entity_type}:{self.object_id} "
                f"[{self.status}]")


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

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["scheduled_report", "status"]),
            models.Index(fields=["started_at"]),
        ]

    def __str__(self):
        return f"Run {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


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

