"""Email helpers: verification, password reset, ticket notifications.

Provider-agnostic (Django SMTP backend via env). Failures are logged with
diagnostics but NEVER with secrets (no passwords, tokens, or hashes).
"""
import logging

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

logger = logging.getLogger(__name__)
_token_gen = PasswordResetTokenGenerator()


def _send(subject, body, to):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to],
                  fail_silently=False)
    except Exception as exc:
        # Log type + host only; never the token, address details beyond
        # domain, or message body (may contain links with tokens).
        domain = (to or "").split("@")[-1]
        logger.warning("Email delivery failed to @%s via %s: %s",
                       domain, settings.EMAIL_HOST or "(local)",
                       type(exc).__name__)


def send_verification_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = _token_gen.make_token(user)
    link = (f"{settings.FRONTEND_URL}/#/verify-email?uid={uid}&token={token}")
    _send("Verify your email",
          f"Hi,\n\nPlease verify your email by opening this link:\n{link}\n\n"
          f"If you did not request this, ignore it.",
          user.email)


def send_password_reset_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = _token_gen.make_token(user)
    link = (f"{settings.FRONTEND_URL}/#/reset-password"
            f"?uid={uid}&token={token}")
    _send("Password reset",
          f"Hi,\n\nReset your password here:\n{link}\n\n"
          f"If you did not request this, ignore it.",
          user.email)


def check_token(user, token):
    return _token_gen.check_token(user, token)


def decode_uid(uidb64):
    try:
        return force_str(urlsafe_base64_decode(uidb64))
    except Exception:
        return None


def send_ticket_notification(to_email, subject, body):
    if not to_email:
        return
    _send(subject, body, to_email)


def ticket_links(ticket_id):
    return (f"{settings.FRONTEND_URL}/#/tickets",
            f"{settings.BACKEND_URL}/api/tickets/{ticket_id}/")
