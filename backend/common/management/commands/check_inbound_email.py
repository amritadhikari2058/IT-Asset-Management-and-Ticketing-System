"""Read-only IMAP inbound email diagnostic.

Configuration-only (default):

    python backend/manage.py check_inbound_email

Optional live read-only connectivity:

    python backend/manage.py check_inbound_email --connect

Never fetches bodies, marks messages read, moves, deletes, or creates tickets.
Credentials are never printed.
"""

import sys
import imaplib
import ssl

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check inbound email configuration; optionally test read-only IMAP connectivity."

    def add_arguments(self, parser):
        parser.add_argument(
            "--connect",
            action="store_true",
            default=False,
            help="Attempt a read-only IMAP connection (mailbox SELECT only).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=10,
            help="Socket timeout in seconds (default 10).",
        )

    def handle(self, *args, **options):
        connect = options["connect"]
        timeout = options["timeout"]

        enabled = getattr(settings, "INBOUND_MAILBOX_ENABLED", True)
        host = (getattr(settings, "INBOUND_MAILBOX_HOST", "") or "").strip()
        port = getattr(settings, "INBOUND_MAILBOX_PORT", 993)
        user = (getattr(settings, "INBOUND_MAILBOX_USER", "") or "").strip()
        password = getattr(settings, "INBOUND_MAILBOX_PASSWORD", "")
        use_tls = bool(getattr(settings, "INBOUND_MAILBOX_USE_TLS", True))
        mailbox = (getattr(settings, "INBOUND_MAILBOX_NAME", "INBOX") or "INBOX")
        poll_seconds = getattr(settings, "INBOUND_MAILBOX_POLL_SECONDS", 60)

        self.stdout.write(f"Inbound mailbox enabled: {enabled}")
        self.stdout.write(f"IMAP host: {host or '(not set)'}")
        self.stdout.write(f"IMAP port: {port}")
        self.stdout.write(f"IMAP username: {user or '(not set)'}")
        self.stdout.write(f"IMAP password: {'present' if password else 'not set'}")
        self.stdout.write(f"IMAP TLS: {use_tls}")
        self.stdout.write(f"IMAP mailbox: {mailbox}")
        self.stdout.write(f"Poll interval: {poll_seconds}s")

        if not enabled:
            self.stdout.write("Inbound polling is disabled; no connectivity check performed.")
            sys.exit(0)

        if not host or not user:
            self.stderr.write(
                "ERROR: INBOUND_MAILBOX_ENABLED=true but host or user is not set.")
            sys.exit(1)

        if not connect:
            self.stdout.write(
                "Configuration looks complete. Use --connect to test "
                "read-only IMAP connectivity.")
            sys.exit(0)

        # Live read-only connectivity check.
        try:
            if use_tls:
                ctx = ssl.create_default_context()
                client = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
            else:
                client = imaplib.IMAP4(host, port)
            client.socket.settimeout(timeout)

            if user and password:
                client.login(user, password)
            # Read-only: SELECT does not modify messages.
            typ, _ = client.select(mailbox, readonly=True)
            if typ != "OK":
                self.stderr.write(
                    f"ERROR: Could not select mailbox '{mailbox}': {typ}")
                try:
                    client.logout()
                except Exception:
                    pass
                sys.exit(1)

            self.stdout.write(
                f"OK: Read-only IMAP connection succeeded to {host}:{port}, "
                f"mailbox '{mailbox}' selected.")
            try:
                client.logout()
            except Exception:
                pass
            sys.exit(0)

        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "authentication" in msg or "no password" in msg or "invalid" in msg:
                category = "authentication"
            elif "timed out" in msg or "timeout" in msg:
                category = "timeout"
            elif "getaddrinfo" in msg or "nodename" in msg or "refused" in msg:
                category = "dns_or_connection"
            else:
                category = "unknown"
            self.stderr.write(
                f"ERROR: IMAP connectivity failed ({category}): "
                f"{type(exc).__name__}")
            sys.exit(1)