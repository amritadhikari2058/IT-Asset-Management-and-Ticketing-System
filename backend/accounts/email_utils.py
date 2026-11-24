"""Account auth email/token helpers.

Auth/security emails (password reset, verification) live here. Domain
notification delivery (ticket/SLA/maintenance/KB/scheduled reports) has moved
to ``common.notification_delivery`` and ``common.email``; legacy names are
re-exported for backward compatibility.
"""
import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage, send_mail  # noqa: F401 - patch surface
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode



logger = logging.getLogger(__name__)


def _send(subject, body, to):
    """Send a single email, logging failures without exposing secrets."""
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


# ---------- Auth token helpers ----------

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


# ---------- Auth/security transactional emails ----------

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


# ---------- Backward-compatible re-exports ----------
# Domain notification delivery moved to common.notification_delivery / common.email.
_MOVED = {
    "send_ticket_notification": ("common.notification_delivery", "send_ticket_notification"),
    "send_kb_notification": ("common.notification_delivery", "send_kb_notification"),
    "ticket_links": ("common.notification_delivery", "ticket_links"),
    "_notify_user": ("common.notification_delivery", "_notify_user"),
    "_notify_sla_approaching": ("common.notification_delivery", "_notify_sla_approaching"),
    "_notify_sla_breached": ("common.notification_delivery", "_notify_sla_breached"),
    "_notify_maintenance_reminder": ("common.notification_delivery", "_notify_maintenance_reminder"),
    "send_sla_approaching": ("common.notification_delivery", "send_sla_approaching"),
    "send_sla_breached": ("common.notification_delivery", "send_sla_breached"),
    "send_maintenance_reminder": ("common.notification_delivery", "send_maintenance_reminder"),
    "send_scheduled_report_email": ("common.email", "send_scheduled_report_email"),
}


def __getattr__(name):
    target = _MOVED.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr = target
    from importlib import import_module
    mod = import_module(module_name)
    value = getattr(mod, attr)
    globals()[name] = value
    return value
