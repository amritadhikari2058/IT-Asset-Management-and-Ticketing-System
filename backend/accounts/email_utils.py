"""Email helpers: verification, password reset, ticket notifications.

- Outgoing ticket / SLA / maintenance notifications go through the
  provider-agnostic Django SMTP backend (env-configured).
- Delivery failures are caught and logged WITHOUT credentials or message
  bodies; the ticket flow itself never breaks on mail problems.
- A short-lived cache key (ticket + subject + recipient) prevents duplicate
  outbound delivery for retried/duplicate events.
- Password-reset + verification links use Django's token generators and
  never leak account existence.
"""
import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage, send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils import timezone

from common.models import Notification
from common.notifications import (
    KB_REVIEW_CATEGORY, MAINTENANCE_CATEGORY, SLA_CATEGORY,
    email_enabled_for, scheduled_report_delivery_enabled,
)
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


def _dedup_key(ticket_id, subject, to_email):
    import hashlib
    ticket_part = str(ticket_id) if ticket_id is not None else "ticket"
    subject_part = (subject or "").strip().lower()
    to_part = (to_email or "").lower()
    digest = hashlib.sha256(
        f"{ticket_part}|{subject_part}|{to_part}".encode("utf-8")
    ).hexdigest()[:32]
    return f"email_sent:{digest}"


def _cache():
    from django.core.cache import cache
    return cache


def send_ticket_notification(to_email, subject, body, ticket_id=None, user=None, category=None):
    """Send a ticket notification email (deduped, best-effort).

    The outbound decision is centralized in ``common.notifications`` so the
    global + category preference switches are applied exactly once per send.

    - ``user`` is the preference-aware recipient account (ticket events,
      SLA, maintenance all pass it through here).
    - ``category`` is the notification category being delivered (``None``
      for global/master-only ticket acknowledgements).

    Scheduled report deliveries do NOT go through this helper: they use the
    explicit scheduled-report recipient policy instead.

    Returns True when the mail was handed to the backend, False when it was
    skipped (preferences / duplicate) or failed. Failures never raise into
    callers.
    """
    if not to_email:
        return False
    if user is not None and not email_enabled_for(user, category=category):
        # User opted out (master switch or this category): skip outbound
        # email. In-app notifications are unaffected (see _notify_user).
        return False
    key = _dedup_key(ticket_id, subject, to_email)
    cache = _cache()
    try:
        if cache.get(key):
            logger.info("Duplicate ticket email suppressed: %s", subject)
            return False
    except Exception:
        pass  # cache unavailable -> fail open and send anyway
    ok = False
    try:
        _send(subject, body, to_email)
        ok = True
    except Exception as exc:
        logger.warning("Ticket email send failed: %s", type(exc).__name__)
    try:
        cache.set(key, True, int(getattr(
            settings, "EMAIL_DEDUP_TTL_SECONDS", 3600)))
    except Exception:
        pass
    return ok


def send_kb_notification(to_email, subject, body, article=None, user=None):
    """Send a Knowledge Base review/publication email (deduped, best-effort).

    Mirrors ``send_ticket_notification``: the outbound decision is
    centralized in ``common.notifications`` so the global + ``kb_review``
    category preference switches are applied exactly once per send. Failures
    are logged without secrets and never raise into callers.
    """
    if not to_email:
        return False
    if user is not None and not email_enabled_for(user, category=KB_REVIEW_CATEGORY):
        return False
    article_id = article.pk if article is not None else None
    key = _dedup_key(article_id, subject, to_email)
    cache = _cache()
    try:
        if cache.get(key):
            logger.info("Duplicate KB email suppressed: %s", subject)
            return False
    except Exception:
        pass  # cache unavailable -> fail open and send anyway
    ok = False
    try:
        _send(subject, body, to_email)
        ok = True
    except Exception as exc:
        logger.warning("KB email send failed: %s", type(exc).__name__)
    try:
        cache.set(key, True, int(getattr(
            settings, "EMAIL_DEDUP_TTL_SECONDS", 3600)))
    except Exception:
        pass
    return ok


def ticket_links(ticket_id):
    return (f"{settings.FRONTEND_URL}/#/tickets",
            f"{settings.BACKEND_URL}/api/tickets/{ticket_id}/")


# ---------- In-app notification + outbound email for ticket events ----------

def _notify_user(recipient, actor, title, body, ticket):
    """Create an in-app notification; never notify the actor of their own
    action, never for inactive/deleted users, never leak internal content.
    """
    if recipient is None or getattr(recipient, "pk", None) is None:
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    return Notification.objects.create(
        recipient=recipient, title=title[:255], body=body or "",
        entity_type="tickets.Ticket", object_id=str(ticket.pk))


