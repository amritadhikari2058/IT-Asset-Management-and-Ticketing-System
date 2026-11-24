"""Low-level email delivery helpers.

Provider-agnostic Django SMTP sending with safe logging (no secrets/message
bodies). Delivery failures are caught and logged; callers decide how to handle
False returns.
"""
import hashlib
import logging

from django.conf import settings
from django.core.mail import EmailMessage, send_mail

logger = logging.getLogger(__name__)


def _cache():
    from django.core.cache import cache
    return cache


def _dedup_key(entity_id, subject, to_email):
    entity_part = str(entity_id) if entity_id is not None else "entity"
    subject_part = (subject or "").strip().lower()
    to_part = (to_email or "").lower()
    digest = hashlib.sha256(
        f"{entity_part}|{subject_part}|{to_part}".encode("utf-8")
    ).hexdigest()[:32]
    return f"email_sent:{digest}"


def send_email(subject, body, to):
    """Send a single email, logging failures without exposing secrets.

    Only the domain, exception type and a generic message are logged.
    Returns True when the backend accepted the message, False otherwise.
    """
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to],
                  fail_silently=False)
        return True
    except Exception as exc:
        domain = (to or "").split("@")[-1]
        logger.warning(
            "Email delivery failed to @%s via %s: %s",
            domain, settings.EMAIL_HOST or "(local)",
            type(exc).__name__)
        return False


# Backward-compatible private alias used by older call sites.
_send = send_email


def send_scheduled_report_email(to_email, subject, body, filename, content,
                                content_type):
    """Send one scheduled-report delivery email with file attachment.

    Best-effort: failures are logged (domain + exception type only) and never
    raised into the delivery loop.

    Recipient policy: scheduled reports are delivered to the explicit
    recipient list configured on the schedule (IT / staff authored) and do
    NOT inherit unrelated per-user notification categories. The decision is
    centralized via ``common.notifications.scheduled_report_delivery_enabled``.
    """
    from common.notifications import scheduled_report_delivery_enabled

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
