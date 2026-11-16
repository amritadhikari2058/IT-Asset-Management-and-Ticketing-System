"""Views for monitoring module."""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from .models import MonitoringSource, MonitoringAlert, MonitoringEvent
from .serializers import (
    MonitoringSourceListSerializer,
    MonitoringSourceCreateSerializer,
    MonitoringEventSerializer,
    MonitoringAlertSerializer,
)
from .permissions import SystemAdminPermission
from .authentication import MonitoringAuthentication


class MonitoringEventViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for MonitoringEvent read-only access."""

    queryset = MonitoringEvent.objects.all()
    serializer_class = MonitoringEventSerializer
    authentication_classes = []
    permission_classes = [SystemAdminPermission]


class MonitoringAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for MonitoringAlert with action endpoints."""

    queryset = MonitoringAlert.objects.all()
    serializer_class = MonitoringAlertSerializer
    authentication_classes = []
    permission_classes = [SystemAdminPermission]

    @action(methods=["POST"], detail=True, url_path="acknowledge")
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        user = request.user
        if user.role not in ("it_support", "it_manager", "system_admin"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        alert.acknowledged_by = user
        alert.acknowledged_at = timezone.now()
        alert.status = alert.AlertStatus.ACKNOWLEDGED
        alert.save(update_fields=["acknowledged_by", "acknowledged_at", "status"])
        return Response({"detail": "Alert acknowledged."})

    @action(methods=["POST"], detail=True, url_path="assign")
    def assign(self, request, pk=None):
        alert = self.get_object()
        user = request.user
        if user.role not in ("it_support", "it_manager", "system_admin"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        assignee_id = request.data.get("user")
        if assignee_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                assignee = User.objects.get(id=assignee_id)
                alert.assigned_to = assignee
                alert.save(update_fields=["assigned_to"])
            except User.DoesNotExist:
                return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "Alert assigned."})

    @action(methods=["POST"], detail=True, url_path="suppress")
    def suppress(self, request, pk=None):
        alert = self.get_object()
        reason = request.data.get("reason")
        if not reason:
            return Response({"detail": "Reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        if alert.severity == alert.AlertSeverity.CRITICAL:
            if user.role != "system_admin":
                return Response({"detail": "Critical alert suppression requires System Admin."}, status=status.HTTP_403_FORBIDDEN)
        alert.status = alert.AlertStatus.SUPPRESSED
        alert.suppression_count = (alert.suppression_count or 0) + 1
        alert.save(update_fields=["status", "suppression_count"])
        return Response({"detail": "Alert suppressed."})

    @action(methods=["POST"], detail=True, url_path="unsuppress")
    def unsuppress(self, request, pk=None):
        alert = self.get_object()
        alert.status = alert.AlertStatus.OPEN
        alert.save(update_fields=["status"])
        return Response({"detail": "Alert unsuppressed."})

    @action(methods=["POST"], detail=True, url_path="resolve")
    def resolve(self, request, pk=None):
        alert = self.get_object()
        user = request.user
        if user.role not in ("it_support", "it_manager", "system_admin"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        alert.status = alert.AlertStatus.RESOLVED
        alert.save(update_fields=["status"])
        return Response({"detail": "Alert resolved."})

    @action(methods=["POST"], detail=True, url_path="close")
    def close(self, request, pk=None):
        alert = self.get_object()
        user = request.user
        if user.role not in ("it_manager", "system_admin"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        alert.status = alert.AlertStatus.CLOSED
        alert.closed_at = timezone.now()
        alert.save(update_fields=["status", "closed_at"])
        return Response({"detail": "Alert closed."})

    @action(methods=["POST"], detail=True, url_path="reopen")
    def reopen(self, request, pk=None):
        alert = self.get_object()
        user = request.user
        if user.role not in ("it_support", "it_manager", "system_admin"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        alert.status = alert.AlertStatus.OPEN
        alert.save(update_fields=["status"])
        return Response({"detail": "Alert reopened."})

class MonitoringSourceViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for MonitoringSource management."""

    queryset = MonitoringSource.objects.all()
    serializer_class = MonitoringSourceListSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return MonitoringSourceCreateSerializer
        return MonitoringSourceListSerializer

    def get_permissions(self):
        if self.action in ["create", "rotate_secret"]:
            return [SystemAdminPermission()]
        return super().get_permissions()

    @action(methods=["POST"], detail=True, url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        source = self.get_object()
        return Response({"detail": "Secret rotation not yet implemented."})

    @action(methods=["POST"], detail=True, url_path="disable")
    def disable(self, request, pk=None):
        source = self.get_object()
        source.is_active = False
        source.save(update_fields=["is_active"])
        return Response({"detail": "Source disabled."})

    @action(methods=["POST"], detail=True, url_path="enable")
    def enable(self, request, pk=None):
        source = self.get_object()
        source.is_active = True
        source.save(update_fields=["is_active"])
        return Response({"detail": "Source enabled."})

    @action(methods=["POST"], detail=True, url_path="test")
    def test(self, request, pk=None):
        source = self.get_object()
        return Response({"detail": "Configuration valid."})

class ReportViewSet(viewsets.ViewSet):
    """ViewSet for monitoring reports."""

    authentication_classes = []
    permission_classes = [SystemAdminPermission]
def ingest_event(request, source_code):
    """Ingest a single monitoring event."""
    return Response({"detail": "Ingestion endpoint requires implementation."})


def ingest_batch_events(request, source_code):
    """Ingest a batch of monitoring events."""
    return Response({"detail": "Batch ingestion requires implementation."})


def manual_event(request):
    """Create a manual monitoring event."""
    return Response({"detail": "Manual event creation requires implementation."})
class DashboardViewSet(viewsets.ViewSet):
    """ViewSet for monitoring dashboard data."""

    authentication_classes = []
    permission_classes = [SystemAdminPermission]

    def list(self, request):
        return Response({"detail": "Dashboard data requires implementation."})