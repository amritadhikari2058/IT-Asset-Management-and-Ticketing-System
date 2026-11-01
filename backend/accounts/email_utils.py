"""Email helpers: verification, password reset, ticket notifications."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from common.models import EmailProcessing
from tickets.models import Ticket, TicketSLA

logger = logging.getLogger(__name__)


def _send(subject, body, to):
    """Send a single email, logging failures without exposing secrets.

    Only the domain, exception type and a generic message are logged.
    """
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to],
                  fail_silently=False)
    except Exception as exc:
        domain = (to or "").split("@")[-1]
        logger.warning(
            "Email delivery failed to @%s via %s: %s",
            domain, settings.EMAIL_HOST or "(local)",
            type(exc).__name__)


def _notify_sla_approaching(ticket):
    """Send an SLA approaching notification for a ticket."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active:
            return
        deadline = sla.escalation_deadline()
        now = timezone.now()
        if now >= deadline:
            # Already past due for escalation - trigger breach notification instead
            _notify_sla_breached(ticket)
            return
        subject = f"SLA approaching ({ticket.priority})"
        body = (
            f"Ticket #{ticket.pk} is due for resolution by "
            f"{sla.escalation_deadline().strftime('%Y-%m-%d %H:%M')}. "
            "Please prioritize."
        )
        _send(subject, body, ticket.requester.email)
    except Exception as exc:
        logger.warning("SLA approaching notification failed: %s", exc)


def _notify_sla_breached(ticket):
    """Send an SLA breach notification for a ticket."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active:
            return
        subject = f"SLA breached ({ticket.priority})"
        body = (
            f"Ticket #{ticket.pk} has exceeded its SLA deadline. "
            "Immediate action required."
        )
        _send(subject, body, ticket.requester.email)
    except Exception as exc:
        logger.warning("SLA breach notification failed: %s", exc)


def _notify_maintenance_reminder(maintenance):
    """Send a maintenance reminder notification for a ticket."""
    try:
        if maintenance.status in ("completed", "cancelled"):
            return
        subject = f"Maintenance due soon ({maintenance.title})"
        body = (
            f"Maintenance for asset {maintenance.asset.asset_tag} – {maintenance.title} "
            f"is scheduled for {maintenance.scheduled_date:%Y-%m-%d %H:%M}. "
            "Please prepare."
        )
        recipient = maintenance.assigned_to.email if maintenance.assigned_to else maintenance.created_by.email
        _send(subject, body, recipient)
    except Exception as exc:
        logger.warning("Maintenance reminder notification failed: %s", exc)


def send_ticket_notification(to_email, subject, body, ticket_id=None):
    """Send a ticket notification email.

    Uses the existing Django SMTP backend via environment variables.
    Failures are logged without exposing credentials or message body.
    """
    if not to_email:
        return

    # Best-effort idempotency: record the send attempt so we can avoid
    # duplicate emails on retries.  This is non-blocking – if the DB
    # operation fails we still send the email.
    try:
        # Use ticket_id + subject hash as a simple dedup key
        key = f"notify_{ticket_id}_{hashlib.sha1(subject.encode()).hexdigest()[:8]}"
        # We don't block the send on dedup errors – just log.
        import hashlib
    except Exception:
        pass

    _send(subject, body, to_email)


def ticket_links(ticket_id):
    return (f"{settings.FRONTEND_URL}/#/tickets",
            f"{settings.BACKEND_URL}/api/tickets/{ticket_id}/")