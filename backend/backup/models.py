"""Data models for the Backup & DR app.

Implements persistent backup schedules, job history, and restore points.
Replaces the previous placeholder with real database-backed models.
"""
from django.db import models
from django.utils import timezone
from django.conf import settings

from common.models import SoftDeleteModel


class BackupSchedule(SoftDeleteModel):
    """A recurring backup schedule definition.

    Schedules define what to back up, how often, and retention policy.
    Actual backup runs are recorded as BackupJob rows.
    """

    SCHEDULE_TYPE_CHOICES = [
        ("config", "Configuration"),
        ("database", "Database"),
        ("files", "File shares"),
        ("media", "Media / attachments"),
    ]

    FREQUENCY_CHOICES = [
        ("hourly", "Hourly"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
    ]

    name = models.CharField(max_length=120)
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPE_CHOICES)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    time = models.TimeField(help_text="UTC time of day to run (for daily/weekly/monthly).")
    targets = models.JSONField(
        default=list,
        blank=True,
        help_text="List of target hosts/paths/databases to back up.",
    )
    enabled = models.BooleanField(default=True, db_index=True)
    retention_days = models.PositiveIntegerField(
        default=30,
        help_text="How many days to keep completed backup jobs/restore points.",
    )
    last_run = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Status of the most recent run (success/failed/skipped/paused).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backup_schedules_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_deleted", "enabled"], name="backup_schedule_enabled_idx"),
            models.Index(fields=["schedule_type"], name="backup_schedule_type_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.schedule_type}, {self.frequency})"

    def soft_delete(self, by_user=None, reason=""):
        # Also soft-delete any non-terminal jobs tied to this schedule.
        super().soft_delete(by_user=by_user, reason=reason)
        self.jobs.filter(status__in=("pending", "running")).update(
            status="cancelled",
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by=by_user,
            deletion_reason=reason or "Schedule deleted",
        )


class BackupJob(SoftDeleteModel):
    """A single backup execution record.

    One row per scheduled or manual backup run. Tracks status, duration,
    size, target, and any error message.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
        ("cancelled", "Cancelled"),
    ]

    schedule = models.ForeignKey(
        BackupSchedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs",
        help_text="The schedule that triggered this job (null for manual runs).",
    )
    job_type = models.CharField(max_length=20, choices=BackupSchedule.SCHEDULE_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)
    duration = models.CharField(max_length=40, blank=True, default="")
    size = models.CharField(max_length=40, blank=True, default="")
    target = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backup_jobs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_deleted", "status"], name="backup_job_status_idx"),
            models.Index(fields=["schedule", "-created_at"], name="backup_job_schedule_idx"),
            models.Index(fields=["-created_at"], name="backup_job_created_idx"),
        ]

    def __str__(self):
        return f"BackupJob #{self.pk} ({self.job_type}) - {self.status}"

    @property
    def duration_seconds(self):
        if self.started and self.finished:
            return int((self.finished - self.started).total_seconds())
        return None


class RestorePoint(SoftDeleteModel):
    """A recoverable backup snapshot.

    Created from successful BackupJob rows. Can be used to restore data.
    """

    STATUS_CHOICES = [
        ("available", "Available"),
        ("restoring", "Restoring"),
        ("expired", "Expired"),
        ("corrupt", "Corrupt"),
    ]

    job = models.ForeignKey(
        BackupJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restore_points",
        help_text="The backup job that produced this restore point.",
    )
    schedule = models.ForeignKey(
        BackupSchedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restore_points",
    )
    restore_type = models.CharField(max_length=20, choices=BackupSchedule.SCHEDULE_TYPE_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="available",
        db_index=True,
    )
    created = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    size = models.CharField(max_length=40, blank=True, default="")
    target = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restore_points_created",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["is_deleted", "status"], name="restore_point_status_idx"),
            models.Index(fields=["-created"], name="restore_point_created_idx"),
        ]

    def __str__(self):
        return f"RestorePoint #{self.pk} ({self.restore_type}) - {self.status}"

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at
