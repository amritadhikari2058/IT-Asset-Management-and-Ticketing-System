from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0004_monitoringalert_policy_alter_monitoringalert_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringalert",
            name="automation_error_code",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="monitoringalert",
            name="automation_error_summary",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="monitoringalert",
            name="automation_retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="monitoringalert",
            name="automation_last_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="monitoringalert",
            name="automation_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name="monitoringalert",
            constraint=models.UniqueConstraint(
                condition=models.Q(ticket__isnull=False),
                fields=("ticket",),
                name="unique_ticket_per_monitoring_alert",
            ),
        ),
    ]
