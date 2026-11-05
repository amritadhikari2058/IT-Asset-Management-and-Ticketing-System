"""Celery Background Tasks for Software Licensing and Renewals.

Implements automated maintenance:
- evaluate_license_deadlines: Proactive expiry and renewal deadline notifications.
- evaluate_license_compliance_task: Scheduled compliance audit, over-allocation detection,
  and automatic transition of expired agreements.
"""

import logging
from typing import Any, Dict

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from common.models import BackgroundTaskRun, Notification
from licensing.models import LicenseAgreement, LicenseComplianceFinding
from licensing.services import evaluate_license_compliance

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def evaluate_license_deadlines(self=None) -> Dict[str, Any]:
    """Daily evaluation of upcoming license renewals, expirations, and notices.

    Transitions active agreements to 'expiring' and notifies contract owners.
    Records operational health in BackgroundTaskRun.
    """
    now = timezone.now()
    today = now.date()
    run = BackgroundTaskRun.objects.create(
        task_name="licensing.tasks.evaluate_license_deadlines",
        status="running",
    )

    expiring_count = 0
    notified_count = 0

    try:
        active_agrs = LicenseAgreement.objects.filter(
            is_deleted=False,
            status="active",
            expiry_date__isnull=False,
        ).select_related("software_product", "owner", "contract_manager")

        for agr in active_agrs:
            notice_days = agr.renewal_notice_days or 30
            notice_threshold = today + timezone.timedelta(days=notice_days)

            # Check if within renewal notice window
            target_date = agr.renewal_date or agr.expiry_date
            if target_date and today >= (target_date - timezone.timedelta(days=notice_days)):
                # Transition status to expiring
                agr.status = "expiring"
                agr.save(update_fields=["status", "updated_at"])
                expiring_count += 1

                # Send notifications to owner and contract manager (prevent duplicates within 7 days)
                recipients = set()
                if agr.owner and agr.owner.is_active:
                    recipients.add(agr.owner)
                if agr.contract_manager and agr.contract_manager.is_active:
                    recipients.add(agr.contract_manager)

                cutoff = now - timezone.timedelta(days=7)
                for rec in recipients:
                    already_notified = Notification.objects.filter(
                        recipient=rec,
                        entity_type="licensing.LicenseAgreement",
                        object_id=str(agr.pk),
                        created_at__gte=cutoff,
                    ).exists()

                    if not already_notified:
                        Notification.objects.create(
                            recipient=rec,
                            title=f"License Renewal Notice: {agr.software_product.name}",
                            body=(
                                f"Agreement {agr.agreement_number} for '{agr.software_product.name}' is approaching "
                                f"renewal/expiry on {agr.expiry_date}. Please review required renewal actions."
                            ),
                            entity_type="licensing.LicenseAgreement",
                            object_id=str(agr.pk),
                        )
                        notified_count += 1

        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.payload = {
            "agreements_expiring_transitioned": expiring_count,
            "notifications_dispatched": notified_count,
        }
        run.save()

        return run.payload

    except Exception as exc:
        logger.exception("evaluate_license_deadlines task failed: %s", exc)
        run.status = "failed"
        run.success = False
        run.finished_at = timezone.now()
        run.error_summary = type(exc).__name__
        run.save()
        if self:
            raise self.retry(exc=exc)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def evaluate_license_compliance_task(self=None) -> Dict[str, Any]:
    """Scheduled compliance engine run.

    Transitions expired agreements when grace period ends and updates findings.
    """
    now = timezone.now()
    today = now.date()
    run = BackgroundTaskRun.objects.create(
        task_name="licensing.tasks.evaluate_license_compliance_task",
        status="running",
    )

    expired_count = 0

    try:
        # 1. Expire agreements past grace period
        candidates = LicenseAgreement.objects.filter(
            is_deleted=False,
            status__in=["active", "expiring"],
            expiry_date__isnull=False,
        )

        for agr in candidates:
            grace_days = agr.grace_period_days or 0
            grace_end = agr.expiry_date + timezone.timedelta(days=grace_days)
            if today > grace_end:
                agr.status = "expired"
                agr.save(update_fields=["status", "updated_at"])
                expired_count += 1

        # 2. Run full compliance engine
        findings = evaluate_license_compliance()

        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.payload = {
            "agreements_expired": expired_count,
            "compliance_findings_processed": len(findings),
        }
        run.save()

        return run.payload

    except Exception as exc:
        logger.exception("evaluate_license_compliance_task failed: %s", exc)
        run.status = "failed"
        run.success = False
        run.finished_at = timezone.now()
        run.error_summary = type(exc).__name__
        run.save()
        if self:
            raise self.retry(exc=exc)
        raise
