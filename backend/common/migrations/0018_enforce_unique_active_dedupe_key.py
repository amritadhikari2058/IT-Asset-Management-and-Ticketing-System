"""Enforce unique_active_dedupe_key conditional unique index.

Migration 0013 (notification_dedupe_key) declares a conditional
``UniqueConstraint`` on ``Notification(dedupe_key) WHERE is_deleted=False``.
On PostgreSQL 18 / Django 6.0 the ``AddConstraint`` operation materializes
this as a partial unique index, but the index may be absent on existing
databases created before migration 0013, or present with a wrong definition.

This migration idempotently ensures the index exists with the correct
definition:

- Unique on ``(dedupe_key)``
- Predicate ``WHERE NOT is_deleted`` (active notifications only)
- Table ``common_notification``

``CREATE UNIQUE INDEX IF NOT EXISTS`` is NOT used alone because it does not
validate that an existing same-named index has the correct definition.  If an
index named ``unique_active_dedupe_key`` exists but with wrong columns or
predicate, this migration drops and recreates it.

NULL ``dedupe_key`` values are distinct from one another in both PostgreSQL
and SQLite unique indexes, so rows created outside the dedup-aware path are
unaffected.

Reversible: drops the index on rollback.
"""

from django.db import migrations, connection, models


def _index_exists(schema_editor, table, index_name):
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                """
                SELECT 1 FROM pg_indexes
                WHERE tablename = %s AND indexname = %s
                """,
                [table, index_name],
            )
        elif vendor == "sqlite":
            cursor.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'index' AND tbl_name = %s AND name = %s
                """,
                [table, index_name],
            )
        else:
            cursor.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'index' AND tbl_name = %s AND name = %s
                """,
                [table, index_name],
            )
        return cursor.fetchone() is not None


def _index_definition(schema_editor, table, index_name):
    """Return (is_unique, columns, predicate) or None."""
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                """
                SELECT indexdef FROM pg_indexes
                WHERE tablename = %s AND indexname = %s
                """,
                [table, index_name],
            )
            row = cursor.fetchone()
            if not row:
                return None
            indexdef = row[0]
            is_unique = "UNIQUE" in indexdef.upper()
            columns_match = "dedupe_key" in indexdef
            predicate_match = "NOT is_deleted" in indexdef.upper()
            return (is_unique, columns_match, predicate_match)
        elif vendor == "sqlite":
            cursor.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'index' AND tbl_name = %s AND name = %s
                """,
                [table, index_name],
            )
            row = cursor.fetchone()
            if not row:
                return None
            sql = row[0]
            is_unique = "UNIQUE" in sql.upper()
            columns_match = "dedupe_key" in sql
            predicate_match = "NOT is_deleted" in sql.upper()
            return (is_unique, columns_match, predicate_match)
        return None


def _find_duplicate_active_dedupe_keys(schema_editor):
    """Return list of dedupe_key values that have more than one active row."""
    from common.models import Notification
    duplicates = (
        Notification.objects.filter(is_deleted=False)
        .exclude(dedupe_key__isnull=True)
        .values("dedupe_key")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    return list(duplicates)


def enforce_dedupe_index(apps, schema_editor):
    table = "common_notification"
    index_name = "unique_active_dedupe_key"

    # Check for duplicate data that would prevent index creation.
    duplicates = _find_duplicate_active_dedupe_keys(schema_editor)
    if duplicates:
        keys = [d["dedupe_key"] for d in duplicates]
        raise RuntimeError(
            "Cannot create unique_active_dedupe_key: duplicate active "
            f"dedupe_key values exist: {keys}.  Resolve duplicates before "
            "applying this migration."
        )

    if _index_exists(schema_editor, table, index_name):
        definition = _index_definition(schema_editor, table, index_name)
        if definition and all(definition):
            # Index exists with correct definition; nothing to do.
            return
        # Index exists with wrong definition; drop and recreate.
        schema_editor.execute(
            f'DROP INDEX IF EXISTS "{index_name}"'
        )

    # Create the index.
    vendor = connection.vendor
    if vendor == "postgresql":
        sql = (
            f'CREATE UNIQUE INDEX "{index_name}" '
            f'ON "{table}" ("dedupe_key") WHERE NOT "is_deleted"'
        )
    else:
        sql = (
            f'CREATE UNIQUE INDEX "{index_name}" '
            f'ON "{table}" ("dedupe_key") WHERE NOT "is_deleted"'
        )
    schema_editor.execute(sql)


def drop_dedupe_index(apps, schema_editor):
    index_name = "unique_active_dedupe_key"
    schema_editor.execute(f'DROP INDEX IF EXISTS "{index_name}"')


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0017_scheduledreportrun_execution_token_and_more"),
    ]

    operations = [
        migrations.RunPython(
            enforce_dedupe_index,
            reverse_code=drop_dedupe_index,
        ),
    ]
