"""Alert correlation logic for monitoring module."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import MonitoringAlert, MonitoringEvent, MonitoringAlertHistory


def build_event_fingerprint(event):
    """Build deterministic fingerprint for an event."""
    parts = [
        event.source.code,
        event.event_type,
        event.target_type,
        event.target_identifier,
        event.metric_name,
        event.environment,
    ]
    import hashlib
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:128]


def build_correlation_key(event):
    """Build correlation key for matching events/alerts."""
    parts = [
        event.source.code,
        event.target_type,
        event.target_identifier,
        event.metric_name,
    ]
    return ":".join(parts)


def correlate_event(event):
    """Correlate an event to an existing or new alert.

    Returns (alert, created, is_duplicate).
    Uses transaction.atomic and select_for_update for concurrency safety.
    """
    fingerprint = build_event_fingerprint(event)
    correlation_key = build_correlation_key(event)

    event.fingerprint = fingerprint
    event.correlation_key = correlation_key
    event.processing_status = "normalized"

    with transaction.atomic():
        # Use select_for_update for concurrency safety
        existing_alert = (
            MonitoringAlert.objects.select_for_update()
            .filter(fingerprint=fingerprint)
            .filter(status__in=["new", "open", "acknowledged"])
            .first()
        )

        if existing_alert:
            # Duplicate event - update existing alert
            event.processing_status = "correlated"
            event.save(update_fields=["fingerprint", "correlation_key", "processing_status"])

            existing_alert.event_count = (existing_alert.event_count or 0) + 1
            existing_alert.duplicate_event_count = (existing_alert.duplicate_event_count or 0) + 1
            existing_alert.latest_event = event
            existing_alert.last_seen_at = timezone.now()
            existing_alert.save(update_fields=["event_count", "duplicate_event_count", "latest_event", "last_seen_at"])

            # Record history
            MonitoringAlertHistory.objects.create(
                alert=existing_alert,
                event=event,
                event_type=MonitoringAlertHistory.EventType.DUPLICATE_RECEIVED,
                new_status=existing_alert.status,
            )

            return existing_alert, False, True

        # Check for recovered alert with same fingerprint (reopen)
        recovered_alert = (
            MonitoringAlert.objects.select_for_update()
            .filter(fingerprint=fingerprint)
            .filter(status="recovered")
            .first()
        )

        if recovered_alert:
            # Reopen recovered alert
            recovered_alert.status = "open"
            recovered_alert.event_count = (recovered_alert.event_count or 0) + 1
            recovered_alert.event_count = (recovered_alert.event_count or 0) + 1
            recovered_alert.latest_event = event
            recovered_alert.last_seen_at = timezone.now()
            recovered_alert.recovered_at = None
            recovered_alert.save(update_fields=["status", "event_count", "latest_event", "last_seen_at", "recovered_at"])

            event.processing_status = "correlated"
            event.save(update_fields=["fingerprint", "correlation_key", "processing_status"])

            MonitoringAlertHistory.objects.create(
                alert=recovered_alert,
                event=event,
                event_type=MonitoringAlertHistory.EventType.REOPENED,
                new_status="open",
            )

            return recovered_alert, False, False

        # Create new alert
        alert = MonitoringAlert(
            source=event.source,
            fingerprint=fingerprint,
            correlation_key=correlation_key,
            title=event.title,
            summary=event.summary,
            severity=event.severity,
            status="open",
            first_event=event,
            latest_event=event,
            event_count=1,
            department=event.department,
            asset=event.asset,
            configuration_item=event.configuration_item,
            service_catalogue_item=event.service_catalogue_item,
        )
        alert.save()

        event.processing_status = "alerted"
        event.save(update_fields=["fingerprint", "correlation_key", "processing_status"])

        MonitoringAlertHistory.objects.create(
            alert=alert,
            event=event,
            event_type=MonitoringAlertHistory.EventType.CREATED,
            new_status=alert.status,
        )

        return alert, True, False
