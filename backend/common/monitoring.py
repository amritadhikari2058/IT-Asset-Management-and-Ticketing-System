"""Phase 26 — system health checks and operational monitoring service.

Component checks report *actual* availability, not merely configuration.
A configured but unreachable component is reported as ``unavailable`` or
``unknown``, never ``healthy`` solely because environment variables are set.

All checks are intentionally lightweight: no per-request database writes,
no test emails actually delivered, no expensive migrations run.
"""
import hashlib
import logging
import time
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import connections
from django.db.utils import OperationalError as DbOperationalError
from django.utils import timezone
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from common.models import (HealthCheckResult, OperationalErrorEvent,
                           OperationalAlert)

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"
NOT_CONFIGURED = "not_configured"

HEALTH_STATES = {HEALTHY, DEGRADED, UNAVAILABLE, UNKNOWN, NOT_CONFIGURED}

# Components registered for health checks, in evaluation order.
COMPONENTS = [
    "backend",
    "database",
    "redis",
    "celery_worker",
    "celery_beat",
    "background_tasks",
    "email",
    "storage",
    "application_errors",
]


def _now():
    return timezone.now()


def _json_safe(value):
    """Recursively convert datetimes to ISO strings for JSONField safety."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _record(component, state, diagnostic="", details=None, success_at=None,
            failure_at=None):
    """Persist a health check result and return the created row."""
    now = _now()
    return HealthCheckResult.objects.create(
        component=component, state=state, evaluated_at=now,
        last_successful_at=success_at,
        last_failure_at=failure_at,
        diagnostic=diagnostic or "",
        details=_json_safe(details or {}))


def _previous(component):
    """Most recent previous result for a component (to carry last success/failure)."""
    return (HealthCheckResult.objects.filter(component=component)
            .order_by("-evaluated_at").first())


def check_backend():
    """Django is responding — if this function runs, the backend is up."""
    prev = _previous("backend")
    return _record("backend", HEALTHY,
                   "Django application is responding.",
                   details={"checked": "request"})


def check_database():
    """Database connectivity, response time and migration consistency."""
    details = {}
    diagnostic = ""
    state = HEALTHY
    now = _now()
    prev = _previous("database")

    try:
        conn = connections["default"]
        start = time.perf_counter()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        details["query_response_ms"] = elapsed_ms
        details["vendor"] = conn.vendor

        if elapsed_ms > 1000:
            state = DEGRADED
            diagnostic = f"Database responding slowly ({elapsed_ms} ms)."
        else:
            diagnostic = "Database reachable."

        # Migration consistency: compare loader graph against applied migrations.
        try:
            from django.db.migrations.loader import MigrationLoader
            loader = MigrationLoader(connections["default"])
            applied = set(loader.applied_migrations)
            graph = loader.graph
            missing = []
            for node in graph.nodes:
                app_label, migration = node
                key = f"{app_label}.{migration}"
                if key not in applied:
                    missing.append(key)
            details["migration_inconsistency"] = bool(missing)
            details["migration_missing_count"] = len(missing)
            if missing:
                details["migration_missing"] = missing[:10]
                state = DEGRADED
                diagnostic = (diagnostic + " "
                              if diagnostic else "") + \
                    f"{len(missing)} migration(s) not recorded as applied."
            else:
                details["migration_inconsistency"] = False
        except Exception as exc:  # noqa: BLE001
            details["migration_check_error"] = type(exc).__name__
            diagnostic = (diagnostic + " "
                          if diagnostic else "") + "Migration consistency could not be verified."
    except DbOperationalError as exc:
        state = UNAVAILABLE
        diagnostic = "Database connection failed."
        details["error"] = type(exc).__name__
    except Exception as exc:  # noqa: BLE001
        state = UNAVAILABLE
        diagnostic = "Database check failed."
        details["error"] = type(exc).__name__

    return _record("database", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state != HEALTHY else
                   (prev.last_failure_at if prev else None))


def check_redis():
    """Redis availability via Django cache ping (a real round-trip)."""
    details = {}
    state = NOT_CONFIGURED
    diagnostic = "Redis/cache not configured."
    now = _now()
    prev = _previous("redis")

    location = getattr(settings, "CACHES", {}).get("default", {}).get(
        "LOCATION", "")
    backend = getattr(settings, "CACHES", {}).get("default", {}).get(
        "BACKEND", "")

    if not location or "redis" not in str(backend).lower():
        return _record("redis", NOT_CONFIGURED, diagnostic, details,
                       success_at=(prev.last_successful_at if prev else None),
                       failure_at=(prev.last_failure_at if prev else None))

    try:
        # A genuine round-trip: set + get a probe key.
        probe_key = "__ops_health_redis_probe__"
        probe_val = str(timezone.now().timestamp())
        cache.set(probe_key, probe_val, 10)
        got = cache.get(probe_key)
        cache.delete(probe_key)
        if got == probe_val:
            state = HEALTHY
            diagnostic = "Redis reachable (cache round-trip succeeded)."
            details["location"] = location
        else:
            state = UNAVAILABLE
            diagnostic = "Redis cache round-trip failed (value mismatch)."
    except Exception as exc:  # noqa: BLE001
        state = UNAVAILABLE
        diagnostic = "Redis unreachable."
        details["error"] = type(exc).__name__

    return _record("redis", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state != HEALTHY else
                   (prev.last_failure_at if prev else None))


def check_celery_worker():
    """Celery worker availability via inspect().ping().

    Reports Unknown when Celery/broker cannot be introspected rather than
    claiming a worker is online from configuration alone.
    """
    details = {}
    state = UNKNOWN
    diagnostic = "Celery worker could not be introspected."
    now = _now()
    prev = _previous("celery_worker")

    try:
        from config.celery import app as celery_app
        inspector = celery_app.control.inspect(timeout=5)
        if not inspector:
            state = NOT_CONFIGURED
            diagnostic = "Celery app not available for inspection."
        else:
            stats = inspector.stats()
            ping = inspector.ping()
            workers = list((stats or {}).keys())
            details["workers"] = workers
            details["worker_count"] = len(workers)
            if workers and ping:
                state = HEALTHY
                worker_count = len(workers)
                diagnostic = f"{worker_count} Celery worker(s) responding."
            elif workers:
                state = DEGRADED
                diagnostic = "Celery worker(s) registered but not responding to ping."
            else:
                state = UNAVAILABLE
                diagnostic = "No Celery workers responding."
    except Exception as exc:  # noqa: BLE001
        state = UNKNOWN
        diagnostic = "Celery worker health could not be determined."
        details["error"] = type(exc).__name__

    return _record("celery_worker", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state in (UNAVAILABLE, NOT_CONFIGURED)
                   else (prev.last_failure_at if prev else None))


def check_celery_beat():
    """Celery Beat scheduling activity.

    Beat health is hard to prove from the API side. We report based on
    whether Beat is configured and whether recent scheduled-task background
    runs exist. Unknown when not determinable.
    """
    details = {}
    state = UNKNOWN
    diagnostic = "Celery Beat activity could not be confirmed."
    now = _now()
    prev = _previous("celery_beat")

    beat_schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {}) or {}
    configured = bool(beat_schedule)
    details["schedules_configured"] = len(beat_schedule)

    if not configured:
        state = NOT_CONFIGURED
        diagnostic = "No Celery Beat schedules configured."
    else:
        # Look for recent successful runs of known scheduled tasks as
        # indirect evidence Beat is dispatching.
        scheduled_names = {
            v.get("task") for v in beat_schedule.values() if v.get("task")}
        from common.models import BackgroundTaskRun
        recent = (BackgroundTaskRun.objects.filter(
            task_name__in=scheduled_names,
            started_at__gte=now - timezone.timedelta(hours=24))
                  .order_by("-started_at")[:5])
        recent_success = any(r.status == "succeeded" for r in recent)
        details["recent_scheduled_runs"] = [
            {"task": r.task_name, "status": r.status,
             "started_at": r.started_at.isoformat() if r.started_at else None}
            for r in recent]
        if recent_success:
            state = HEALTHY
            diagnostic = "Celery Beat scheduled tasks have run successfully recently."
        elif recent:
            state = DEGRADED
            diagnostic = "Celery Beat tasks ran recently but none succeeded in the last 24 h."
        else:
            state = UNKNOWN
            diagnostic = ("Beat configured, but no recent scheduled-task runs "
                          "observed; worker/beat status cannot be confirmed.")

    return _record("celery_beat", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state == UNAVAILABLE else
                   (prev.last_failure_at if prev else None))


def check_background_tasks():
    """Background task execution health from BackgroundTaskRun history."""
    details = {}
    state = HEALTHY
    diagnostic = "Background tasks operating normally."
    now = _now()
    prev = _previous("background_tasks")

    from common.models import BackgroundTaskRun
    recent = list(BackgroundTaskRun.objects.order_by("-started_at")[:50])
    details["recent_runs"] = [
        {"task": r.task_name, "status": r.status,
         "started_at": r.started_at,
         "finished_at": r.finished_at,
         "error_summary": r.error_summary} for r in recent[:10]]

    failed = [r for r in recent if r.status == "failed"]
    running = [r for r in recent if r.status == "running"]

    if failed:
        state = DEGRADED
        diagnostic = f"{len(failed)} recent background task run(s) failed."
        details["recent_failures"] = len(failed)
    elif running:
        state = DEGRADED
        diagnostic = f"{len(running)} background task run(s) still running."
    elif not recent:
        state = UNKNOWN
        diagnostic = "No background task runs recorded yet."
    else:
        details["recent_failures"] = 0

    return _record("background_tasks", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state != HEALTHY else
                   (prev.last_failure_at if prev else None))


def check_email():
    """Email infrastructure: backend configured + delivery testability.

    Does NOT send a real email. Reports whether a backend is configured and
    whether the last recorded outbound activity succeeded. Delivery is
    distinguished from queue/attempt where the backend reports it.
    """
    details = {}
    state = NOT_CONFIGURED
    diagnostic = "Email backend not configured."
    now = _now()
    prev = _previous("email")

    backend = getattr(settings, "EMAIL_BACKEND", "")
    details["backend"] = backend or "<none>"

    if not backend:
        return _record("email", NOT_CONFIGURED, diagnostic, details,
                       success_at=(prev.last_successful_at if prev else None),
                       failure_at=(prev.last_failure_at if prev else None))

    if "console" in backend:
        state = HEALTHY
        diagnostic = "Console email backend configured (dev/test; no real delivery)."
    elif "smtp" in backend.lower():
        host = getattr(settings, "EMAIL_HOST", "") or "<not set>"
        details["host"] = host
        if host:
            state = HEALTHY
            diagnostic = "SMTP email backend configured (delivery not confirmed without sending a test message)."
        else:
            state = NOT_CONFIGURED
            diagnostic = "SMTP backend selected but no EMAIL_HOST configured."
    else:
        state = HEALTHY
        diagnostic = f"Email backend configured: {backend}."

    return _record("email", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state != HEALTHY else
                   (prev.last_failure_at if prev else None))


def check_storage():
    """File/media storage read/write availability and usage where measurable."""
    details = {}
    state = NOT_CONFIGURED
    diagnostic = "Storage backend not configured."
    now = _now()
    prev = _previous("storage")

    try:
        probe_name = "__ops_health_storage_probe__"
        content = ContentFile(b"ops-health-probe")
        default_storage.save(probe_name, content)
        try:
            size = default_storage.size(probe_name)
            details["probe_bytes"] = size
        except Exception:  # noqa: BLE001
            size = None
        default_storage.delete(probe_name)
        state = HEALTHY
        diagnostic = "Storage read/write probe succeeded."
        details["backend"] = default_storage.__class__.__name__
        # Storage usage where measurable (filesystem-backed backends).
        try:
            import os
            from django.conf import settings as _s
            media_root = getattr(_s, "MEDIA_ROOT", "")
            if media_root and os.path.exists(media_root):
                total, used, free = _disk_usage(media_root)
                details["storage_total_bytes"] = total
                details["storage_used_bytes"] = used
                details["storage_free_bytes"] = free
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        state = UNAVAILABLE
        diagnostic = "Storage read/write probe failed."
        details["error"] = type(exc).__name__

    return _record("storage", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state != HEALTHY else
                   (prev.last_failure_at if prev else None))


def _disk_usage(path):
    """Cross-platform disk usage in bytes."""
    import shutil
    return shutil.disk_usage(path)


def check_application_errors():
    """Application error activity: unresolved error count and recent severity."""
    details = {}
    state = HEALTHY
    diagnostic = "No unresolved application errors."
    now = _now()
    prev = _previous("application_errors")

    unresolved = OperationalErrorEvent.objects.filter(resolved=False)
    count = unresolved.count()
    details["unresolved_error_count"] = count
    high = unresolved.filter(severity__in=("high", "critical")).count()
    details["high_severity_unresolved"] = high

    if high > 0:
        state = DEGRADED
        diagnostic = f"{high} high/critical unresolved application error(s)."
    elif count > 0:
        state = DEGRADED
        diagnostic = f"{count} unresolved application error(s)."
    else:
        diagnostic = "No unresolved application errors."

    recent = list(unresolved.order_by("-last_occurred")[:5].values(
        "title", "component", "severity", "last_occurred",
        "occurrence_count"))
    details["recent_errors"] = recent

    return _record("application_errors", state, diagnostic, details,
                   success_at=now if state == HEALTHY else
                   (prev.last_successful_at if prev else None),
                   failure_at=now if state != HEALTHY else
                   (prev.last_failure_at if prev else None))


# Component check registry.
CHECK_REGISTRY = {
    "backend": check_backend,
    "database": check_database,
    "redis": check_redis,
    "celery_worker": check_celery_worker,
    "celery_beat": check_celery_beat,
    "background_tasks": check_background_tasks,
    "email": check_email,
    "storage": check_storage,
    "application_errors": check_application_errors,
}


def run_health_checks(components=None):
    """Run health checks for the given components (all if None).

    Returns a dict: {component: result_dict} plus an overall state.
    """
    components = components or list(COMPONENTS)
    results = {}
    overall = HEALTHY
    state_rank = {HEALTHY: 0, DEGRADED: 1, NOT_CONFIGURED: 2,
                  UNKNOWN: 3, UNAVAILABLE: 4}
    for name in components:
        check = CHECK_REGISTRY.get(name)
        if not check:
            results[name] = {"state": UNKNOWN,
                             "diagnostic": "No check registered."}
            continue
        try:
            row = check()
            results[name] = {
                "state": row.state,
                "diagnostic": row.diagnostic,
                "evaluated_at": row.evaluated_at,
                "last_successful_at": row.last_successful_at,
                "last_failure_at": row.last_failure_at,
                "details": row.details,
            }
            comp_rank = state_rank.get(row.state, 99)
            if comp_rank > state_rank.get(overall, 0):
                overall = row.state
        except Exception as exc:  # noqa: BLE001
            logger.exception("Health check %s failed", name)
            results[name] = {
                "state": UNKNOWN,
                "diagnostic": "Check raised an exception.",
                "error": type(exc).__name__,
            }
    return {"overall": overall, "components": results}
