"""Maintenance reminder tasks."""
from datetime import timedelta
from django.utils import timezone

from assets.models import Maintenance, MaintenanceReminder
from common.models import Notification


def _send_notification(maintenance, level, title, body):
    """Create a notification for the assigned technician (or asset creator if unassigned)."""
    recipient = maintenance.assigned_to if maintenance.assigned_to_id else maintenance.created_by
    if not recipient_id:
        return
    Notification.objects.create(
        recipient_id=recipient_id,
        title=title,
        body=body,
        entity_type="assets.Maintenance",
        object_id=str(maintenance.id),
    )


def check_maintenance_reminders():
    """Periodic task: check all active maintenance items for upcoming or overdue reminders.

    Fires 'before' notifications when the scheduled date is within the next 24 hours
    (or a configurable window) and 'overdue' notifications when the scheduled date has
    passed without completion.
    Duplicate notifications are prevented by the MaintenanceReminder unique constraint.
    """
    now = timezone.now()
    # look for maintenance not yet completed/cancelled
    maintenances = Maintenance.objects.filter(
        status__in=("scheduled", "in_progress")
    ).select_related("asset", "assigned_to", "created_by")

    for m in maintenances:
        scheduled = m.scheduled_date
        if not scheduled:
            continue

        # ---- before scheduled notification ----
        # trigger if within 24 hours of the scheduled date and not already reminded today
        window_start = scheduled - timedelta(hours=24)
        window_end = scheduled + timedelta(minutes=5)
        if window_start <= now <= window_end:
            if not m.reminders.filter(level="before").exists():
                _send_notification(m, "before",
                    f"Maintenance due soon ({m.title})",
                    f"Maintenance for asset {m.asset.asset_tag} – {m.title} is scheduled for {scheduled:%Y-%m-%d %H:%M}. "
                    "Please prepare.")
                MaintenanceReminder.objects.get_or_create(maintenance=m, level="before")

        # ---- overdue notification ----
        if now > scheduled and m.status != "completed" and m.status != "cancelled":
            if not m.reminders.filter(level="overdue").exists():
                _send_notification(m, "overdue",
                    f"Maintenance overdue ({m.title})",
                    f"Maintenance for asset {m.asset.asset_tag} – {m.title} was due at {scheduled:%Y-%m-%d %H:%M} and is still open. "
                    "Update the status or schedule a new maintenance.")
                MaintenanceReminder.objects.get_or_create(maintenance=m, level="overdue")