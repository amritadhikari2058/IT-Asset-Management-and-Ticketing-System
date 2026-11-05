"""Celery worker diagnostic via inspect ping (short timeout, no work enqueued)."""

import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ping Celery workers via inspect (read-only, no work enqueued)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=5,
            help="Inspect timeout in seconds (default 5).",
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]

        try:
            from celery import current_app
        except ImportError:  # pragma: no cover
            self.stderr.write("ERROR: Celery is not installed.")
            sys.exit(1)

        try:
            inspector = current_app.control.inspect(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(
                f"ERROR: Celery inspect failed (broker may be down): "
                f"{type(exc).__name__}")
            sys.exit(1)
        if inspector is None:
            self.stderr.write(
                "ERROR: Could not obtain Celery inspector (broker may be down).")
            sys.exit(1)

        try:
            ping = inspector.ping()
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(
                f"ERROR: Celery inspect ping failed: {type(exc).__name__}")
            sys.exit(1)

        if not ping:
            self.stderr.write(
                "ERROR: No Celery workers responded to inspect ping "
                f"(timeout={timeout}s).")
            sys.exit(1)

        # Sanitize worker hostnames (may reveal internal host info).
        worker_count = len(ping)
        self.stdout.write(
            f"OK: {worker_count} Celery worker(s) responded to ping.")
        sys.exit(0)