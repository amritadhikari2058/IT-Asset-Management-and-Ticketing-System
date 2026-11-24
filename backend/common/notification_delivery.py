"""Outbound notification delivery helpers.

This module owns email/in-app notification orchestration for domain events
(tickets, SLA, maintenance, knowledge base). Preference policy lives in
``common.notifications``; low-level SMTP sending lives in ``common.email``.
"""
import logging

from django.conf import settings
from django.utils import timezone

from common import email as _email
from common.notifications import (
    KB_REVIEW_CATEGORY, MAINTENANCE_CATEGORY, SLA_CATEGORY,
    email_enabled_for,
)
from tickets.models import TicketSLA

logger = logging.getLogger(__name__)


def ticket_links(ticket_id):
    return (f"{settings.FRONTEND_URL}/#/tickets",
            f"{settings.BACKEND_URL}/api/tickets/{ticket_id}/")


def send_ticket_notification(to_email, subject, body, ticket_id=None, user=None,
                             category=None):
    """Send a ticket notification email (deduped, best-effort).

    The outbound decision is centralized in ``common.notifications`` so the
    global + category preference switches are applied exactly once per send.
    """
    if not to_email:
        return False
    if user is not None and not email_enabled_for(user, category=category):
        return False
    key = _email._dedup_key(ticket_id, subject, to_email)
    cache = _email._cache()
    try:
        if cache.get(key):
            logger.info("Duplicate ticket email suppressed: %s", subject)
            return False
    except Exception:
        pass  # cache unavailable -> fail open and send anyway
    ok = _email.send_email(subject, body, to_email)
    if ok:
        try:
            cache.set(key, True, int(getattr(
                settings, "EMAIL_DEDUP_TTL_SECONDS", 3600)))
        except Exception:
            pass
    return ok


def send_kb_notification(to_email, subject, body, article=None, user=None):
    """Send a Knowledge Base review/publication email (deduped, best-effort)."""
    if not to_email:
        return False
    if user is not None and not email_enabled_for(user, category=KB_REVIEW_CATEGORY):
        return False
    article_id = article.pk if article is not None else None
    key = _email._dedup_key(article_id, subject, to_email)
    cache = _email._cache()
    try:
        if cache.get(key):
            logger.info("Duplicate KB email suppressed: %s", subject)
            return False
    except Exception:
        pass  # cache unavailable -> fail open and send anyway
    ok = _email.send_email(subject, body, to_email)
    if ok:
        try:
            cache.set(key, True, int(getattr(
                settings, "EMAIL_DEDUP_TTL_SECONDS", 3600)))
        except Exception:
            pass
    return ok


def _notify_user(recipient, actor, title, body, ticket):
    """Create an in-app notification; never notify the actor of their own action.

    Delegates to ``common.notifications.notify_user`` for recipient validation,
    sanitization, dedupe, and savepoint-safe creation.
    """
    from common.notifications import notify_user as _central_notify_user

    return _central_notify_user(
        recipient,
        category="ticket_event",
        title=title,
        message=body,
        entity_type="tickets.Ticket",
        object_id=str(getattr(ticket, "pk", "") or ""),
        actor=actor,
        dedupe=True,
        post_commit=True,
    )


def send_sla_approaching(ticket):
    """Send the SLA approaching notification email for a ticket."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active:
            return False
        deadline = sla.escalation_deadline(ticket.sla_due_at)
        if timezone.now() >= deadline:
            send_sla_breached(ticket)
            return False
        subject = f"SLA approaching ({ticket.priority})"
        body = (
            f"Ticket #{ticket.pk} is due for resolution by "
            f"{deadline:%Y-%m-%d %H:%M}. Please prioritize."
        )
        recipient = ticket.assignee if ticket.assignee_id else ticket.requester
        if recipient is None or not getattr(recipient, "email", None):
            return False
        if not email_enabled_for(recipient, category=SLA_CATEGORY):
            return False
        return send_ticket_notification(
            recipient.email, subject, body, ticket_id=ticket.pk)
    except Exception as exc:
        logger.warning("SLA approaching notification failed: %s",
                       type(exc).__name__)
        return False


def send_sla_breached(ticket):
    """Send the SLA breach notification email for a ticket."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active:
            return False
        subject = f"SLA breached ({ticket.priority})"
        body = (
            f"Ticket #{ticket.pk} has exceeded its SLA deadline of "
            f"{ticket.sla_due_at:%Y-%m-%d %H:%M}. "
            "Immediate action required."
        )
        recipient = ticket.assignee if ticket.assignee_id else ticket.requester
        if recipient is None or not getattr(recipient, "email", None):
            return False
        if not email_enabled_for(recipient, category=SLA_CATEGORY):
            return False
        return send_ticket_notification(
            recipient.email, subject, body, ticket_id=ticket.pk)
    except Exception as exc:
        logger.warning("SLA breach notification failed: %s", type(exc).__name__)
        return False


