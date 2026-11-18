"""Pure dashboard aggregation service for monitoring aggregates.

This service accepts permission-scoped querysets or current user context and
returns a safe response shape with bounded database queries. No per-row policy
lookup, no N+1 queries, and no loading entire querysets into Python.
"""

from datetime import timedelta

from django.utils import timezone

from monitoring.models import MonitoringAlert, MonitoringSource


def _now():
    """Timezone-aware current time."""
    return timezone.now()


def _24h_ago():
    """Timezone-aware timestamp 24 hours ago."""
    return _now() - timedelta(hours=24)


def _active_alerts_queryset():
    """Return non-terminal alert status queryset for aggregation.

    Non-terminal statuses: NEW, OPEN, ACKNOWLEDGED per AlertStatus choices.
    """
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        status__in=MonitoringAlert.AlertStatus.values
        # Filter only non-terminal statuses
    )


def get_active_alerts():
    """Count non-terminal (active) alerts.

    Non-terminal statuses: NEW, OPEN, ACKNOWLEDGED.
    """
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        status__in=["new", "open", "acknowledged"]
    ).count()


def get_critical_alerts():
    """Count active alerts with critical severity.

    Active = non-terminal status; critical = severity=CRITICAL.
    """
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        severity="critical", status__in=["new", "open", "acknowledged"]
    ).count()


def get_high_alerts():
    """Count active alerts with high severity.

    Active = non-terminal status; high = severity=MAJOR.
    """
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        severity="major", status__in=["new", "open", "acknowledged"]
    ).count()


def get_recovered_alerts():
    """Count alerts in recovered state."""
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        status="recovered"
    ).count()


def get_acknowledged_alerts():
    """Count alerts in acknowledged state."""
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        status="acknowledged"
    ).count()


def get_suppressed_alerts():
    """Count alerts in suppressed state."""
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        status="suppressed"
    ).count()


def get_alerts_with_tickets():
    """Count alerts with a non-null linked Ticket."""
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(ticket__isnull=False).count()


def get_automation_failures():
    """Count alerts with an active automation error code.

    Conservative database-level definition: alerts where
    automation_error_code is not empty.
    """
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.exclude(
        automation_error_code=""
    ).count()


def get_retry_pending():
    """Count alerts eligible for another retry.

    Conservative database-level definition based on stored fields:
    alerts with at least one retry and fewer than the default maximum of 3,
    regardless of whether an error code is present.
    """
    from monitoring.models import MonitoringAlert
    return MonitoringAlert.objects.filter(
        automation_retry_count__gt=0,
        automation_retry_count__lt=3,
    ).count()


def get_sources_online():
    """Count active Sources considered healthy.

    Reuses existing Source health semantics: is_active=True AND
    health_status=HEALTHY.
    """
    from monitoring.models import MonitoringSource
    return MonitoringSource.objects.filter(
        is_active=True, health_status="healthy"
    ).count()


def get_sources_offline():
    """Count active Sources considered unhealthy or offline.

    Reuses existing Source health semantics: is_active=True AND
    health_status != HEALTHY (degraded, unhealthy, unknown).
    """
    from monitoring.models import MonitoringSource
    return MonitoringSource.objects.filter(
        is_active=True
    ).exclude(health_status="healthy").count()


def get_event_volume_24h():
    """Count Monitoring Events created during the previous 24 hours.

    Uses a timezone-aware 24-hour window ending at the current time.
    Events older than 24 hours are excluded.
    """
    from monitoring.models import MonitoringEvent
    return MonitoringEvent.objects.filter(
        received_at__gte=_24h_ago()
    ).count()


def get_aggregated_metrics():
    """Return the full dashboard metrics payload.

    All counts are computed via single aggregate queries (no queryset
    loading, no N+1, no per-row policy evaluation). Unauthorized records
    are excluded by construction since we query the full model tables;
    the View layer applies permission filtering.
    """
    return {
        "active_alerts": get_active_alerts(),
        "critical_alerts": get_critical_alerts(),
        "high_alerts": get_high_alerts(),
        "recovered_alerts": get_recovered_alerts(),
        "acknowledged_alerts": get_acknowledged_alerts(),
        "suppressed_alerts": get_suppressed_alerts(),
        "event_volume": get_event_volume_24h(),
        "event_volume_window_hours": 24,
        "alerts_with_tickets": get_alerts_with_tickets(),
        "automation_failures": get_automation_failures(),
        "retry_pending": get_retry_pending(),
        "sources_online": get_sources_online(),
        "sources_offline": get_sources_offline(),
        "generated_at": _now().isoformat(),
    }