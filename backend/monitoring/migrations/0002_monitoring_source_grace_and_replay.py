from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsource",
            name="previous_secret_valid_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="monitoringingestionattempt",
            name="request_id",
            field=models.CharField(max_length=128),
        ),
        migrations.AddIndex(
            model_name="monitoringingestionattempt",
            index=models.Index(fields=["source", "request_id"], name="ingest_source_request_idx"),
        ),
        migrations.AddConstraint(
            model_name="monitoringingestionattempt",
            constraint=models.UniqueConstraint(fields=["source", "request_id"], name="unique_ingest_request_per_source"),
        ),
    ]
