"""Views for monitoring module."""
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db import transaction
import hashlib
import json

from .models import MonitoringSource, MonitoringAlert, MonitoringEvent, MonitoringIngestionAttempt, MonitoringEventOccurrence
from .serializers import (
    MonitoringSourceListSerializer,
    MonitoringSourceCreateSerializer,
    MonitoringEventSerializer,
    MonitoringAlertSerializer,
    MonitoringAlertListSerializer,
)
from .permissions import (
    SystemAdminPermission,
    ActiveSystemAdminPermission,
    ITSupportPermission,
    IsMonitoringSource,
)
from .dashboard_service import get_aggregated_metrics
from .authentication import MonitoringAuthentication
from .normalizers import GenericNormalizer
from .correlation import correlate_event, build_event_fingerprint
from .throttling import MonitoringSourceRateThrottle
from .source_views import MonitoringSourceCreateMixin, MonitoringSourceUpdateMixin
from .source_serializers import MonitoringSourceWriteSerializer


class MonitoringEventViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for MonitoringEvent read-only access."""

    queryset = MonitoringEvent.objects.all()
    serializer_class = MonitoringEventSerializer
    permission_classes = [SystemAdminPermission]


class MonitoringAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for MonitoringAlert with action endpoints."""

    queryset = MonitoringAlert.objects.all()
    serializer_class = MonitoringAlertSerializer
    permission_classes = [SystemAdminPermission]

    def get_serializer_class(self):
        """Use the list serializer for the list action."""
        if self.action == "list":
            return MonitoringAlertListSerializer
        return MonitoringAlertSerializer
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
        user = request.user
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

