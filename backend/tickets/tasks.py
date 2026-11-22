"""SLA escalation and breach tasks."""
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import email_utils as _email_utils
from common.models import BackgroundTaskRun
from common.notifications import SLA_CATEGORY, email_enabled_for, notify_user
from common.outbox import enqueue_email
from tickets.models import SLAEscalation, Ticket, TicketSLA

TASK_NAME = "tickets.tasks.check_sla_escalations"


def _send_notification(ticket, level, title, body):
    """Create an in-app SLA notification.

    Recipient: assignee, falling back to requester. SLAEscalation records
    guard repeated reminder/email dispatch for the same ticket+level;
    notify_user dedupe provides extra idempotency for the in-app row.
    """
    recipient = ticket.assignee if ticket.assignee_id else ticket.requester
    if not recipient or not recipient.pk:
        return
    notify_user(
        recipient,
        SLA_CATEGORY,
        title,
        body,
        entity_type="tickets.SLA",
        object_id=str(ticket.pk),
        dedupe=True,
        post_commit=False,
    )


@shared_task(bind=True, max_retries=2, retry_backoff=120)
def check_sla_escalations(self):
    """Periodic task: check all open tickets against their SLA thresholds.

    Fires 'approach' notifications when the SLA deadline is within the
    escalation window, and 'breach' notifications when the deadline has
    passed. Duplicate notifications are prevented by the SLAEscalation
    unique constraint (get_or_create), so retries cannot double-send.
    Sends in-app notifications + (preference-aware) email notifications.
    """
    run = BackgroundTaskRun.objects.create(
        task_name=TASK_NAME, status="running", success=False,
        payload={"action": "sla_check"})
    try:
        now = timezone.now()
        tickets = Ticket.objects.filter(
            status__in=("new", "open", "in_progress"))

        for ticket in tickets:
            try:
                sla_cfg = TicketSLA.objects.get(
                    priority=ticket.priority, is_active=True)
            except TicketSLA.DoesNotExist:
                continue

            due = ticket.get_sla_due_at()
            if not due:
                continue

            approach_dt = sla_cfg.escalation_deadline(due)
            if now >= approach_dt and now < sla_cfg.breach_deadline(due):
                if not ticket.sla_escalations.filter(level="approach").exists():
                    enqueued = None
                    with transaction.atomic():
                        _esc, created = SLAEscalation.objects.get_or_create(
                            ticket=ticket, level="approach")
                        if created:
                            title = f"SLA approaching ({ticket.priority})"
                            body = (
                                f"Ticket #{ticket.id} is due for "
                                f"resolution by {due:%Y-%m-%d %H:%M}. "
                                "Please prioritize."
                            )
                            recipient = ticket.assignee if ticket.assignee_id else ticket.requester
                            _send_notification(ticket, "approach", title, body)
                            if recipient and getattr(recipient, "email", None) and email_enabled_for(recipient, category=SLA_CATEGORY):
                                enqueued = enqueue_email(
                                    event_type="ticket.email.sla_approaching",
                                    to_email=recipient.email,
                                    subject=title,
                                    body=body,
                                    recipient=recipient,
                                    category=SLA_CATEGORY,
                                    ticket_id=ticket.pk,
                                    dedupe=True,
                                )
                    if enqueued is not None and getattr(settings, "NOTIFICATION_OUTBOX_EAGER", False):
                        from common.outbox import deliver_event_core
                        try:
                            deliver_event_core(enqueued.id)
                        except Exception:
                            pass

            if now >= sla_cfg.breach_deadline(due):
                if not ticket.sla_escalations.filter(level="breach").exists():
                    enqueued = None
                    with transaction.atomic():
                        _esc, created = SLAEscalation.objects.get_or_create(
                            ticket=ticket, level="breach")
                        if created:
                            title = f"SLA breached ({ticket.priority})"
                            body = (
                                f"Ticket #{ticket.id} has exceeded its "
                                f"SLA deadline of {due:%Y-%m-%d %H:%M}. "
                                "Immediate action required."
                            )
                            recipient = ticket.assignee if ticket.assignee_id else ticket.requester
                            _send_notification(ticket, "breach", title, body)
                            if recipient and getattr(recipient, "email", None) and email_enabled_for(recipient, category=SLA_CATEGORY):
                                enqueued = enqueue_email(
                                    event_type="ticket.email.sla_breached",
                                    to_email=recipient.email,
                                    subject=title,
                                    body=body,
                                    recipient=recipient,
                                    category=SLA_CATEGORY,
                                    ticket_id=ticket.pk,
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
        return {"checked": Ticket.objects.filter(
            status__in=("new", "open", "in_progress")).count()}
    except Exception as exc:
        run.status = "failed"
        run.success = False
        run.error_summary = type(exc).__name__
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary",
                                "finished_at"])
        raise self.retry(exc) from exc
