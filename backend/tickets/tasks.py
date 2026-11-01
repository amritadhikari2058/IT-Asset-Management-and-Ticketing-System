"""SLA escalation and breach tasks."""
from datetime import timedelta
from django.utils import timezone

from tickets.models import Ticket, TicketSLA
from common.models import Notification


def _send_notification(ticket, level, title, body):
    """Create a notification for the ticket assignee (or requester if unassigned)."""
    recipient = ticket.assignee if ticket.assignee_id else ticket.requester
    if not recipient_id:
        return
    Notification.objects.create(
        recipient_id=recipient_id,
        title=title,
        body=body,
        entity_type="tickets.SLA",
        object_id=str(ticket.id),
    )


def check_sla_escalations():
    """Periodic task: check all open tickets against their SLA thresholds.

    Fires 'approach' notifications when the SLA deadline is within the
    escalation window, and 'breach' notifications when the deadline has passed.
    Duplicate notifications are prevented by the SLAEscalation unique constraint.
    """
    now = timezone.now()
    tickets = Ticket.objects.filter(
        status__in=("new", "open", "in_progress")
    )

    for ticket in tickets:
        # Look up the SLA configuration for this ticket's priority
        try:
            sla_cfg = TicketSLA.objects.get(priority=ticket.priority, is_active=True)
        except TicketSLA.DoesNotExist:
            continue

        due = ticket.sla_due_at
        if not due:
            continue

        # ---- approach notification ----
        approach_dt = sla_cfg.escalation_deadline()
        if now >= approach_dt and now < sla_cfg.breach_deadline():
            # send approach if not already recorded
            if not ticket.sla_escalations.filter(level="approach").exists():
                _send_notification(ticket, "approach",
                    f"SLA approaching ({ticket.priority})",
                    f"Ticket #{ticket.id} is due for resolution by {due:%Y-%m-%d %H:%M}. "
                    "Please prioritize.")
                SLAEscalation.objects.get_or_create(ticket=ticket, level="approach")

        # ---- breach notification ----
        if now >= sla_cfg.breach_deadline():
            if not ticket.sla_escalations.filter(level="breach").exists():
                _send_notification(ticket, "breach",
                    f"SLA breached ({ticket.priority})",
                    f"Ticket #{ticket.id} has exceeded its SLA deadline of {due:%Y-%m-%d %H:%M}. "
                    "Immediate action required.")
                SLAEscalation.objects.get_or_create(ticket=ticket, level="breach")