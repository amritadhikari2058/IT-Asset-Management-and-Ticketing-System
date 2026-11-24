"""Views for the Backup & DR app.

Provides CRUD for backup schedules, job history, and restore points.
All mutating endpoints are IT-staff or system-admin only.
"""
import os

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from common.permissions import IsSystemAdmin, IsITStaff
from common.audit import log_action

from .models import BackupSchedule, BackupJob, RestorePoint
from .serializers import (
    BackupScheduleSerializer,
    BackupJobSerializer,
    RestorePointSerializer,
)


class BackupScheduleViewSet(viewsets.ModelViewSet):
    """CRUD for backup schedules. IT staff only."""

    queryset = BackupSchedule.objects.filter(
        is_deleted=False
    ).annotate(job_count_annotated=Count("jobs")).order_by("name")
    serializer_class = BackupScheduleSerializer
    permission_classes = [IsITStaff]

    def get_queryset(self):
        return super().get_queryset()

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_action(actor=self.request.user, action="create", instance=obj,
                   details={"schedule_type": obj.schedule_type, "frequency": obj.frequency})

    def perform_update(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        active_jobs = obj.jobs.filter(status__in=("pending", "running")).count()
        if active_jobs:
            return Response(
                {"detail": f"Cannot delete schedule: {active_jobs} active job(s). "
                           f"Wait or cancel them first."},
                status=status.HTTP_409_CONFLICT,
            )
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[IsITStaff])
    def toggle(self, request, pk=None):
        """Enable/disable a schedule."""
        obj = self.get_object()
        obj.enabled = not obj.enabled
        obj.save(update_fields=["enabled", "updated_at"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"enabled": obj.enabled})
        return Response({"enabled": obj.enabled, "id": obj.pk})

    @action(detail=True, methods=["post"], permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = BackupSchedule.all_objects.get(pk=pk)
        with transaction.atomic():
            from common.models import AuditLog
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="backup.BackupSchedule", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})

    @action(detail=True, methods=["post"], permission_classes=[IsSystemAdmin])
    def restore(self, request, pk=None):
        obj = BackupSchedule.all_objects.get(pk=pk)
        if not obj.is_deleted:
            return Response({"detail": "Not deleted."}, status=400)
        obj.restore()
        log_action(actor=request.user, action="restore", instance=obj)
        return Response(BackupScheduleSerializer(obj).data)


class BackupJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only view of backup job history. IT staff only."""

    queryset = BackupJob.objects.filter(is_deleted=False).order_by("-created_at")
    serializer_class = BackupJobSerializer
    permission_classes = [IsITStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        schedule = self.request.query_params.get("schedule")
        if schedule:
            qs = qs.filter(schedule_id=schedule)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        job_type = self.request.query_params.get("type")
        if job_type:
            qs = qs.filter(job_type=job_type)
        return qs

    @action(detail=False, methods=["post"], permission_classes=[IsITStaff])
    def run_manual(self, request):
        """Trigger a manual backup job (enqueues a Celery task).

        Accepts { "type": "config|database|files|media", "target": "..." }
        """
        from .tasks import run_backup_job
        job_type = request.data.get("type")
        target = request.data.get("target", "")
        if job_type not in dict(BackupSchedule.SCHEDULE_TYPE_CHOICES):
            return Response({"detail": "Invalid backup type."}, status=400)
        job = BackupJob.objects.create(
            job_type=job_type,
            status="pending",
            target=target,
            created_by=request.user,
        )
        run_backup_job.delay(str(job.pk))
        return Response(BackupJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], permission_classes=[IsITStaff])
    def cancel(self, request, pk=None):
        obj = self.get_object()
        if obj.status not in ("pending", "running"):
            return Response(
                {"detail": f"Cannot cancel a {obj.status} job."},
                status=status.HTTP_409_CONFLICT,
            )
        obj.status = "cancelled"
        obj.finished = timezone.now()
        obj.error = "Cancelled by user."
        obj.save(update_fields=["status", "finished", "error", "updated_at"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"cancelled": True})
        return Response(BackupJobSerializer(obj).data)

    @action(detail=True, methods=["get"], permission_classes=[IsITStaff])
    def download(self, request, pk=None):
        """Download a backup artifact. IT staff only; path-traversal protected."""
        obj = self.get_object()
        artifact_path = (obj.artifact_path or "").strip()
        if not artifact_path:
            return Response({"detail": "No artifact available for this job."}, status=404)

        base = getattr(settings, "BACKUP_ARTIFACT_DIR", None) or (
            settings.BASE_DIR / "backup_artifacts")
        base_real = os.path.realpath(str(base))
        artifact_real = os.path.realpath(artifact_path)
        try:
            common = os.path.commonpath([base_real, artifact_real])
        except ValueError:
            common = ""
        if common != base_real:
            return Response({"detail": "Artifact path is not allowed."}, status=400)
        if not os.path.isfile(artifact_real):
            return Response({"detail": "Artifact file not found."}, status=404)

        filename = os.path.basename(artifact_real)
        log_action(actor=request.user, action="download", instance=obj,
                   details={"filename": filename})
        return FileResponse(open(artifact_real, "rb"), as_attachment=True,
                            filename=filename)


class RestorePointViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only view of restore points. IT staff only."""

    queryset = RestorePoint.objects.filter(is_deleted=False).order_by("-created")
    serializer_class = RestorePointSerializer
    permission_classes = [IsITStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        restore_type = self.request.query_params.get("type")
        if restore_type:
            qs = qs.filter(restore_type=restore_type)
        return qs

    @action(detail=True, methods=["post"], permission_classes=[IsITStaff])
    def restore(self, request, pk=None):
        """Mark a restore point as in-progress (actual restore is backend-specific)."""
        obj = self.get_object()
        if obj.status != "available":
            return Response(
                {"detail": f"Cannot restore from a {obj.status} point."},
                status=status.HTTP_409_CONFLICT,
            )
        if obj.is_expired:
            return Response({"detail": "Restore point has expired."}, status=409)
        # Actual restore execution is environment-specific and not automated here.
        # We record the intent for audit/operational tracking.
        obj.status = "restoring"
        obj.save(update_fields=["status", "updated_at"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"restore_requested": True})
        return Response({
            "detail": "Restore marked as requested. Perform the environment-specific restore procedure using the recorded artifact.",
            "id": obj.pk,
            "artifact_path": obj.job.artifact_path if obj.job_id else "",
        })

    @action(detail=False, methods=["post"], permission_classes=[IsSystemAdmin])
    def expire_old(self, request):
        """Expire restore points past their retention window. System admin only."""
        now = timezone.now()
        expired = RestorePoint.objects.filter(
            is_deleted=False,
            expires_at__isnull=False,
            expires_at__lt=now,
            status="available",
        ).update(status="expired", updated_at=now)
        return Response({"expired": expired})
