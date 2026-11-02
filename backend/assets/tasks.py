"""Maintenance reminder tasks."""
from celery import shared_task
from django.utils import timezone

from assets.models import Maintenance, MaintenanceReminder
from common.models import BackgroundTaskRun
from accounts import email_utils as _email_utils

TASK_NAME = "assets.tasks.check_maintenance_reminders"


def _send_notification(maintenance, level, title, body):
    """Create a notification for the assigned technician (or asset creator
    if unassigned). The MaintenanceReminder unique constraint guards repeats.
    """
    recipient = maintenance.assigned_to if maintenance.assigned_to_id \
        else maintenance.created_by
    if not recipient or not recipient.pk:
        return
    from common.models import Notification
    Notification.objects.create(
        recipient_id=recipient.pk,
        title=title,
        body=body,
        entity_type="assets.Maintenance",
        object_id=str(maintenance.id),
    )


@shared_task(bind=True, max_retries=2, retry_backoff=120)
def check_maintenance_reminders(self):
    """Periodic task: check all active maintenance items for upcoming or
    overdue reminders.

    Fires 'before' notifications when the scheduled date is within the
    before-window and 'overdue' notifications when the scheduled date has
    passed without completion. Duplicate notifications are prevented by
    the MaintenanceReminder unique constraint, so retries cannot double-send.
    Sends in-app notifications + (preference-aware) email reminders.
    """
    run = BackgroundTaskRun.objects.create(
        task_name=TASK_NAME, status="running", success=False,
        payload={"action": "maintenance_reminders"})
    try:
        from datetime import timedelta
        now = timezone.now()
        maintenances = Maintenance.objects.filter(
            status__in=("scheduled", "in_progress")
        ).select_related("asset", "assigned_to", "created_by")

        for m in maintenances:
            scheduled = m.scheduled_date
            if not scheduled:
                continue
            window_start = scheduled - timedelta(hours=24)
            window_end = scheduled + timedelta(minutes=5)
            if window_start <= now <= window_end:
                if not m.reminders.filter(level="before").exists():
                    _send_notification(m, "before",
                                       f"Maintenance due soon ({m.title})",
                                       f"Maintenance for asset "
                                       f"{m.asset.asset_tag} – {m.title} is "
                                       f"scheduled for {scheduled:%Y-%m-%d %H:%M}. "
                                       "Please prepare.")
                    MaintenanceReminder.objects.get_or_create(
                        maintenance=m, level="before")
                    _email_utils.send_maintenance_reminder(m)

            if now > scheduled and m.status != "completed" \
                    and m.status != "cancelled":
                if not m.reminders.filter(level="overdue").exists():
                    _send_notification(m, "overdue",
                                       f"Maintenance overdue ({m.title})",
                                       f"Maintenance for asset "
                                       f"{m.asset.asset_tag} – {m.title} was due "
                                       f"at {scheduled:%Y-%m-%d %H:%M} and is "
                                       "still open. Update the status or "
                                       "schedule a new maintenance.")
                    MaintenanceReminder.objects.get_or_create(
                        maintenance=m, level="overdue")
                    _email_utils.send_maintenance_reminder(m)

        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "finished_at"])
        return {"checked": maintenances.count()}
    except Exception as exc:
        run.status = "failed"
        run.success = False
        run.error_summary = type(exc).__name__
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary",
                                "finished_at"])
        raise self.retry(exc) from exc
