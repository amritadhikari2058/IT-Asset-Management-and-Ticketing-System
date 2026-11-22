"""Add ScheduledReportDelivery for durable per-recipient email dedupe.

Provides durable per-recipient delivery tracking so that lease recovery,
worker crashes, or retried Celery tasks cannot unintentionally produce
duplicate scheduled-report emails to the same recipient within the same run.

Reversible: drops the table on rollback. Safe for existing data (new table,
no data migration required).
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0018_enforce_unique_active_dedupe_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduledReportDelivery",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False, db_index=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="%(class)s_deleted",
                    to=settings.AUTH_USER_MODEL)),
                ("deletion_reason", models.TextField(blank=True, default="")),
                ("recipient_email", models.EmailField(max_length=254)),
                ("delivery_dedupe_key", models.CharField(max_length=64,
                                                        unique=True)),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("sent", "Sent"),
                             ("failed", "Failed")],
                    default="pending", max_length=20)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("scheduled_report_run", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="deliveries",
                    to="common.scheduledreportrun")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["scheduled_report_run", "status"],
                        name="schedreport_run_status_idx"),
                    models.Index(
                        fields=["delivery_dedupe_key"],
                        name="schedreport_dedupe_key_idx"),
                ],
            },
        ),
    ]
