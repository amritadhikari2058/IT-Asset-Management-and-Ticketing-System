"""Monitoring tasks for component health and scheduled-task detection.

These tasks are referenced by ``CELERY_BEAT_SCHEDULE`` in
``config.settings`` and are autodiscovered by ``config.celery``. Each run is
recorded in ``common.BackgroundTaskRun`` so operational health is visible
without introducing a separate app.

Registration note: this module is not named ``tasks.py``, so Celery's
``autodiscover_tasks()`` does not find it. ``config/celery.py`` imports it
explicitly.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from common.models import BackgroundTaskRun
from common.monitoring import run_health_checks
from common.monitoring_service import create_or_update_alert

logger = logging.getLogger(__name__)

# A task is considered repeatedly failing when it has this many failed runs
# inside the window below.
REPEAT_FAILURE_THRESHOLD = 3
REPEAT_FAILURE_WINDOW_HOURS = 24
# A scheduled task counts as missed once its last run is older than this
# multiple of its configured interval.
MISSED_INTERVAL_MULTIPLIER = 2


def _start(task_name):
    """Create the single execution row for this attempt."""
    return BackgroundTaskRun.objects.create(
        task_name=task_name, status="running", success=False,
        payload={"action": "monitoring"})


def _finish(run, status, error_summary="", payload=None):
    """Finish the execution row started by :func:`_start` (no duplicate row)."""
    if payload is not None:
        run.payload = payload
    run.status = status
    run.success = status == "succeeded"
    run.error_summary = error_summary or ""
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "success", "error_summary",
                            "finished_at", "payload"])
    return run


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def evaluate_component_health(self):
    """Evaluate the health of system components (database, cache, storage).

    Runs the real health checks (which persist ``HealthCheckResult`` rows)
    and records a ``BackgroundTaskRun`` for the evaluation.
    """
    task_name = "common.monitoring_tasks.evaluate_component_health"
    run = _start(task_name)
    try:
        results = run_health_checks([
            "database", "backend", "redis", "storage", "email",
            "celery_worker", "celery_beat"])
        _finish(run, "succeeded",
                payload={"overall": results.get("overall", "")})
        return {"status": "ok", "overall": results.get("overall", "")}
    except Exception as exc:  # noqa: BLE001
        _finish(run, "failed", error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def detect_repeated_task_failures(self):
    """Detect tasks that are failing repeatedly and raise operational alerts.

    A task with at least ``REPEAT_FAILURE_THRESHOLD`` failed runs in the last
    ``REPEAT_FAILURE_WINDOW_HOURS`` hours produces one alert, deduplicated per
    task name by the alerting service, so a persistent failure does not flood
    the alert list.
    """
    task_name = "common.monitoring_tasks.detect_repeated_task_failures"
    run = _start(task_name)
    try:
        window_start = timezone.now() - timedelta(
            hours=REPEAT_FAILURE_WINDOW_HOURS)
        counts = {}
        for name in (BackgroundTaskRun.objects
                     .filter(status="failed", started_at__gte=window_start)
                     .values_list("task_name", flat=True)):
            counts[name] = counts.get(name, 0) + 1

        flagged = {}
        for name, count in counts.items():
            if count < REPEAT_FAILURE_THRESHOLD:
                continue
            create_or_update_alert(
                component="background_tasks",
                severity="warning",
                title=f"Repeated background task failures: {name}",
                description=(f"{count} failed runs in the last "
                             f"{REPEAT_FAILURE_WINDOW_HOURS} hours."),
                details={"task_name": name, "failure_count": count,
                         "window_hours": REPEAT_FAILURE_WINDOW_HOURS},
                dedup_key=f"repeated-task-failure:{name}",
            )
            flagged[name] = count

        _finish(run, "succeeded",
                payload={"flagged_tasks": flagged,
                         "window_hours": REPEAT_FAILURE_WINDOW_HOURS})
        return {"status": "ok", "flagged_tasks": flagged}
    except Exception as exc:  # noqa: BLE001
        _finish(run, "failed", error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc


def _interval_seconds(schedule):
    """Return a fixed interval for a Beat entry, or None for crontab entries."""
    if isinstance(schedule, (int, float)):
        return float(schedule)
    total = getattr(schedule, "total_seconds", None)
    if callable(total):
        try:
            return float(total())
        except (TypeError, ValueError):
            return None
    return None


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def detect_missed_scheduled_tasks(self):
    """Detect scheduled tasks that missed their expected run window.

    Only interval-based Beat entries are evaluated (crontab entries have no
    fixed interval that can be compared against the last run). A task is
    considered missed when its most recent recorded run is older than
    ``MISSED_INTERVAL_MULTIPLIER`` times its interval. Tasks that have never
    run are not reported here: Beat liveness is handled by the
    ``celery_beat`` health check.
    """
    task_name = "common.monitoring_tasks.detect_missed_scheduled_tasks"
    run = _start(task_name)
    try:
        now = timezone.now()
        beat_schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {}) or {}
        missed = {}
        for entry_name, entry in beat_schedule.items():
            scheduled_task = (entry or {}).get("task")
            interval = _interval_seconds((entry or {}).get("schedule"))
            if not scheduled_task or not interval or interval <= 0:
                continue
            last_run = (BackgroundTaskRun.objects
                        .filter(task_name=scheduled_task)
                        .order_by("-started_at").first())
            if last_run is None:
                continue
            threshold = timedelta(
                seconds=interval * MISSED_INTERVAL_MULTIPLIER)
            if now - last_run.started_at <= threshold:
                continue
            age_seconds = int((now - last_run.started_at).total_seconds())
            missed[scheduled_task] = age_seconds
            create_or_update_alert(
                component="celery_beat",
                severity="warning",
                title=f"Scheduled task missed its run window: {scheduled_task}",
                description=(f"Last observed run was {age_seconds}s ago; "
                             f"expected every {int(interval)}s "
                             f"(entry '{entry_name}')."),
                details={"task_name": scheduled_task,
                         "entry": entry_name,
                         "interval_seconds": int(interval),
                         "age_seconds": age_seconds},
                dedup_key=f"missed-scheduled-task:{scheduled_task}",
            )

        _finish(run, "succeeded", payload={"missed_tasks": missed})
        return {"status": "ok", "missed_tasks": missed}
    except Exception as exc:  # noqa: BLE001
        _finish(run, "failed", error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc
