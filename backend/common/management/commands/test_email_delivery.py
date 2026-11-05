"""Safe outbound email diagnostic.

Configuration-only (default):

    python backend/manage.py test_email_delivery --dry-run

Explicit real-send mode (never automatic):

    python backend/manage.py test_email_delivery --to recipient@example.com --send

Never sends unless both --to and --send are supplied. Credentials are never printed.
"""

import sys
import re

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Command(BaseCommand):
    help = "Diagnose outbound email configuration without sending by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Check configuration only; do not send (default).",
        )
        parser.add_argument(
            "--send",
            action="store_true",
            default=False,
            help="Actually send a diagnostic email (requires --to).",
        )
        parser.add_argument(
            "--to",
            default=None,
            help="Recipient address for a real send (requires --send).",
        )

    def handle(self, *args, **options):
        do_send = options["send"]
        to = options["to"]
        dry_run = options["dry_run"] and not do_send

        self.stdout.write(f"Email backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"Default from: {settings.DEFAULT_FROM_EMAIL}")
        if settings.EMAIL_HOST:
            self.stdout.write(f"SMTP host: {settings.EMAIL_HOST}")
            self.stdout.write(f"SMTP port: {settings.EMAIL_PORT}")
            self.stdout.write(f"SMTP TLS: {settings.EMAIL_USE_TLS}")
            self.stdout.write(f"SMTP SSL: {settings.EMAIL_USE_SSL}")
            self.stdout.write(f"SMTP timeout: {settings.EMAIL_TIMEOUT}s")
            self.stdout.write("SMTP username: {'configured' if settings.EMAIL_HOST_USER else 'not set'}")
            self.stdout.write("SMTP password: {'present' if settings.EMAIL_HOST_PASSWORD else 'not set'}")
        else:
            self.stdout.write("SMTP host: not set")

        if do_send:
            if not to:
                self.stderr.write(
                    "ERROR: --send requires --to <recipient>.")
                sys.exit(2)
            if not EMAIL_RE.match(to or ""):
                self.stderr.write(f"ERROR: Invalid recipient address: {to}")
                sys.exit(2)
            if not settings.DEFAULT_FROM_EMAIL or "@" not in settings.DEFAULT_FROM_EMAIL:
                self.stderr.write(
                    "ERROR: DEFAULT_FROM_EMAIL is not configured; cannot send.")
                sys.exit(3)

            try:
                email = EmailMessage(
                    "IT Service Desk diagnostic",
                    "This is a diagnostic email from the IT Ticketing "
                    "& Asset Management System. No action is required.",
                    settings.DEFAULT_FROM_EMAIL,
                    [to],
                )
                email.send(fail_silently=False)
                self.stdout.write(
                    f"Diagnostic email accepted by SMTP backend for {to}.")
                self.stdout.write(
                    "SMTP acceptance confirmed; inbox delivery is not verified.")
                sys.exit(0)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(
                    f"ERROR: Email send failed: {type(exc).__name__}")
                sys.exit(4)

        # Dry-run / configuration-only.
        if "console" in settings.EMAIL_BACKEND or "locmem" in settings.EMAIL_BACKEND:
            self.stdout.write(
                "WARNING: Using a non-SMTP backend; no real mail is delivered.")
        else:
            self.stdout.write("SMTP backend configured; use --to/--send to test live delivery.")
        sys.exit(0)