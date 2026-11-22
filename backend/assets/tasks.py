"""Maintenance reminder tasks."""
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import email_utils as _email_utils
from assets.models import Maintenance, MaintenanceReminder
from common.models import BackgroundTaskRun
from common.notifications import MAINTENANCE_CATEGORY, email_enabled_for, notify_user
from common.outbox import enqueue_email

TASK_NAME = "assets.tasks.check_maintenance_reminders"


def _send_notification(maintenance, level, title, body):
    """Create an in-app maintenance reminder notification.

    Recipient: assigned technician, falling back to creator. The
    MaintenanceReminder unique constraint guards repeated reminder/email
    dispatch for the same maintenance+level; notify_user dedup provides
    extra idempotency for the in-app notification row itself.
    """
    recipient = maintenance.assigned_to if maintenance.assigned_to_id \
        else maintenance.created_by
    if not recipient or not recipient.pk:
        return
    notify_user(
        recipient,
        MAINTENANCE_CATEGORY,
        title,
        body,
        entity_type="assets.Maintenance",
        object_id=str(maintenance.pk),
        dedupe=True,
        post_commit=False,
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
                    enqueued = None
                    with transaction.atomic():
                        _rem, created = MaintenanceReminder.objects.get_or_create(
                            maintenance=m, level="before")
                        if created:
                            title = f"Maintenance due soon ({m.title})"
                            body = (
                                f"Maintenance for asset "
                                f"{m.asset.asset_tag} - {m.title} is "
                                f"scheduled for {scheduled:%Y-%m-%d %H:%M}. "
                                "Please prepare."
                            )
                            recipient = m.assigned_to if m.assigned_to_id else m.created_by
                            _send_notification(m, "before", title, body)
                            if recipient and getattr(recipient, "email", None) and email_enabled_for(recipient, category=MAINTENANCE_CATEGORY):
                                enqueued = enqueue_email(
                                    event_type="maintenance.email.reminder",
                                    to_email=recipient.email,
                                    subject=title,
                                    body=body,
                                    recipient=recipient,
                                    category=MAINTENANCE_CATEGORY,
                                    ticket_id=None,
                                    dedupe=True,
                                )
                    if enqueued is not None and getattr(settings, "NOTIFICATION_OUTBOX_EAGER", False):
                        from common.outbox import deliver_event_core
                        try:
                            deliver_event_core(enqueued.id)
                        except Exception:
                            pass

            if now > scheduled and m.status != "completed" \
                    and m.status != "cancelled":
                if not m.reminders.filter(level="overdue").exists():
                    enqueued = None
                    with transaction.atomic():
                        _rem, created = MaintenanceReminder.objects.get_or_create(
                            maintenance=m, level="overdue")
                        if created:
                            title = f"Maintenance overdue ({m.title})"
                            body = (
                                f"Maintenance for asset "
                                f"{m.asset.asset_tag} - {m.title} was due "
                                f"at {scheduled:%Y-%m-%d %H:%M} and is "
                                "still open. Update the status or "
                                "schedule a new maintenance."
                            )
                            recipient = m.assigned_to if m.assigned_to_id else m.created_by
                            _send_notification(m, "overdue", title, body)
                            if recipient and getattr(recipient, "email", None) and email_enabled_for(recipient, category=MAINTENANCE_CATEGORY):
                                enqueued = enqueue_email(
                                    event_type="maintenance.email.overdue",
                                    to_email=recipient.email,
                                    subject=title,
                                    body=body,
                                    recipient=recipient,
                                    category=MAINTENANCE_CATEGORY,
                                    ticket_id=None,
                                    dedupe=True,
                                )
                    if enqueued is not None and getattr(settings, "NOTIFICATION_OUTBOX_EAGER", False):
                        from common.outbox import deliver_event_core
                        try:
                            deliver_event_core(enqueued.id)
                        except Exception:
                            pass

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
