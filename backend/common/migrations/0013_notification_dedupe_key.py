"""Add dedupe_key fingerprint + conditional uniqueness to Notification.

Adds a nullable ``dedupe_key`` CharField that stores a deterministic
SHA-256 fingerprint of the notification identity fields
(recipient, title, body, entity_type, object_id).  Rows created through
the dedup-aware ``common.notifications.notify_user()`` path populate it;
direct ``Notification.objects.create()`` callers leave it NULL, which
does not participate in the uniqueness constraint (SQL NULLs are
distinct from one another).

A conditional ``UniqueConstraint`` on ``dedupe_key`` with
``condition=Q(is_deleted=False)`` guarantees that at most one active
(non-soft-deleted) notification exists per dedupe_key, enforced by the
database and therefore safe under concurrent creation.

No data migration is required: existing rows keep NULL dedupe_key and
are unaffected by the constraint.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0012_backgroundtaskrun_correlation_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="dedupe_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Deterministic fingerprint for active-notification deduplication. NULL for rows created outside the dedup-aware path.",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_deleted=False),
                fields=("dedupe_key",),
                name="unique_active_dedupe_key",
            ),
        ),
    ]
