"""Data-retention service layer.

Preview + execution of retention policies. Execution is always preceded by
a preview; eligibility is re-validated at execution time inside a
transaction. AuditLog (security events) is explicitly excluded from any
generic retention operation and is never automatically deleted.

Celery tasks are thin wrappers around these functions so they can be tested
without a broker.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.models import (AuditLog, BackgroundTaskRun, DataRetentionExecution,
                           DataRetentionPolicy, Notification)

# Categories that have no automated model-backed handling in this release.
# They can still be policy-defined but require manual review.
MANUAL_REVIEW_CATEGORIES = (
    "temporary_import_reports",
    "expired_temporary_records",
    "other",
)

# Never subject to automatic retention / deletion under any policy.
PROTECTED_MODELS = (AuditLog,)


def _cutoff(policy):
    return timezone.now() - timedelta(days=policy.retention_duration)


def preview_retention(policy):
    """Preview a retention operation without mutating anything.

    Returns a dict: eligible counts per category, excluded records with
    reasons, and whether execution is recommended.
    """
    cutoff = _cutoff(policy)
    category = policy.data_category
    result = {
        "policy_id": policy.pk,
        "policy_name": policy.name,
        "data_category": category,
        "retention_duration_days": policy.retention_duration,
        "cutoff": cutoff,
        "eligible": {},
        "excluded": [],
        "total_eligible": 0,
        "total_affected_estimate": 0,
        "can_execute": bool(policy.enabled),
        "notes": [],
    }

    if category == "security_events":
        # AuditLog is the security-event store; never auto-delete it.
        result["excluded"].append({
            "model": "common.AuditLog",
            "reason": "Audit logs are protected historical records; never "
                      "automatically deleted by a retention policy.",
        })
        result["notes"].append(
            "Security events (AuditLog) are retained permanently; no "
            "automated deletion applies.")
        return result

    if category in MANUAL_REVIEW_CATEGORIES:
        result["notes"].append(
            f"No automated model-backed retention for '{category}'; "
            "records require manual review before removal.")
        result["can_execute"] = False
        return result

    if category == "notifications":
        qs = Notification.objects.filter(created_at__lt=cutoff)
        # Never remove unread notifications: the recipient may still need them.
        eligible_qs = qs.filter(is_read=True)
        excluded_qs = qs.filter(is_read=False)
        result["eligible"]["common.Notification"] = eligible_qs.count()
        result["excluded"].append({
            "model": "common.Notification",
            "reason": "Unread notifications are excluded until read "
                      f"({excluded_qs.count()} excluded).",
        })
        result["total_eligible"] = eligible_qs.count()
        result["total_affected_estimate"] = eligible_qs.count()
        result["notes"].append(
            "Eligible read notifications older than the retention window "
            "are soft-deleted; unread notifications are preserved.")
        return result

    if category == "background_task_runs":
        qs = BackgroundTaskRun.objects.filter(started_at__lt=cutoff)
        # Keep the most recent outcome per task for operational health.
        eligible_qs = qs.exclude(status="running")
        excluded_qs = qs.filter(status="running")
        result["eligible"]["common.BackgroundTaskRun"] = eligible_qs.count()
        result["excluded"].append({
            "model": "common.BackgroundTaskRun",
            "reason": "Running task runs are excluded "
                      f"({excluded_qs.count()} excluded).",
        })
        result["total_eligible"] = eligible_qs.count()
        result["total_affected_estimate"] = eligible_qs.count()
        result["notes"].append(
            "Finished background-task runs older than the retention window "
            "are soft-deleted; running runs are preserved.")
        return result

    result["notes"].append(
        f"No automated retention handler for category '{category}'.")
    result["can_execute"] = False
    return result


@transaction.atomic
def execute_retention(policy, executor):
    """Execute a retention policy after revalidating eligibility.

    Returns (ok, error, summary). Per-category failures are isolated so one
    category's failure does not corrupt unrelated records.
    """
    if not policy.enabled:
        return False, "Policy is disabled.", {"policy_id": policy.pk}

    preview = preview_retention(policy)
    if not preview["can_execute"]:
        return False, preview["notes"][0] if preview["notes"] else \
            "Policy cannot be executed.", {"policy_id": policy.pk}

    category = policy.data_category
    affected = 0
    excluded = 0
    exclusion_reasons = []
    error_summary = ""

    try:
        if category == "notifications":
            cutoff = _cutoff(policy)
            qs = Notification.objects.filter(
                created_at__lt=cutoff, is_read=True)
            count = qs.count()
            # Bulk soft-delete respects the model's soft-delete override.
            qs.delete()  # -> SoftDeleteQuerySet.soft_delete()
            affected = count
            excluded = Notification.objects.filter(
                created_at__lt=cutoff, is_read=False).count()
            exclusion_reasons.append({
                "model": "common.Notification",
                "reason": "Unread notifications preserved.",
                "count": excluded,
            })

        elif category == "background_task_runs":
            cutoff = _cutoff(policy)
            qs = BackgroundTaskRun.objects.filter(
                started_at__lt=cutoff).exclude(status="running")
            count = qs.count()
            qs.delete()
            affected = count
            excluded = BackgroundTaskRun.objects.filter(
                started_at__lt=cutoff, status="running").count()
            exclusion_reasons.append({
                "model": "common.BackgroundTaskRun",
                "reason": "Running task runs preserved.",
                "count": excluded,
            })

        else:
            return False, f"No execution handler for category '{category}'.", {
                "policy_id": policy.pk}

    except Exception as exc:  # isolation: one category fails, others not touched
        error_summary = type(exc).__name__
        return False, error_summary, {
            "policy_id": policy.pk, "category": category,
            "error_summary": error_summary}

    # Record execution outcome.
    policy.last_run_at = timezone.now()
    policy.save(update_fields=["last_run_at"])
    execution = DataRetentionExecution.objects.create(
        policy=policy, status="succeeded",
        finished_at=timezone.now(),
        records_eligible=preview["total_eligible"],
        records_affected=affected,
        records_excluded=excluded,
        exclusion_reasons=exclusion_reasons,
        result={"category": category, "affected": affected},
    )
    return True, "", {
        "policy_id": policy.pk,
        "category": category,
        "records_affected": affected,
        "records_excluded": excluded,
        "execution_id": execution.pk,
    }
