"""Alert correlation logic for monitoring module."""

import hashlib

from django.db import transaction
from django.utils import timezone

from .models import MonitoringAlert, MonitoringAlertHistory


def build_event_fingerprint(event):
    """Build deterministic fingerprint for an event."""
    parts = [
        getattr(getattr(event, "source", None), "code", "") or "",
        getattr(event, "event_type", "") or "",
        getattr(event, "target_type", "") or "",
        getattr(event, "target_identifier", "") or "",
        getattr(event, "metric_name", "") or "",
        getattr(event, "environment", "") or "",
    ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:128]


def build_correlation_key(event):
    """Build correlation key for matching events/alerts."""
    parts = [
        getattr(getattr(event, "source", None), "code", "") or "",
        getattr(event, "target_type", "") or "",
        getattr(event, "target_identifier", "") or "",
        getattr(event, "metric_name", "") or "",
    ]
    return ":".join(parts)


def _next_alert_number():
    # Simple monotonic generator suitable for isolated test environments.
    last = MonitoringAlert.objects.order_by("-id").values_list("alert_number", flat=True).first() or ""
    try:
        num = int(str(last).split("-")[-1])
    except Exception:
        num = MonitoringAlert.objects.count()
    return f"ALT-{num + 1:06d}"


def _ensure_event_persisted(event, fingerprint, correlation_key):
    """Persist event if needed; reuse canonical event when fingerprint already exists."""
    from .models import MonitoringEvent

    update_fields = []
    if not getattr(event, "pk", None):
        existing = MonitoringEvent.objects.filter(fingerprint=fingerprint).first()
        if existing is not None:
            # Reuse canonical event for duplicate/reopen correlation flows.
            event.pk = existing.pk
            for field in [
                "event_id", "source_id", "event_type", "event_state", "severity", "title",
                "summary", "occurred_at", "target_type", "target_identifier", "metric_name",
                "environment", "raw_payload_hash", "processing_status", "correlation_key",
                "fingerprint", "department", "asset_id", "configuration_item_id",
            ]:
                if hasattr(existing, field):
                    setattr(event, field, getattr(existing, field))
            return
        event.fingerprint = fingerprint
        event.correlation_key = correlation_key
        if not getattr(event, "raw_payload_hash", None):
            event.raw_payload_hash = hashlib.sha256(b"").hexdigest()
        event.processing_status = "normalized"
        event.save()
        return

    if getattr(event, "fingerprint", None) != fingerprint:
        # If another canonical row already owns this fingerprint, reuse it.
        existing = MonitoringEvent.objects.filter(fingerprint=fingerprint).exclude(pk=event.pk).first()
        if existing is not None:
            event.pk = existing.pk
            for field in [
                "event_id", "source_id", "event_type", "event_state", "severity", "title",
                "summary", "occurred_at", "target_type", "target_identifier", "metric_name",
                "environment", "raw_payload_hash", "processing_status", "correlation_key",
                "fingerprint", "department", "asset_id", "configuration_item_id",
            ]:
                if hasattr(existing, field):
                    setattr(event, field, getattr(existing, field))
            return
        event.fingerprint = fingerprint
        update_fields.append("fingerprint")
    if getattr(event, "correlation_key", None) != correlation_key:
        event.correlation_key = correlation_key
        update_fields.append("correlation_key")
    if update_fields:
        event.save(update_fields=update_fields)


def correlate_event(event):
    """Correlate an event to an existing or new alert.

    Returns (alert, created, is_duplicate).
    """
    fingerprint = build_event_fingerprint(event)
    correlation_key = build_correlation_key(event)

    with transaction.atomic():
        _ensure_event_persisted(event, fingerprint, correlation_key)

        existing_alert = (
            MonitoringAlert.objects.select_for_update()
            .filter(fingerprint=fingerprint, status__in=["new", "open", "acknowledged"])
            .first()
        )

        if existing_alert:
            event.processing_status = "correlated"
            event.save(update_fields=["processing_status"])
            existing_alert.event_count = (existing_alert.event_count or 0) + 1
            existing_alert.duplicate_event_count = (existing_alert.duplicate_event_count or 0) + 1
            existing_alert.latest_event = event
            existing_alert.last_seen_at = timezone.now()
            existing_alert.save(update_fields=["event_count", "duplicate_event_count", "latest_event", "last_seen_at"])
            MonitoringAlertHistory.objects.create(
                alert=existing_alert,
                event=event,
                event_type=MonitoringAlertHistory.EventType.DUPLICATE_RECEIVED,
                new_status=existing_alert.status,
            )
            return existing_alert, False, True

        recovered_alert = (
            MonitoringAlert.objects.select_for_update()
            .filter(fingerprint=fingerprint, status="recovered")
            .first()
        )

        if recovered_alert:
            previous = recovered_alert.status
            recovered_alert.status = "open"
            recovered_alert.event_count = (recovered_alert.event_count or 0) + 1
            recovered_alert.latest_event = event
            recovered_alert.last_seen_at = timezone.now()
            recovered_alert.recovered_at = None
            recovered_alert.save(update_fields=["status", "event_count", "latest_event", "last_seen_at", "recovered_at"])
            event.processing_status = "correlated"
            event.save(update_fields=["processing_status"])
            MonitoringAlertHistory.objects.create(
                alert=recovered_alert,
                event=event,
                event_type=MonitoringAlertHistory.EventType.REOPENED,
                previous_status=previous,
                new_status="open",
            )
            return recovered_alert, False, False

        # Recovery event for unknown alert: record as correlated event without creating alert.
        if getattr(event, "event_state", None) in {"recovered", "Recovered"}:
            event.processing_status = "correlated"
            event.save(update_fields=["processing_status"])
            return None, False, False

        alert = MonitoringAlert.objects.create(
            alert_number=_next_alert_number(),
            source=event.source,
            fingerprint=fingerprint,
            correlation_key=correlation_key,
            title=event.title,
            summary=getattr(event, "summary", "") or "",
            severity=getattr(event, "severity", MonitoringAlert.AlertSeverity.INFO),
            status="open",
            first_event=event,
            latest_event=event,
            event_count=1,
            department=getattr(event, "department", "") or "",
            asset=getattr(event, "asset", None),
            configuration_item=getattr(event, "configuration_item", None),
        )
        event.processing_status = "alerted"
        event.save(update_fields=["processing_status"])
        MonitoringAlertHistory.objects.create(
            alert=alert,
            event=event,
            event_type=MonitoringAlertHistory.EventType.CREATED,
            new_status=alert.status,
        )
        return alert, True, False
