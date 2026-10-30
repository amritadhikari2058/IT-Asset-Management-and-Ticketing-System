from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0003_alter_auditlog_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(choices=[("create", "Create"), ("update", "Update"), ("soft_delete", "Soft delete"), ("restore", "Restore"), ("hard_delete", "Permanent delete"), ("bulk_create", "Bulk create"), ("bulk_update", "Bulk update"), ("bulk_soft_delete", "Bulk soft delete"), ("status_change", "Status change"), ("assignment", "Assignment change"), ("deactivate", "Deactivate"), ("reactivate", "Reactivate"), ("retire", "Retire"), ("note", "Note / comment"), ("password_reset", "Password reset"), ("export", "Export")], max_length=32),
        ),
    ]
