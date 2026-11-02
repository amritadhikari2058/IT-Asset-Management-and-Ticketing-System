"""SLA escalation and breach tasks."""
from celery import shared_task
from django.utils import timezone

from accounts import email_utils as _email_utils
from common.models import BackgroundTaskRun, Notification
from tickets.models import Ticket, TicketSLA, SLAEscalation

TASK_NAME = "tickets.tasks.check_sla_escalations"


def _send_notification(ticket, level, title, body):
    """Create an in-app notification for the ticket assignee (or requester
    if unassigned). The SLA escalation record guards duplicate sends.
    """
    recipient = ticket.assignee if ticket.assignee_id else ticket.requester
    if not recipient or not recipient.pk:
        return
    Notification.objects.create(
        recipient_id=recipient.pk,
        title=title,
        body=body,
        entity_type="tickets.SLA",
        object_id=str(ticket.id),
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

            due = ticket.sla_due_at
            if not due:
                continue

            approach_dt = sla_cfg.escalation_deadline(ticket.sla_due_at)
            if now >= approach_dt and now < sla_cfg.breach_deadline(ticket.sla_due_at):
                if not ticket.sla_escalations.filter(level="approach").exists():
                    _send_notification(ticket, "approach",
                                       f"SLA approaching ({ticket.priority})",
                                       f"Ticket #{ticket.id} is due for "
                                       f"resolution by {due:%Y-%m-%d %H:%M}. "
                                       "Please prioritize.")
                    SLAEscalation.objects.get_or_create(
                        ticket=ticket, level="approach")
                    _email_utils.send_sla_approaching(ticket)

            if now >= sla_cfg.breach_deadline(ticket.sla_due_at):
                if not ticket.sla_escalations.filter(level="breach").exists():
                    _send_notification(ticket, "breach",
                                       f"SLA breached ({ticket.priority})",
                                       f"Ticket #{ticket.id} has exceeded its "
                                       f"SLA deadline of {due:%Y-%m-%d %H:%M}. "
                                       "Immediate action required.")
                    SLAEscalation.objects.get_or_create(
                        ticket=ticket, level="breach")
                    _email_utils.send_sla_breached(ticket)

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
