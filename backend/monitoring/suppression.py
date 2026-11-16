"""Suppression logic for monitoring module."""

from django.db import transaction
from django.utils import timezone

from .models import MonitoringAlert, AlertSuppressionWindow


def check_suppression_window(alert, source=None, asset=None, configuration_item=None):
    """Check if an alert should be suppressed based on active suppression windows.

    Returns (should_suppress, reason).
    """
    now = timezone.now()

    windows = AlertSuppressionWindow.objects.filter(
        status="active",
        starts_at__lte=now,
        ends_at__gte=now,
    )

    for window in windows:
        matches = False

        if window.scope_type == "global":
            matches = True
        elif window.scope_type == "source" and window.source == source:
            matches = True
        elif window.scope_type == "rule" and window.alert_rule:
            matches = True
        elif window.scope_type == "asset" and window.asset == asset:
            matches = True
        elif window.scope_type == "configuration_item" and window.configuration_item == configuration_item:
            matches = True

        if matches:
            return True, f"Suppressed by window: {window.name}"

    return False, ""


def record_suppression_count(alert):
    """Record suppression count on alert."""
    alert.suppression_count = (alert.suppression_count or 0) + 1
    alert.save(update_fields=["suppression_count"])


def is_maintenance_aware(asset):
    """Check if an asset is under active maintenance.

    Read-only check - does not modify asset or change models.
    """
    if not asset:
        return False

    # Check if asset has active maintenance
    try:
        return asset.is_under_maintenance()
    except AttributeError:
        return False
