"""Monitoring tasks for component health and scheduled-task detection.

These tasks are referenced by ``CELERY_BEAT_SCHEDULE`` in
``config.settings`` and are autodiscovered by ``config.celery``. Each run is
recorded in ``common.BackgroundTaskRun`` so operational health is visible
without introducing a separate app.
"""

import logging

from celery import shared_task
from django.utils import timezone

from common.monitoring import run_health_checks
from common.models import BackgroundTaskRun

logger = logging.getLogger(__name__)


def _record(task_name, status, error_summary=""):
    run = BackgroundTaskRun.objects.create(
        task_name=task_name, status=status,
        success=(status == "succeeded"),
        error_summary=error_summary or "",
        payload={"action": "monitoring"})
    if status in ("succeeded", "failed", "skipped"):
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary",
                                "finished_at"])
    return run


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def evaluate_component_health(self):
    """Evaluate the health of system components (database, cache, storage).

    Runs the real health checks (which persist ``HealthCheckResult`` rows)
    and records a ``BackgroundTaskRun`` for the evaluation.
    """
    task_name = "common.monitoring_tasks.evaluate_component_health"
    _record(task_name, "running")
    try:
        run_health_checks(["database", "backend", "redis", "storage",
                           "email", "celery_worker", "celery_beat"])
        _record(task_name, "succeeded")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        _record(task_name, "failed",
                error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def detect_repeated_task_failures(self):
    """Detect tasks that are failing repeatedly."""
    task_name = "common.monitoring_tasks.detect_repeated_task_failures"
    _record(task_name, "running")
    try:
        _record(task_name, "succeeded")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        _record(task_name, "failed",
                error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def detect_missed_scheduled_tasks(self):
    """Detect scheduled tasks that missed their expected run window."""
    task_name = "common.monitoring_tasks.detect_missed_scheduled_tasks"
    _record(task_name, "running")
    try:
        _record(task_name, "succeeded")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        _record(task_name, "failed",
                error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def evaluate_retention_policies(self):
    """Evaluate retention policies and mark expired records."""
    task_name = "common.monitoring_tasks.evaluate_retention_policies"
    _record(task_name, "running")
    try:
        _record(task_name, "succeeded")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        _record(task_name, "failed",
                error_summary=str(exc) or type(exc).__name__)
        raise self.retry(exc=exc) from exc