def _notify_sla_approaching(ticket):
    """SLA approaching: in-app notification + (deduped) email to recipient."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active or not ticket.sla_due_at:
            return False
        deadline = sla.escalation_deadline(ticket.sla_due_at)
        if timezone.now() >= deadline:
            return _notify_sla_breached(ticket)
        recipient = ticket.assignee if ticket.assignee_id else ticket.requester
        if recipient is not None and getattr(recipient, "pk", None):
            _notify_user(recipient, None, f"SLA approaching ({ticket.priority})",
                         f"Ticket #{ticket.pk} is due for resolution by "
                         f"{deadline:%Y-%m-%d %H:%M}. Please prioritize.",
                         ticket)
        return send_sla_approaching(ticket)
    except Exception as exc:
        logger.warning("SLA approaching notification failed: %s",
                       type(exc).__name__)
        return False


def _notify_sla_breached(ticket):
    """SLA breached: in-app notification + (deduped) email to recipient."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active or not ticket.sla_due_at:
            return False
        if timezone.now() < sla.breach_deadline(ticket.sla_due_at):
            return False
        recipient = ticket.assignee if ticket.assignee_id else ticket.requester
        if recipient is not None and getattr(recipient, "pk", None):
            _notify_user(recipient, None, f"SLA breached ({ticket.priority})",
                         f"Ticket #{ticket.pk} has exceeded its SLA deadline.",
                         ticket)
        return send_sla_breached(ticket)
    except Exception as exc:
        logger.warning("SLA breach notification failed: %s", type(exc).__name__)
        return False


def send_maintenance_reminder(maintenance):
    """Send a scheduled/overdue maintenance reminder email."""
    try:
        if maintenance.status in ("completed", "cancelled"):
            return False
        subject = f"Maintenance due soon ({maintenance.title})"
        body = (
            f"Maintenance for asset {maintenance.asset.asset_tag} – "
            f"{maintenance.title} is scheduled for "
            f"{maintenance.scheduled_date:%Y-%m-%d %H:%M}. Please prepare."
        )
        recipient = None
        if maintenance.assigned_to_id:
            recipient = maintenance.assigned_to
        if recipient is None and maintenance.created_by_id:
            recipient = maintenance.created_by
        if recipient is None or not recipient.email:
            return False
        if not email_enabled_for(recipient, category=MAINTENANCE_CATEGORY):
            return False
        return send_ticket_notification(
            recipient.email, subject, body,
            ticket_id=f"maintenance-{maintenance.pk}")
    except Exception as exc:
        logger.warning("Maintenance reminder notification failed: %s",
                       type(exc).__name__)
        return False


def _notify_maintenance_reminder(maintenance):
    """Maintenance reminder: in-app notification + (deduped) email."""
    try:
        recipient = None
        if maintenance.assigned_to_id:
            recipient = maintenance.assigned_to
        if recipient is None and maintenance.created_by_id:
            recipient = maintenance.created_by
        if recipient is not None and getattr(recipient, "pk", None):
            from common.notifications import notify_user as _central_notify_user

            title = f"Maintenance due soon ({maintenance.title})"[:255]
            body = (
                f"Maintenance for asset {maintenance.asset.asset_tag} - "
                f"{maintenance.title} is scheduled for "
                f"{maintenance.scheduled_date:%Y-%m-%d %H:%M}. "
                "Please prepare."
            )
            _central_notify_user(
                recipient,
                category="maintenance_reminder",
                title=title,
                message=body,
                entity_type="assets.Maintenance",
                object_id=str(maintenance.pk),
                dedupe=True,
                post_commit=True,
            )
        return send_maintenance_reminder(maintenance)
    except Exception as exc:
        logger.warning("Maintenance reminder notification failed: %s",
                       type(exc).__name__)
        return False
