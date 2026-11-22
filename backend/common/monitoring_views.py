"""Phase 26 — monitoring, alerting and incident management APIs.

Permissions are enforced in the backend. Frontend hiding is UX only.
"""
import logging

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.monitoring import run_health_checks, COMPONENTS
from common.monitoring_service import (
    record_error, resolve_error, create_or_update_alert,
    acknowledge_alert, resolve_alert, close_alert,
    create_incident, update_incident,
)
from common.monitoring_metrics import aggregate_api_metrics
from common.models import (HealthCheckResult, OperationalAlert,
                           OperationalErrorEvent, OperationalIncident,
                           BackgroundTaskRun)
from common.permissions import IsSystemAdmin, IsITStaff, is_system_admin

logger = logging.getLogger(__name__)

# Tasks explicitly classified as safe to re-enqueue via the manual retry
# action. Arbitrary task names/arguments are never accepted through the API.
SAFE_RETRY_TASKS = frozenset({
    "common.tasks.process_inbound_mailbox",
    "common.tasks.process_inbound_email_task",
    "common.tasks.run_scheduled_reports",
    "common.tasks.evaluate_retention_policies",
    "common.tasks.execute_retention_policy",
})


def _is_system_admin(user):
    return is_system_admin(user)


def _can_write_incident(user, incident):
    """Incident write permission.

    System Admin: full. IT Manager/IT Support: only incidents assigned to
    them, and only non-privileged fields unless they are the assignee.
    """
    if _is_system_admin(user):
        return True
    if not (user and user.is_authenticated):
        return False
    if incident.assigned_to_id and incident.assigned_to_id == user.pk:
        return True
    return False


@api_view(["GET"])
@permission_classes([IsITStaff])
def system_health(request):
    """Centralized system health dashboard.

    Returns per-component health state (healthy/degraded/unavailable/
    unknown/not_configured) plus an overall state. Reflects actual
    component availability, not configuration alone.
    """
    components = request.query_params.getlist("component") or None
    return Response(run_health_checks(components))


@api_view(["POST"])
@permission_classes([IsITStaff])
def record_application_error(request):
    """Record a sanitized operational error (server-side use).

    Body: {component, title, message?, endpoint?, status_code?,
           correlation_id?, severity?, details?}
    """
    data = request.data or {}
    component = data.get("component", "other")
    title = data.get("title", "Untitled error")
    if not title:
        return Response({"detail": "title is required."}, status=400)
    event = record_error(
        component=component, title=title,
        message=data.get("message", ""),
        endpoint=data.get("endpoint", ""),
        status_code=data.get("status_code"),
        correlation_id=data.get("correlation_id", ""),
        severity=data.get("severity", "medium"),
        details=data.get("details", {}),
    )
    from common.serializers import OperationalErrorEventSerializer
    return Response(OperationalErrorEventSerializer(event).data, status=201)


class HealthCheckResultViewSet(viewsets.ReadOnlyModelViewSet):
    """Health check result history."""

    permission_classes = [IsITStaff]

    def get_queryset(self):
        qs = HealthCheckResult.objects.all().order_by("-evaluated_at")
        component = self.request.query_params.get("component")
        if component:
            qs = qs.filter(component=component)
        state = self.request.query_params.get("state")
        if state:
            qs = qs.filter(state=state)
        return qs

    def list(self, request, *args, **kwargs):
        from common.serializers import HealthCheckResultSerializer
        qs = self.get_queryset()[:100]
        return Response(HealthCheckResultSerializer(qs, many=True).data)


class BackgroundTaskMonitorViewSet(viewsets.ViewSet):
    """Background task execution history (reuses BackgroundTaskRun)."""

    permission_classes = [IsITStaff]

    def list(self, request):
        qs = BackgroundTaskRun.objects.all().order_by("-started_at")
        task_name = request.query_params.get("task_name")
        if task_name:
            qs = qs.filter(task_name=task_name)
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        limit = int(request.query_params.get("limit", "50"))
        qs = qs[:limit]
        data = [{
            "id": r.id, "task_name": r.task_name, "status": r.status,
            "started_at": r.started_at, "finished_at": r.finished_at,
            "success": r.success, "error_summary": r.error_summary,
            "payload": r.payload,
        } for r in qs]
        return Response(data)

    @action(detail=False, methods=["post"])
    def retry_task(self, request):
        """Re-enqueue a safe-to-retry background task.

        Body: {task_name}. Only tasks in SAFE_RETRY_TASKS may be retried.
        Idempotent: a recent running run for the same task blocks a
        duplicate enqueue. Records who initiated the retry.
        """
        task_name = (request.data or {}).get("task_name")
        if not task_name or task_name not in SAFE_RETRY_TASKS:
            return Response(
                {"detail": "Task not eligible for manual retry."},
                status=400)
        recent = (BackgroundTaskRun.objects.filter(task_name=task_name)
                  .order_by("-started_at").first())
        if recent and recent.status == "running":
            return Response(
                {"detail": f"{task_name} already running.",
                 "run": recent.id}, status=409)
        try:
            from celery import current_app
            task = current_app.tasks.get(task_name)
            if task is None:
                return Response(
                    {"detail": f"Task {task_name} not registered."},
                    status=400)
            task.delay()
            BackgroundTaskRun.objects.create(
                task_name=task_name, status="running", success=False,
                started_at=timezone.now(),
                payload={"retried_by": getattr(request.user, "pk", None),
                         "retried_by_email": getattr(request.user, "email",
                                                     None)})
            return Response({"retried": True, "task_name": task_name})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Manual retry of %s failed", task_name)
            return Response(
                {"detail": f"Retry failed: {type(exc).__name__}"},
                status=500)


class OperationalErrorEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Application error events."""

    permission_classes = [IsITStaff]

    def get_queryset(self):
        qs = OperationalErrorEvent.objects.all().order_by("-last_occurred")
        component = self.request.query_params.get("component")
        if component:
            qs = qs.filter(component=component)
        resolved = self.request.query_params.get("resolved")
        if resolved is not None:
            qs = qs.filter(resolved=(resolved.lower() == "true"))
        return qs[:200]

    def list(self, request, *args, **kwargs):
        from common.serializers import OperationalErrorEventSerializer
        qs = self.get_queryset()
        return Response(OperationalErrorEventSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        event = OperationalErrorEvent.objects.filter(pk=pk).first()
        if not event:
            return Response({"detail": "Not found."}, status=404)
        ok, result = resolve_error(event.pk, request.user)
        if not ok:
            return Response({"detail": result}, status=404)
        from common.serializers import OperationalErrorEventSerializer
        return Response(OperationalErrorEventSerializer(result).data)


class OperationalAlertViewSet(viewsets.ViewSet):
    """Operational alerts with acknowledgement and resolution."""

    permission_classes = [IsITStaff]

    def list(self, request):
        qs = OperationalAlert.objects.all().order_by("-created_at")
        component = self.request.query_params.get("component")
        if component:
            qs = qs.filter(component=component)
        severity = self.request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        from common.serializers import OperationalAlertSerializer
        return Response(OperationalAlertSerializer(qs[:200], many=True).data)

    @action(detail=False, methods=["post"])
    def create_alert(self, request):
        """Manually create an operational alert (System Admin only)."""
        if not _is_system_admin(request.user):
            return Response(
                {"detail": "Only System Admin can create alerts."},
                status=403)
        data = request.data or {}
        title = data.get("title", "")
        if not title:
            return Response({"detail": "title is required."}, status=400)
        alert, _ = create_or_update_alert(
            component=data.get("component", "other"),
            severity=data.get("severity", "warning"),
            title=title,
            description=data.get("description", ""),
            details=data.get("details", {}),
        )
        from common.serializers import OperationalAlertSerializer
        return Response(OperationalAlertSerializer(alert).data, status=201)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        ok, result = acknowledge_alert(pk, request.user)
        if not ok:
            return Response({"detail": result}, status=404)
        from common.serializers import OperationalAlertSerializer
        return Response(OperationalAlertSerializer(result).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        ok, result = resolve_alert(pk, request.user)
        if not ok:
            return Response({"detail": result}, status=404)
        from common.serializers import OperationalAlertSerializer
        return Response(OperationalAlertSerializer(result).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        if not _is_system_admin(request.user):
            return Response(
                {"detail": "Only System Admin can close alerts."},
                status=403)
        ok, result = close_alert(pk, request.user)
        if not ok:
            return Response({"detail": result}, status=404)
        from common.serializers import OperationalAlertSerializer
        return Response(OperationalAlertSerializer(result).data)


class OperationalIncidentViewSet(viewsets.ViewSet):
    """Operational incidents (distinct from support tickets)."""

    permission_classes = [IsITStaff]

    def list(self, request):
        user = request.user
        qs = OperationalIncident.objects.all().order_by("-created_at")
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        severity = request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        assigned = request.query_params.get("assigned")
        if assigned is not None and assigned.lower() == "me" \
                and not _is_system_admin(user):
            qs = qs.filter(assigned_to=user)
        from common.serializers import OperationalIncidentSerializer
        return Response(OperationalIncidentSerializer(qs[:200], many=True).data)

    def create(self, request):
        if not _is_system_admin(request.user):
            return Response(
                {"detail": "Only System Admin can create incidents."},
                status=403)
        data = request.data or {}
        title = data.get("title", "")
        if not title:
            return Response({"detail": "title is required."}, status=400)
        incident = create_incident(
            title=title, description=data.get("description", ""),
            severity=data.get("severity", "warning"),
            affected_component=data.get("affected_component", ""),
            assigned_to=data.get("assigned_to"),
            related_ticket=data.get("related_ticket"),
            related_alerts=data.get("related_alerts", []),
            internal_notes=data.get("internal_notes", ""))
        from common.serializers import OperationalIncidentSerializer
        return Response(OperationalIncidentSerializer(incident).data,
                        status=201)

    def retrieve(self, request, pk=None):
        incident = OperationalIncident.objects.filter(pk=pk).first()
        if not incident:
            return Response({"detail": "Not found."}, status=404)
        from common.serializers import OperationalIncidentSerializer
        return Response(OperationalIncidentSerializer(incident).data)

    def update(self, request, pk=None):
        incident = OperationalIncident.objects.filter(pk=pk).first()
        if not incident:
            return Response({"detail": "Not found."}, status=404)
        if not _can_write_incident(request.user, incident):
            return Response(
                {"detail": "You may only update incidents assigned to you."},
                status=403)
        if not _is_system_admin(request.user):
            data = {k: v for k, v in (request.data or {}).items()
                    if k not in ("severity", "assigned_to")}
        else:
            data = request.data or {}
        ok, result = update_incident(incident.pk, request.user, **data)
        if not ok:
            return Response({"detail": result}, status=404)
        from common.serializers import OperationalIncidentSerializer
        return Response(OperationalIncidentSerializer(result).data)

    def partial_update(self, request, pk=None):
        return self.update(request, pk)

    def destroy(self, request, pk=None):
        if not _is_system_admin(request.user):
            return Response(
                {"detail": "Only System Admin can delete incidents."},
                status=403)
        incident = OperationalIncident.objects.filter(pk=pk).first()
        if not incident:
            return Response({"detail": "Not found."}, status=404)
        incident.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        incident = OperationalIncident.objects.filter(pk=pk).first()
        if not incident:
            return Response({"detail": "Not found."}, status=404)
        if not _can_write_incident(request.user, incident):
            return Response(
                {"detail": "You may only assign incidents assigned to you."},
                status=403)
        assigned = (request.data or {}).get("assigned_to")
        from accounts.models import User
        user = None
        if assigned:
            user = User.objects.filter(pk=assigned).first()
            if not user:
                return Response({"detail": "Assignee not found."}, status=404)
        ok, result = update_incident(incident.pk, request.user,
                                     assigned_to=user.pk if user else None)
        from common.serializers import OperationalIncidentSerializer
        return Response(OperationalIncidentSerializer(result).data)


class ApiPerformanceViewSet(viewsets.ViewSet):
    """Aggregated API performance metrics (from cache, no per-request DB)."""

    permission_classes = [IsITStaff]

    def list(self, request):
        minutes = int(request.query_params.get("minutes", "60"))
        data = aggregate_api_metrics(minutes=minutes)
        return Response({"minutes": minutes, "endpoints": data})


class EmailStorageHealthViewSet(viewsets.ViewSet):
    """Email and storage health detail (subset of system health)."""

    permission_classes = [IsITStaff]

    def list(self, request):
        result = run_health_checks(["email", "storage"])
        return Response(result)


class NotificationOutboxViewSet(viewsets.ViewSet):
    """Operational visibility and safe recovery for the notification outbox.

    Read access: IT staff / admins. Manual retry / cancel: System Admin only,
    and every privileged action is recorded in the audit log.
    """

    permission_classes = [IsITStaff]

    def list(self, request):
        from common.models import NotificationOutboxEvent
        from common.outbox import get_outbox_stats
        from common.serializers import NotificationOutboxEventSerializer

        qs = NotificationOutboxEvent.objects.all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        event_type = request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)
        limit = min(int(request.query_params.get("limit", "50")), 200)
        qs = qs.order_by("-created_at")[:limit]
        return Response({
            "stats": get_outbox_stats(),
            "events": NotificationOutboxEventSerializer(qs, many=True).data,
        })

    @action(detail=True, methods=["get"])
    def inspect(self, request, pk=None):
        """Full event detail including the structured payload (admins only)."""
        if not is_system_admin(request.user):
            return Response(
                {"detail": "Only System Admin may inspect payloads."},
                status=403)
        from common.models import NotificationOutboxEvent
        from common.serializers import NotificationOutboxEventSerializer
        event = NotificationOutboxEvent.objects.filter(pk=pk).first()
        if event is None:
            return Response({"detail": "Not found."}, status=404)
        data = NotificationOutboxEventSerializer(event).data
        data["payload"] = event.payload
        return Response(data)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def retry(self, request, pk=None):
        """Re-queue a failed/cancelled event (System Admin only, audited)."""
        from common.audit import log_action
        from common.outbox import retry_event
        ok, result = retry_event(pk)
        if not ok:
            return Response({"detail": result}, status=400)
        log_action(actor=request.user, action="update",
                   instance=result, reason="manual_outbox_retry",
                   details={"event_type": result.event_type,
                            "recipient_email": result.recipient_email})
        return Response({"retried": True, "id": str(result.id),
                         "status": result.status})

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def cancel(self, request, pk=None):
        """Cancel a pending/retry/processing event (System Admin, audited)."""
        from common.audit import log_action
        from common.outbox import cancel_event
        reason = (request.data or {}).get("reason", "")
        ok, result = cancel_event(pk, reason=reason)
        if not ok:
            return Response({"detail": result}, status=400)
        log_action(actor=request.user, action="update", instance=result,
                   reason="manual_outbox_cancel",
                   details={"event_type": result.event_type,
                            "recipient_email": result.recipient_email})
        return Response({"cancelled": True, "id": str(result.id),
                         "status": result.status})
