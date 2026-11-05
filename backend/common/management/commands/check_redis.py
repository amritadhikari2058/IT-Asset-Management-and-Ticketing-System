"""Safe Redis / Celery broker diagnostic.

Performs a harmless PING only. Never lists, reads, or deletes keys.
"""

import sys
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - redis is a project dependency
    redis_lib = None


def _sanitize_url(url):
    if not url:
        return "(not set)"
    try:
        parsed = urlparse(url)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        path = parsed.path or ""
        if parsed.query:
            path += f"?{parsed.query}"
        return f"{parsed.scheme or ''}://{netloc}{path}"
    except Exception:
        return "(redacted)"


class Command(BaseCommand):
    help = "Ping the configured Redis broker (read-only, no key access)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=5,
            help="Socket timeout in seconds (default 5).",
        )
        parser.add_argument(
            "--url",
            default=None,
            help="Override broker URL (sanitized in output).",
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]
        url = options["url"] or getattr(settings, "CELERY_BROKER_URL", "")
        if not url:
            self.stderr.write("ERROR: CELERY_BROKER_URL is not configured.")
            sys.exit(1)
        if redis_lib is None:
            self.stderr.write("ERROR: redis Python package is not installed.")
            sys.exit(1)

        try:
            parsed = urlparse(url)
            client = redis_lib.Redis(
                host=parsed.hostname or "localhost",
                port=parsed.port or 6379,
                db=int(parsed.path.lstrip("/") or 0),
                password=parsed.password or None,
                ssl=(parsed.scheme == "rediss"),
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
                health_check_interval=30,
            )
            pong = client.ping()
        except Exception as exc:  # noqa: BLE001 - categorize safely
            msg = str(exc)
            if "authentication" in msg.lower() or "no password" in msg.lower():
                category = "authentication"
            elif "timed out" in msg.lower() or "timeout" in msg.lower():
                category = "timeout"
            elif "nodename" in msg.lower() or "getaddrinfo" in msg.lower() \
                    or "refused" in msg.lower():
                category = "connection"
            else:
                category = "unknown"
            self.stderr.write(
                f"ERROR: Redis PING failed ({category}): {type(exc).__name__}")
            sys.exit(1)

        if pong:
            self.stdout.write(
                f"OK: Redis PING succeeded via {_sanitize_url(url)} "
                f"(timeout={timeout}s)")
            sys.exit(0)
        self.stderr.write("ERROR: Redis PING returned unexpected response.")
        sys.exit(1)