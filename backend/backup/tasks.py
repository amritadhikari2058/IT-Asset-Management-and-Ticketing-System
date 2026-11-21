"""Celery Background Tasks for Backup & DR.

This app is a registered placeholder: it has no models, views or URLs yet.
No backup/disaster-recovery execution is implemented here, and nothing in
this phase should be read as evidence that backups are configured.

``sync_beat_schedules`` is kept importable for the planned feature, but it is
deliberately not scheduled in ``CELERY_BEAT_SCHEDULE`` and it no longer
reports success for work it did not do.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_beat_schedules(self=None):
    """Planned backup-schedule reconciliation (not implemented yet).

    Returns ``{"status": "not_implemented"}`` so callers, logs and any task
    history never mistake this placeholder for a successful backup sync.
    """
    logger.info(
        "sync_beat_schedules: backup scheduling is not implemented; "
        "no schedules were synchronized.")
    return {
        "status": "not_implemented",
        "synced": 0,
        "detail": "placeholder; no backup models configured yet",
    }
