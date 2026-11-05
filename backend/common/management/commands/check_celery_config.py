"""Celery configuration diagnostic (static, no worker contact).

Validates Celery settings without enqueuing or contacting a worker.
"""

import sys

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Validate Celery configuration without contacting a worker."

    def handle(self, *args, **options):
        s = settings
        errors = 0
        warnings = 0

        def err(msg):
            nonlocal errors
            errors += 1
            self.stderr.write(f"ERROR: {msg}")

        def warn(msg):
            nonlocal warnings
            warnings += 1
            self.stderr.write(f"WARNING: {msg}")

        def ok(msg):
            self.stdout.write(f"OK: {msg}")

        # Broker URL
        broker = getattr(s, "CELERY_BROKER_URL", "")
        if broker:
            ok(f"Broker URL configured: {broker.split('://')[0]}://***")
        else:
            err("CELERY_BROKER_URL is not configured")

        # Eager mode
        eager = getattr(s, "CELERY_TASK_ALWAYS_EAGER", False)
        if eager:
            warn("CELERY_TASK_ALWAYS_EAGER is true (tasks run inline)")
        else:
            ok("Celery eager mode is disabled")

        # Serializer
        serializer = getattr(s, "CELERY_TASK_SERIALIZER", "json")
        if serializer != "json":
            err(f"Task serializer is {serializer} (not JSON)")
        else:
            ok("Task serializer: json")

        # Accept content
        accept = list(getattr(s, "CELERY_ACCEPT_CONTENT", ["json"]))
        if "pickle" in accept:
            err("CELERY_ACCEPT_CONTENT allows pickle (unsafe)")
        else:
            ok(f"Accept content: {', '.join(accept)}")

        # Timezone
        tz = getattr(s, "CELERY_TIMEZONE", None) or getattr(s, "TIME_ZONE", "UTC")
        ok(f"Timezone: {tz}")

        # Time limits
        tlimit = getattr(s, "CELERY_TASK_TIME_LIMIT", 0)
        if tlimit > 0:
            ok(f"Task time limit: {tlimit}s")
        else:
            warn("CELERY_TASK_TIME_LIMIT is not bounded")

        # Result backend
        result_backend = getattr(s, "CELERY_RESULT_BACKEND", "")
        if result_backend:
            ok(f"Result backend: {result_backend.split('://')[0]}://***")
        else:
            warn("No result backend configured")

        # Task paths resolve
        beat = getattr(s, "CELERY_BEAT_SCHEDULE", {})
        if not beat:
            err("CELERY_BEAT_SCHEDULE is empty")
        else:
            ok(f"{len(beat)} Beat schedule entry(ies)")
            expected = [
                "tickets.tasks.check_sla_escalations",
                "assets.tasks.check_maintenance_reminders",
                "common.tasks.process_inbound_mailbox",
                "common.tasks.run_scheduled_reports",
            ]
            for path in expected:
                found = any(v.get("task") == path for v in beat.values())
                if not found:
                    err(f"Expected Beat task missing: {path}")
                    continue
                module_path, _, func_name = path.rpartition(".")
                try:
                    __import__(module_path, fromlist=[func_name])
                    ok(f"Beat task resolves: {path}")
                except Exception as exc:
                    err(f"Beat task path does not import: {path} ({exc})")

        # Retry settings
        retries = getattr(s, "CELERY_TASK_MAX_RETRIES", None)
        if retries is not None:
            ok(f"Max retries: {retries}")
        backoff = getattr(s, "CELERY_TASK_RETRY_BACKOFF", None)
        if backoff is not None:
            ok(f"Retry backoff: {backoff}s")

        if errors:
            self.stderr.write(f"\n{errors} error(s), {warnings} warning(s).")
            sys.exit(1)
        self.stdout.write(
            f"\nCelery configuration valid ({warnings} warning(s)).")
        sys.exit(0)