def _notify_sla_approaching(ticket):
    """SLA approaching: in-app notification + (deduped) email to requester."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active or not ticket.sla_due_at:
            # No SLA clock attached (or config inactive): nothing to report.
            return False
        deadline = sla.escalation_deadline(ticket.sla_due_at)
        if timezone.now() >= deadline:
            # Escalation window already elapsed -> handled by breach path.
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
    """SLA breached: in-app notification + (deduped) email to requester."""
    try:
        sla = ticket.priority_sla
        if not sla or not sla.is_active or not ticket.sla_due_at:
            return False
        if timezone.now() < sla.breach_deadline(ticket.sla_due_at):
            # Breach window has not been reached yet -> nothing to report.
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


def _notify_maintenance_reminder(maintenance):
    """Maintenance reminder: in-app notification + (deduped) email."""
    try:
        recipient = None
        if maintenance.assigned_to_id:
            recipient = maintenance.assigned_to
        if recipient is None and maintenance.created_by_id:
            recipient = maintenance.created_by
        if recipient is not None and getattr(recipient, "pk", None):
            Notification.objects.create(
                recipient=recipient,
                title=f"Maintenance due soon ({maintenance.title})",
                body=f"Maintenance for asset {maintenance.asset.asset_tag} – "
                     f"{maintenance.title} is scheduled for "
                     f"{maintenance.scheduled_date:%Y-%m-%d %H:%M}. "
                     "Please prepare.",
                entity_type="assets.Maintenance",
                object_id=str(maintenance.pk))
        return send_maintenance_reminder(maintenance)
    except Exception as exc:
        logger.warning("Maintenance reminder notification failed: %s",
                      type(exc).__name__)
        return False


# ---------- Auth-related transactional emails ----------

def _token_uid(user):
    return urlsafe_base64_encode(force_bytes(user.pk))


def _token_check(user, token):
    if not user or not token:
        return False
    return default_token_generator.check_token(user, token)


def decode_uid(uid):
    """Decode a uid=... token from a verification/reset link back to pk."""
    if not uid:
        return None
    try:
        return int(urlsafe_base64_decode(uid))
    except Exception:
        return None


def check_token(user, token):
    return _token_check(user, token)


def send_password_reset_email(user):
    """Send a password-reset email (generic content, no account leak).

    ESSENTIAL / security transactional email: never suppressed by user
    notification preferences (central policy in ``common.notifications``).
    """
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
    _send(
        "Password reset requested",
        "If an account exists for this address, a password reset link "
        f"was generated.\n\nReset password: {link}\n\nThis link expires "
        "quickly and can only be used once. If you did not request this, "
        "ignore this email.",
        user.email,
    )


def send_verification_email(user):
    """Send an email-verification email with uid/token link.

    ESSENTIAL / security transactional email: never suppressed by user
    notification preferences (central policy in ``common.notifications``).
    """
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    link = f"{settings.FRONTEND_URL}/verify-email?uid={uid}&token={token}"
    _send(
        "Verify your email",
        "Welcome! Confirm your email address to activate your account.\n\n"
        f"Verify: {link}\n\nThis link expires quickly and can only be "
        "used once.",
        user.email,
    )


# ---------- SLA notifications ----------

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
            # Centralized preference check (master switch + sla_escalation).
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
        breach_deadline = sla.breach_deadline(ticket.sla_due_at)
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
            # Centralized preference check (master switch + sla_escalation).
            return False
        return send_ticket_notification(
            recipient.email, subject, body, ticket_id=ticket.pk)
    except Exception as exc:
        logger.warning("SLA breach notification failed: %s", type(exc).__name__)
        return False


# ---------- Maintenance reminders ----------

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
            # Centralized preference check (master switch + maintenance).
            return False
        return send_ticket_notification(
            recipient.email, subject, body,
            ticket_id=f"maintenance-{maintenance.pk}")
    except Exception as exc:
        logger.warning("Maintenance reminder notification failed: %s",
                      type(exc).__name__)
        return False


def send_scheduled_report_email(to_email, subject, body, filename, content, content_type):
    """Send one scheduled-report delivery email with file attachment.

    Best-effort: failures are logged (domain + exception type only) and never
    raised into the delivery loop.

    Recipient policy: scheduled reports are delivered to the explicit
    recipient list configured on the schedule (IT / staff authored) and do
    NOT inherit unrelated per-user notification categories. The decision is
    centralized via ``common.notifications.scheduled_report_delivery_enabled``.
    """
    if not to_email or not scheduled_report_delivery_enabled():
        return False
    try:
        email = EmailMessage(
            subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])
        email.attach(filename, content, content_type)
        email.send(fail_silently=False)
        return True
    except Exception as exc:  # noqa: BLE001
        domain = (to_email or "").split("@")[-1]
        logger.warning(
            "Scheduled report email failed to %s via %s: %s",
            domain, settings.EMAIL_HOST or "(local)", type(exc).__name__)
        return False
