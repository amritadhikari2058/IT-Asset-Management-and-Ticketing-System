"""Prevent two concurrent 'running' ScheduledReportRun rows per report.

The report scanner (``common.tasks.run_scheduled_reports``) previously
picked up due scheduled reports without row locking, so two workers could
both start a ``running`` run for the same report and double-deliver it.
A partial unique constraint on ``(scheduled_report)`` where
``status = 'running'`` makes the database itself serialize execution: only
one running run can exist per scheduled report at a time.

Existing duplicate running runs (from before this constraint) are resolved
by keeping the most recent one and marking the rest skipped, so the
constraint can be added cleanly against real data.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def remove_duplicate_running_runs(apps, schema_editor):
    ScheduledReportRun = apps.get_model("common", "ScheduledReportRun")
    report_ids = (
        ScheduledReportRun.objects.filter(status="running")
        .values_list("scheduled_report", flat=True)
        .distinct()
    )
    for report_id in report_ids:
        runs = list(
            ScheduledReportRun.objects.filter(
                scheduled_report_id=report_id, status="running"
            ).order_by("-started_at", "-pk")
        )
        # Keep the most recent running run; mark the rest skipped so they
        # can never be mistaken for an in-flight delivery.
        for run in runs[1:]:
            run.status = "skipped"
            run.success = False
            if not run.finished_at:
                run.finished_at = run.started_at or timezone.now()
            run.save(
                update_fields=["status", "success", "finished_at"]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0015_notificationoutboxevent"),
    ]

    operations = [
        migrations.RunPython(
            remove_duplicate_running_runs,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="scheduledreportrun",
            constraint=models.UniqueConstraint(
                fields=["scheduled_report"],
                condition=models.Q(status="running"),
                name="unique_running_run_per_scheduled_report",
            ),
        ),
    ]
