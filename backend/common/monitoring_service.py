"""Location A operational alerting service.

Creates and refreshes ``common.OperationalAlert`` records, deduplicated by
``dedup_key`` so a persistent failure does not flood notifications. Also
provides sanitized error-event recording (``OperationalErrorEvent``) and
alert/incident lifecycle helpers. Secrets (passwords, tokens, authorization
headers, keys) are never stored in plaintext.
"""

import hashlib
import re
from django.utils import timezone

from common.models import (
    OperationalAlert, OperationalErrorEvent, OperationalIncident,
)

_SECRET_KEYS = ("password", "passwd", "pwd", "secret", "token",
                "authorization", "api_key", "apikey", "private_key",
                "client_secret", "access_token", "refresh_secret")


def _is_secret_key(key):
    k = key.lower()
    return k in _SECRET_KEYS or any(s in k for s in _SECRET_KEYS)


def sanitize_details(details):
    """Return a copy of ``details`` with secret-like values redacted.

    Redaction is recursive: nested dicts and lists are walked so secrets
    buried in arbitrary JSON structure are never stored.
    """
    if isinstance(details, dict):
        out = {}
        for key, value in details.items():
            if _is_secret_key(key):
                out[key] = "[REDACTED]"
            else:
                out[key] = sanitize_details(value)
        return out
    if isinstance(details, list):
        return [sanitize_details(item) for item in details]
    return details


_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|authorization|api_key|apikey|"
    r"private_key|client_secret|access_token|refresh_secret)\s*[:=]\s*\S+")


def sanitize_message(message):
    """Return ``message`` with embedded secret assignments stripped."""
    if not message:
        return message
    return _SECRET_PATTERN.sub(lambda m: m.group(1) + "=[REDACTED]", message)


def _dedup_key(*parts):
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:128]


def create_or_update_alert(*, component, severity, title, description,
                           details=None, dedup_key=None):
    """Create or refresh an operational alert.

    An existing alert with the same ``dedup_key`` is refreshed rather than
    duplicated, so recurring failures are tracked as a single alert.
    Returns ``(alert, created)``.
    """
    details = sanitize_details(details or {})
    dedup_key = dedup_key or _dedup_key(component, title)
    defaults = {
        "component": component,
        "severity": severity,
        "title": title[:200],
        "description": description,
        "details": details,
        "last_occurred": timezone.now(),
    }
    alert, created = OperationalAlert.objects.update_or_create(
        dedup_key=dedup_key, defaults=defaults)
    if created:
        alert.occurrence_count = 1
    else:
        alert.occurrence_count = (alert.occurrence_count or 0) + 1
        if alert.status in ("resolved", "closed"):
            alert.status = "open"
            alert.resolved = False
            alert.resolved_at = None
            alert.resolved_by = None
    alert.save(update_fields=[
        "component", "severity", "title", "description", "details",
        "last_occurred", "occurrence_count", "status", "resolved",
        "resolved_at", "resolved_by"])
    return alert, created


def record_error(*, component, title, message="", endpoint="",
                 status_code=None, correlation_id="", severity="medium",
                 details=None):
    """Record a sanitized operational error event.

    Returns the created (or dedup-updated) ``OperationalErrorEvent``.
    """
    details = sanitize_details(details or {})
    message = sanitize_message(message)
    dedup_key = _dedup_key(component, title, endpoint, status_code)
    defaults = {
        "component": component,
        "severity": severity,
        "title": title[:200],
        "message": message,
        "correlation_id": str(correlation_id or "")[:64],
        "endpoint": endpoint[:200],
        "status_code": status_code,
        "details": details,
    }
    event, created = OperationalErrorEvent.objects.update_or_create(
        dedup_key=dedup_key, defaults=defaults)
    if not created:
        event.occurrence_count = (event.occurrence_count or 0) + 1
        event.save(update_fields=["occurrence_count", "details", "message"])
    return event


def resolve_error(event_pk, user):
    """Mark an error event resolved. Returns ``(ok, event)``."""
    try:
        event = OperationalErrorEvent.objects.get(pk=event_pk)
    except OperationalErrorEvent.DoesNotExist:
        return False, None
    event.resolved = True
    event.resolved_by = user
    event.resolved_at = timezone.now()
    event.save(update_fields=["resolved", "resolved_by", "resolved_at"])
    return True, event


def acknowledge_alert(alert_pk, user):
    """Acknowledge an alert. Returns ``(ok, alert)``."""
    try:
        alert = OperationalAlert.objects.get(pk=alert_pk)
    except OperationalAlert.DoesNotExist:
        return False, None
    alert.acknowledged = True
    alert.acknowledged_by = user
    alert.acknowledged_at = timezone.now()
    alert.status = "acknowledged"
    alert.save(update_fields=["acknowledged", "acknowledged_by",
                              "acknowledged_at", "status"])
    return True, alert


def resolve_alert(alert_pk, user):
    """Resolve an alert. Returns ``(ok, alert)``."""
    try:
        alert = OperationalAlert.objects.get(pk=alert_pk)
    except OperationalAlert.DoesNotExist:
        return False, None
    alert.resolved = True
    alert.resolved_by = user
    alert.resolved_at = timezone.now()
    alert.status = "resolved"
    alert.save(update_fields=["resolved", "resolved_by", "resolved_at",
                              "status"])
    return True, alert


def close_alert(alert_pk, user):
    """Close an alert. Returns ``(ok, alert)``.

    Authorization (system admin only) is enforced by the calling view.
    """
    try:
        alert = OperationalAlert.objects.get(pk=alert_pk)
    except OperationalAlert.DoesNotExist:
        return False, None
    alert.status = "closed"
    alert.resolved = True
    alert.resolved_at = timezone.now()
    alert.save(update_fields=["status", "resolved", "resolved_at"])
    return True, alert


def create_incident(*, title, description, severity, affected_component="",
                    assigned_to=None, related_ticket=None,
                    related_alerts=None, internal_notes=""):
    """Create an operational incident. Returns the incident."""
    if assigned_to is not None and not hasattr(assigned_to, "pk"):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            assigned_to = User.objects.get(pk=assigned_to)
        except User.DoesNotExist:  # noqa: BLE001
            assigned_to = None
    incident = OperationalIncident.objects.create(
        title=title[:200], description=description, severity=severity,
        affected_component=affected_component, assigned_to=assigned_to,
        related_ticket=related_ticket, related_alerts=related_alerts or [],
        internal_notes=internal_notes)
    return incident


def update_incident(incident_pk, user, **fields):
    """Update fields on an incident. Returns ``(ok, incident)``.

    ``user`` is the actor (authorization is enforced by the calling view).
    """
    try:
        incident = OperationalIncident.objects.get(pk=incident_pk)
    except OperationalIncident.DoesNotExist:
        return False, "Incident not found."
    allowed = {"title", "description", "severity", "status",
               "affected_component", "assigned_to", "related_ticket",
               "related_alerts", "internal_notes"}
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "assigned_to" and value is not None \
                and not hasattr(value, "pk"):
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                value = User.objects.get(pk=value)
            except User.DoesNotExist:  # noqa: BLE001
                value = None
        setattr(incident, key, value)
    incident.save()
    return True, incident
