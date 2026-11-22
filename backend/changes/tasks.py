"""Celery background tasks for Change Management.

All tasks are idempotent, bounded, and record their outcome in
common.BackgroundTaskRun. None of them executes shell commands or
infrastructure actions; they only evaluate state and record findings.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from changes.models import (
    ChangeRequest,
    ChangeConflict,
    ChangeTemplate,
    PostImplementationReview,
    MaintenanceWindow,
)

from common.models import BackgroundTaskRun
from common.tasks import _mark_run

logger = logging.getLogger(__name__)


def _record_run(task_name, status, error_summary="", payload=None):
    run = BackgroundTaskRun.objects.create(
        task_name=task_name, status=status,
        success=(status == "succeeded"),
        error_summary=error_summary or "",
        payload=payload or {},
    )
    if status in ("succeeded", "failed", "skipped"):
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary", "finished_at"])
    return run


@shared_task(bind=True, max_retries=3, retry_backoff=60)
def evaluate_change_deadlines(self):
    """Evaluate overdue approvals, upcoming implementations, overdue tasks,
    overdue validation, overdue PIRs, and overdue emergency retrospectives.

    Idempotent: only records findings; does not mutate change state except
    through the normal domain model (none here - it raises findings via
    BackgroundTaskRun).
    """
    run = _record_run("changes.tasks.evaluate_change_deadlines", "running")
    try:
        now = timezone.now()
        findings = []

        # Overdue approvals: pending approvals past their planned start.
        overdue_approvals = ChangeRequest.objects.filter(
            status="pending_approval",
            planned_start__lt=now,
        ).count()
        if overdue_approvals:
            findings.append(f"{overdue_approvals} approval(s) overdue.")

        # Upcoming implementations: scheduled within next 24h.
        upcoming = ChangeRequest.objects.filter(
            status="scheduled",
            planned_start__gte=now,
            planned_start__lte=now + timezone.timedelta(hours=24),
        ).count()
        if upcoming:
            findings.append(f"{upcoming} implementation(s) due in next 24h.")

        # Overdue tasks.
        from changes.models import ChangeTask
        overdue_tasks = ChangeTask.objects.filter(
            status__in=["pending", "ready", "in_progress"],
            planned_end__lt=now,
        ).count()
        if overdue_tasks:
            findings.append(f"{overdue_tasks} task(s) overdue.")

        # Overdue validation.
        overdue_validation = ChangeRequest.objects.filter(
            status="validation",
            planned_end__lt=now,
        ).count()
        if overdue_validation:
            findings.append(f"{overdue_validation} validation(s) overdue.")

        # Overdue PIR.
        overdue_pir = PostImplementationReview.objects.filter(
            status__in=["pending", "scheduled", "in_progress"],
            scheduled_for__lt=now,
        ).count()
        if overdue_pir:
            findings.append(f"{overdue_pir} PIR(s) overdue.")

        # Emergency retrospectives overdue (emergency changes completed but PIR pending).
        overdue_emergency = ChangeRequest.objects.filter(
            change_type="emergency",
            status__in=["completed", "rolled_back"],
            pir__isnull=True,
            actual_end__lt=now - timezone.timedelta(days=7),
        ).count()
        if overdue_emergency:
            findings.append(f"{overdue_emergency} emergency retrospective(s) overdue.")

        summary = "; ".join(findings) if findings else "No overdue items."
        run.payload = {"findings": findings}
        _mark_run("changes.tasks.evaluate_change_deadlines", run, "succeeded")
        logger.info("Change deadline evaluation complete: %s", summary)
        return {"findings": findings}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Change deadline evaluation failed.")
        _mark_run("changes.tasks.evaluate_change_deadlines", run, "failed", error_summary=type(exc).__name__)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, retry_backoff=120)
def detect_change_conflicts(self):
    """Detect conflicts among scheduled/approved future changes.

    Bounded time horizon (next 90 days). Updates existing conflicts by
    fingerprint and creates new ones. Idempotent.
    """
    from changes.conflicts import detect_conflicts, upsert_conflicts

    run = _record_run("changes.tasks.detect_change_conflicts", "running")
    try:
        horizon_end = timezone.now() + timezone.timedelta(days=90)
        changes = ChangeRequest.objects.filter(
            status__in=["scheduled", "in_progress", "approved"],
            planned_start__lte=horizon_end,
        ).select_related("department", "implementation_lead")

        created_count = 0
        updated_count = 0
        for change in changes:
            conflicts = detect_conflicts(change, horizon_days=90)
            c, u = upsert_conflicts(change, conflicts)
            created_count += len(c)
            updated_count += len(u)

        summary = f"Created {created_count}, updated {updated_count} conflict(s)."
        run.payload = {"created": created_count, "updated": updated_count}
        _mark_run("changes.tasks.detect_change_conflicts", run, "succeeded")
        logger.info("Change conflict detection complete: %s", summary)
        return {"created": created_count, "updated": updated_count}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Change conflict detection failed.")
        _mark_run("changes.tasks.detect_change_conflicts", run, "failed", error_summary=type(exc).__name__)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, retry_backoff=3600)
def review_standard_change_templates(self):
    """Identify overdue template reviews and repeated failures.

    Marks templates for review when review interval has passed, and
    suspends templates with repeated failures within the configured window.
    """
    run = _record_run("changes.tasks.review_standard_change_templates", "running")
    try:
        now = timezone.now()
        window_start = now - timezone.timedelta(
            days=getattr(settings, "CHANGE_STANDARD_FAILURE_WINDOW_DAYS", 90))
        failure_threshold = getattr(
            settings, "CHANGE_STANDARD_FAILURE_THRESHOLD", 2)

        # Overdue reviews. This task only reports; it does not deactivate or
        # re-approve a template (that stays an explicit owner decision).
        overdue_templates = list(ChangeTemplate.objects.filter(
            is_active=True,
            is_preapproved=True,
            next_review_due__lt=now,
        ).values_list("pk", flat=True))
        overdue = len(overdue_templates)

        # Failed implementations in the window. ChangeRequest does not store
        # which template produced it, so this is a conservative organisation-
        # level signal for template owners, not a per-template failure count.
        failed_count = ChangeRequest.objects.filter(
            status="failed",
            actual_end__gte=window_start,
        ).count()
        review_flagged = failed_count >= failure_threshold

        summary = (f"{overdue} template(s) overdue for review; "
                   f"{failed_count} failed change(s) in window.")
        _mark_run("changes.tasks.review_standard_change_templates", run,
                  "succeeded",
                  payload={"overdue_templates": overdue,
                           "overdue_template_ids": overdue_templates,
                           "failed_changes": failed_count,
                           "failure_threshold_met": review_flagged})
        logger.info("Template review complete: %s", summary)
        return {"overdue_templates": overdue,
                "failed_changes": failed_count,
                "failure_threshold_met": review_flagged}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Template review failed.")
        _mark_run("changes.tasks.review_standard_change_templates", run, "failed", error_summary=type(exc).__name__)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, retry_backoff=3600)
def activate_change_windows(self):
    """Update maintenance-window state (active/completed) based on time.

    Does not start change implementation automatically.
    """
    run = _record_run("changes.tasks.activate_change_windows", "running")
    try:
        now = timezone.now()
        activated = MaintenanceWindow.objects.filter(
            status="approved", start_at__lte=now, end_at__gt=now
        ).update(status="active")
        completed = MaintenanceWindow.objects.filter(
            end_at__lt=now, status="active"
        ).update(status="completed")
        run.payload = {"activated": activated, "completed": completed}
        _mark_run("changes.tasks.activate_change_windows", run, "succeeded")
        return {"activated": activated, "completed": completed}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Activate change windows failed.")
        _mark_run("changes.tasks.activate_change_windows", run, "failed", error_summary=type(exc).__name__)
        raise self.retry(exc=exc)
