"""Serializers for the Backup & DR app."""
from rest_framework import serializers
from .models import BackupSchedule, BackupJob, RestorePoint


class BackupScheduleSerializer(serializers.ModelSerializer):
    job_count = serializers.SerializerMethodField(read_only=True)
    last_job_status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BackupSchedule
        fields = [
            "id", "name", "schedule_type", "frequency", "time", "targets",
            "enabled", "retention_days", "last_run", "last_status",
            "job_count", "last_job_status", "created_by", "created_at",
            "updated_at", "is_deleted", "deleted_at",
        ]
        read_only_fields = [
            "id", "created_by", "created_at", "updated_at",
            "last_run", "last_status", "job_count", "last_job_status",
        ]

    def get_job_count(self, obj):
        return obj.jobs.count()

    def get_last_job_status(self, obj):
        last = obj.jobs.order_by("-created_at").first()
        return last.status if last else None

    def validate_time(self, value):
        # Any time value is acceptable; Django's TimeField handles parsing.
        return value


class BackupJobSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source="schedule.name", read_only=True, allow_null=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True, allow_null=True)
    duration_seconds = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BackupJob
        fields = [
            "id", "schedule", "schedule_name", "job_type", "status",
            "started", "finished", "duration", "duration_seconds", "size",
            "target", "error", "created_by", "created_by_email",
            "created_at", "updated_at", "is_deleted",
        ]
        read_only_fields = [
            "id", "schedule_name", "created_by_email", "duration_seconds",
            "created_at", "updated_at",
        ]

    def get_duration_seconds(self, obj):
        return obj.duration_seconds


class RestorePointSerializer(serializers.ModelSerializer):
    job_id = serializers.CharField(source="job.id", read_only=True, allow_null=True)
    schedule_name = serializers.CharField(source="schedule.name", read_only=True, allow_null=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True, allow_null=True)
    is_expired = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = RestorePoint
        fields = [
            "id", "job", "job_id", "schedule", "schedule_name", "restore_type",
            "status", "created", "expires_at", "size", "target",
            "created_by", "created_by_email", "updated_at",
            "is_deleted", "is_expired",
        ]
        read_only_fields = [
            "id", "job_id", "schedule_name", "created_by_email",
            "created", "updated_at", "is_expired",
        ]

    def get_is_expired(self, obj):
        return obj.is_expired