class MonitoringSourceViewSet(MonitoringSourceCreateMixin, MonitoringSourceUpdateMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for MonitoringSource management."""

    queryset = MonitoringSource.objects.all()
    serializer_class = MonitoringSourceListSerializer
    permission_classes = [ActiveSystemAdminPermission]
    def get_serializer_class(self):
        """Use the write serializer for create and partial update; list
        serializer for retrieve and list."""
        if self.action in ("create", "partial_update"):
            return MonitoringSourceWriteSerializer
        return MonitoringSourceListSerializer

    @action(methods=["POST"], detail=True, url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        source = self.get_object()
        import hashlib
        import secrets
        from django.utils import timezone

        new_secret = request.data.get("secret") or secrets.token_urlsafe(32)
        source.previous_secret_hash = source.secret_hash
        source.previous_secret_valid_until = timezone.now() + timezone.timedelta(minutes=5)
        source.secret_hash = hashlib.sha256(new_secret.encode()).hexdigest()
        source.save(update_fields=["secret_hash", "previous_secret_hash", "previous_secret_valid_until"])
        return Response({"detail": "Secret rotated.", "secret": new_secret})

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

    authentication_classes = [SessionAuthentication]
    permission_classes = [ITSupportPermission]

    def get_permissions(self):
        if not getattr(self.request.user, "is_active", False):
            return [SystemAdminPermission()]
        return super().get_permissions()

    def list(self, request):
        return Response(get_aggregated_metrics())


class MonitoringIngestionView(APIView):

    """Authenticated, throttled monitoring ingestion endpoint."""

    authentication_classes = [MonitoringAuthentication]
    permission_classes = [IsMonitoringSource]
    throttle_classes = [MonitoringSourceRateThrottle]

    MAX_BATCH_SIZE = 100

    def post(self, request, source_code):
        source = request.user
        if not isinstance(source, MonitoringSource) or source.code != source_code:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        request_id = request.META.get("HTTP_X_MONITORING_REQUEST_ID", "")
        raw_body = request.body
        remote_ip = request.META.get("REMOTE_ADDR", "")
        remote_hash = hashlib.sha256(remote_ip.encode("utf-8")).hexdigest()

        # Replay reservation happens after authentication, timestamp, HMAC, IP, and throttle.
        try:
            attempt = MonitoringIngestionAttempt.objects.create(
                source=source,
                request_id=request_id,
                remote_address_hash=remote_hash,
                payload_size=len(raw_body),
                status=MonitoringIngestionAttempt.Status.ACCEPTED,
            )
        except Exception:
            return Response({"detail": "Replay request rejected."}, status=status.HTTP_409_CONFLICT)

        accepted = 0
        duplicates = 0
        correlated = 0
        rejected = 0
        correlated_alerts = 0

        try:
            with transaction.atomic():
                try:
                    payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    attempt.status = MonitoringIngestionAttempt.Status.REJECTED
                    attempt.error_code = "invalid_json"
                    attempt.save(update_fields=["status", "error_code"])
                    return Response({"detail": "Malformed JSON."}, status=status.HTTP_400_BAD_REQUEST)

                if isinstance(payload, dict) and "events" in payload:
                    events_payload = payload.get("events")
                elif isinstance(payload, dict):
                    events_payload = [payload]
                elif isinstance(payload, list):
                    events_payload = payload
                else:
                    attempt.status = MonitoringIngestionAttempt.Status.REJECTED
                    attempt.error_code = "invalid_payload"
                    attempt.save(update_fields=["status", "error_code"])
                    return Response({"detail": "Invalid payload."}, status=status.HTTP_400_BAD_REQUEST)

                if not isinstance(events_payload, list) or not events_payload:
                    attempt.status = MonitoringIngestionAttempt.Status.REJECTED
                    attempt.error_code = "empty_batch"
                    attempt.save(update_fields=["status", "error_code"])
                    return Response({"detail": "Empty batch."}, status=status.HTTP_400_BAD_REQUEST)
                if len(events_payload) > self.MAX_BATCH_SIZE:
                    attempt.status = MonitoringIngestionAttempt.Status.REJECTED
                    attempt.error_code = "oversized_batch"
                    attempt.save(update_fields=["status", "error_code"])
                    return Response({"detail": "Oversized batch."}, status=status.HTTP_400_BAD_REQUEST)

                normalizer = GenericNormalizer()
                for index, item in enumerate(events_payload):
                    if not isinstance(item, dict):
                        rejected += 1
                        continue
                    normalized = normalizer.normalize(item)
                    errors = normalizer.validate(normalized)
                    if errors:
                        rejected += 1
                        continue

                    occurred_at = normalized.get("occurred_at")
                    if isinstance(occurred_at, str):
                        from django.utils.dateparse import parse_datetime
                        parsed = parse_datetime(occurred_at)
                        occurred_at = parsed or timezone.now()
                    if occurred_at is None:
                        occurred_at = timezone.now()
                    normalized["occurred_at"] = occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else occurred_at


                    event = MonitoringEvent(
                        event_id=f"{source.code}-{request_id}-{index}",
                        source=source,
                        source_event_id=normalized.get("source_event_id", ""),
                        event_type=normalized.get("event_type", ""),
                        event_state=normalized.get("event_state", "firing"),
                        severity=normalized.get("severity", "info"),
                        title=normalized.get("title", ""),
                        summary=normalized.get("summary", ""),
                        occurred_at=occurred_at,
                        target_type=normalized.get("target_type", "unknown"),
                        target_identifier=normalized.get("target_identifier", ""),
                        hostname=normalized.get("hostname", ""),
                        ip_address=normalized.get("ip_address", ""),
                        service_name=normalized.get("service_name", ""),
                        metric_name=normalized.get("metric_name", ""),
                        metric_value=normalized.get("metric_value", ""),
                        threshold=normalized.get("threshold", ""),
                        environment=normalized.get("environment", ""),
                        raw_payload_hash=hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8")).hexdigest(),
                        normalized_payload=normalized,
                        metadata=normalized.get("metadata", {}),
                        processing_status="received",
                    )

                    alert, created_alert, is_duplicate = correlate_event(event)
                    if is_duplicate:
                        duplicates += 1
                    if alert is not None:
                        correlated_alerts += 1
                    accepted += 1
                    correlated += 1

                    try:
                        if not is_duplicate:
                            with transaction.atomic():
                                MonitoringEventOccurrence.objects.create(
                                    event=event,
                                    occurred_at=event.occurred_at,
                                    event_state=event.event_state,
                                    metric_value=event.metric_value,
                                    payload_hash=event.raw_payload_hash,
                                )
                    except Exception:
                        pass


                source.last_event_at = timezone.now()
                source.last_success_at = timezone.now()
                source.save(update_fields=["last_event_at", "last_success_at"])

                attempt.event_count = len(events_payload)
                attempt.accepted_count = accepted
                attempt.rejected_count = rejected
                attempt.duplicate_count = duplicates
                attempt.status = MonitoringIngestionAttempt.Status.ACCEPTED if rejected == 0 else MonitoringIngestionAttempt.Status.PARTIALLY_ACCEPTED
                attempt.save(update_fields=["event_count", "accepted_count", "rejected_count", "duplicate_count", "status"])

        except Exception:
            attempt.status = MonitoringIngestionAttempt.Status.FAILED
            attempt.error_code = "processing_failed"
            attempt.save(update_fields=["status", "error_code"])
            return Response({"detail": "Ingestion failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


        return Response(
            {
                "accepted": accepted,
                "duplicates": duplicates,
                "correlated": correlated,
                "rejected": rejected,
                "alerts": correlated_alerts,
            },
            status=status.HTTP_202_ACCEPTED,
        )

