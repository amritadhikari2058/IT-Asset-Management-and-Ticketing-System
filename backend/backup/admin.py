"""Admin registration for the Backup & DR app."""
from django.contrib import admin

from .models import BackupSchedule, BackupJob, RestorePoint


@admin.register(BackupSchedule)
class BackupScheduleAdmin(admin.ModelAdmin):
    list_display = ("name", "schedule_type", "frequency", "time",
                    "enabled", "retention_days", "last_run", "last_status")
    list_filter = ("schedule_type", "frequency", "enabled", "is_deleted")
    search_fields = ("name", "targets")
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at", "last_run", "last_status")


@admin.register(BackupJob)
class BackupJobAdmin(admin.ModelAdmin):
    list_display = ("id", "job_type", "status", "schedule", "started",
                    "finished", "size", "target", "is_deleted")
    list_filter = ("job_type", "status", "is_deleted")
    search_fields = ("target", "error", "schedule__name")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at", "started", "finished")


@admin.register(RestorePoint)
class RestorePointAdmin(admin.ModelAdmin):
    list_display = ("id", "restore_type", "status", "schedule", "created",
                    "expires_at", "size", "is_expired", "is_deleted")
    list_filter = ("restore_type", "status", "is_deleted")
    search_fields = ("target", "schedule__name")
    ordering = ("-created",)
    readonly_fields = ("created", "updated_at", "is_expired")
