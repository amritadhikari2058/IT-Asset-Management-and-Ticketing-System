"""Celery background tasks for CMDB maintenance.

All runs are recorded in common.BackgroundTaskRun using its real schema:
status running/succeeded/failed, success, finished_at, error_summary
(exception type name only) and a non-sensitive payload. Work is bounded
(batch sizes) and idempotent.
"""

import hashlib
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from common.models import BackgroundTaskRun, Notification

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def evaluate_configuration_drift_task(self=None, batch_size=200):
    """Evaluate approved baselines for drift (bounded, idempotent)."""
    from .baselines import evaluate_configuration_drift
    from .models import ConfigurationBaseline

    run = BackgroundTaskRun.objects.create(
        task_name="cmdb.tasks.evaluate_configuration_drift_task",
        status="running",
    )
    try:
        baseline_ids = list(
            ConfigurationBaseline.objects.filter(
                status="approved", is_deleted=False,
            )
            .order_by("-approved_at")
            .values_list("id", flat=True)[:batch_size]
        )
        evaluated_cis = 0
        findings_opened = 0
        for baseline_id in baseline_ids:
            baseline = (
                ConfigurationBaseline.objects.filter(id=baseline_id)
                .select_related("created_by")
                .first()
            )
            if baseline is None:
                continue
            cis = (
                baseline.configuration_items.filter(is_deleted=False)
                .select_related("ci_type")[:batch_size]
            )
            for ci in cis:
                found = evaluate_configuration_drift(ci, baseline=baseline)
                evaluated_cis += 1
                findings_opened += len(
                    [f for f in found if f.status == "open"]
                )

        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.payload = {
            "evaluated_cis": evaluated_cis,
            "findings_opened": findings_opened,
            "baselines": len(baseline_ids),
        }
        run.save()
        return run.payload

    except Exception as exc:
        logger.exception("CMDB drift evaluation failed: %s", exc)
        run.status = "failed"
        run.success = False
        run.finished_at = timezone.now()
        run.error_summary = type(exc).__name__
        run.save()
        if self:
            raise self.retry(exc=exc)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_assets_to_cmdb_task(self=None, batch_size=100, offset=0):
    """Synchronize a bounded batch of assets into the CMDB."""
    from assets.models import Asset

    from .services import sync_asset_to_ci

    run = BackgroundTaskRun.objects.create(
        task_name="cmdb.tasks.sync_assets_to_cmdb_task",
        status="running",
    )
    try:
        assets = (
            Asset.objects.filter(is_deleted=False)
            .order_by("id")[offset:offset + batch_size]
        )
        created = 0
        updated = 0
        skipped = 0
        for asset in assets:
            ci, was_created = sync_asset_to_ci(asset)
            if was_created:
                created += 1
            elif ci is not None:
                updated += 1
            else:
                skipped += 1

        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.payload = {
            "processed": created + updated + skipped,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "batch_size": batch_size,
            "offset": offset,
        }
        run.save()
        return run.payload

    except Exception as exc:
        logger.exception("CMDB asset sync failed: %s", exc)
        run.status = "failed"
        run.success = False
        run.finished_at = timezone.now()
        run.error_summary = type(exc).__name__
        run.save()
        if self:
            raise self.retry(exc=exc)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_ci_verification_age_task(self=None, batch_size=200, notify=True):
    """Flag overdue CIs as unverified drift findings and notify owners.

    Never-verified or stale CIs (older than the verification threshold) get
    a persistent `unverified_ci` finding (idempotent by fingerprint) and a
    deduplicated notification to their owner/technical owner.
    """
    from .impact import (
        VERIFICATION_THRESHOLD_DAYS,
        find_unverified_configuration_items,
    )
    from .models import ConfigurationDriftFinding

    run = BackgroundTaskRun.objects.create(
        task_name="cmdb.tasks.check_ci_verification_age_task",
        status="running",
    )
    try:
        overdue_cis = list(
            find_unverified_configuration_items(
                VERIFICATION_THRESHOLD_DAYS,
            )[:batch_size]
        )
        flagged = 0
        notified = 0
        cutoff = timezone.now() - timedelta(days=7)
        for ci in overdue_cis:
            fingerprint = hashlib.sha256(
                f"{ci.ci_number}|verification|unverified_ci".encode(),
            ).hexdigest()
            finding, created = ConfigurationDriftFinding.objects.get_or_create(
                fingerprint=fingerprint,
                defaults={
                    "configuration_item": ci,
                    "finding_type": "unverified_ci",
                    "severity": "high"
                    if ci.criticality in ("critical", "high") else "medium",
                    "status": "open",
                    "field_name": "last_verified_at",
                    "expected_value": (
                        f"verified within {VERIFICATION_THRESHOLD_DAYS} days"
                    ),
                    "actual_value": (
                        "never verified" if ci.last_verified_at is None
                        else ci.last_verified_at.isoformat()
                    ),
                    "source": "verification_age_task",
                },
            )
            if created:
                flagged += 1
            if notify and created:
                for user in (ci.owner, ci.technical_owner):
                    if not user or not user.is_active:
                        continue
                    already = Notification.objects.filter(
                        recipient=user,
                        entity_type="cmdb.ConfigurationItem",
                        object_id=str(ci.pk),
                        created_at__gte=cutoff,
                    ).exists()
                    if not already:
                        Notification.objects.create(
                            recipient=user,
                            title=f"CMDB verification overdue: {ci.ci_number}",
                            body=(
                                f"{ci.ci_number} ({ci.name}) has not been "
                                f"verified within "
                                f"{VERIFICATION_THRESHOLD_DAYS} days. "
                                f"Please review and verify."
                            ),
                            entity_type="cmdb.ConfigurationItem",
                            object_id=str(ci.pk),
                        )
                        notified += 1

        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.payload = {
            "overdue_cis": len(overdue_cis),
            "flagged": flagged,
            "notifications_sent": notified,
            "threshold_days": VERIFICATION_THRESHOLD_DAYS,
        }
        run.save()
        return run.payload

    except Exception as exc:
        logger.exception("CMDB verification age check failed: %s", exc)
        run.status = "failed"
        run.success = False
        run.finished_at = timezone.now()
        run.error_summary = type(exc).__name__
        run.save()
        if self:
            raise self.retry(exc=exc)
        raise
