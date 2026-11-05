"""Enforce unique non-blank asset serial numbers without touching data.

Policy
------
- ``serial_number`` stays OPTIONAL: blank/empty values are allowed on any
  number of assets (blank is never subject to uniqueness).
- A non-blank serial number may be used by exactly one asset, INCLUDING
  soft-deleted ones: a recycled asset keeps reserving its serial so a
  recycle-bin restore can never collide with a newer asset.

Why triggers instead of a UNIQUE index
--------------------------------------
The live database already contains assets sharing a serial number (see
the report below, printed during migrate). Existing assets must never be
deleted or rewritten to make a constraint fit, and a UNIQUE index cannot
be created over conflicting rows. BEFORE INSERT / BEFORE UPDATE triggers
enforce the identical rule for every NEW write - including concurrent
requests, ``bulk_create``, and raw ORM ``save()`` calls that bypass
DRF validation - while leaving pre-existing rows untouched and their
other fields editable. Application validation lives in
``assets.serializers.AssetSerializer.validate_serial_number`` and the
bulk endpoints, which produce the friendly field-level messages.

Vendor portability
------------------
SQLite uses ``SELECT RAISE(ABORT, ...)`` triggers. PostgreSQL does not
support that syntax, so this migration creates an equivalent PL/pgSQL
trigger function on PostgreSQL. The database vendor is detected at
migrate time via ``schema_editor.connection.vendor`` so the same
migration file applies cleanly on both SQLite (dev) and PostgreSQL
(production) without editing historical data.
"""
import django.db.models
from django.db import migrations, models


def report_existing_duplicates(apps, schema_editor):
    """Enumerate duplicate serials at migrate time. REPORT ONLY.

    Existing assets are never deleted or modified here (spec): the
    operator is told exactly which rows conflict so the decision about
    them stays a human one. The triggers added by this migration tolerate
    the legacy rows but block any new duplicate from that moment on.
    """
    Asset = apps.get_model("assets", "Asset")
    dups = (
        Asset.objects.exclude(serial_number="")
        .values("serial_number")
        .annotate(n=django.db.models.Count("id"))
        .filter(n__gt=1)
    )
    found = list(dups)
    if not found:
        return
    print(
        "assets.0003: WARNING - duplicate asset serial numbers already "
        "exist. Reported for manual resolution; no asset is deleted or "
        "modified by this migration:"
    )
    for row in found:
        serial = row["serial_number"]
        rows = list(
            Asset.objects.filter(serial_number=serial)
            .order_by("id")
            .values_list("id", "asset_tag", "is_deleted")
        )
        detail = ", ".join(
            f"#{pk} {tag}" + (" (deleted)" if deleted else "")
            for pk, tag, deleted in rows
        )
        print(f"assets.0003:   serial {serial!r} used by {row['n']} assets: {detail}")


def _serial_unique_sql(vendor):
    """Return the (forward_sql, reverse_sql) list for the given vendor."""
    fq_table = "assets_asset"
    col = "serial_number"
    msg = "duplicate serial number: serial numbers must be unique across all assets"

    if vendor == "sqlite":
        forward = [
            "CREATE TRIGGER IF NOT EXISTS assets_asset_serial_unique_insert "
            "BEFORE INSERT ON assets_asset "
            "FOR EACH ROW WHEN NEW.serial_number <> '' AND EXISTS ("
            "  SELECT 1 FROM assets_asset other "
            "  WHERE other.serial_number = NEW.serial_number"
            ") "
            "BEGIN "
            "  SELECT RAISE(ABORT, '%s'); " % msg +
            "END",
            "CREATE TRIGGER IF NOT EXISTS assets_asset_serial_unique_update "
            "BEFORE UPDATE OF serial_number ON assets_asset "
            "FOR EACH ROW WHEN NEW.serial_number <> '' "
            "AND NEW.serial_number <> OLD.serial_number AND EXISTS ("
            "  SELECT 1 FROM assets_asset other "
            "  WHERE other.serial_number = NEW.serial_number "
            "    AND other.id <> NEW.id"
            ") "
            "BEGIN "
            "  SELECT RAISE(ABORT, '%s'); " % msg +
            "END",
        ]
        reverse = [
            "DROP TRIGGER IF EXISTS assets_asset_serial_unique_insert",
            "DROP TRIGGER IF EXISTS assets_asset_serial_unique_update",
        ]
        return forward, reverse

    if vendor == "postgresql":
        forward = [
            # A single PL/pgSQL function serves both INSERT and UPDATE.
            "CREATE OR REPLACE FUNCTION assets_asset_serial_unique_check() "
            "RETURNS trigger AS $$ "
            "BEGIN "
            "  IF NEW.serial_number <> '' AND EXISTS ("
            "    SELECT 1 FROM assets_asset other "
            "    WHERE other.serial_number = NEW.serial_number "
            "      AND other.id <> NEW.id"
            "  ) THEN "
            "    RAISE EXCEPTION '%s' USING ERRCODE = '23505'; " % msg +
            "  END IF; "
            "  RETURN NEW; "
            "END; "
            "$$ LANGUAGE plpgsql",
            "DROP TRIGGER IF EXISTS assets_asset_serial_unique_insert ON assets_asset",
            "DROP TRIGGER IF EXISTS assets_asset_serial_unique_update ON assets_asset",
            "CREATE TRIGGER assets_asset_serial_unique_insert "
            "BEFORE INSERT ON assets_asset "
            "FOR EACH ROW EXECUTE FUNCTION assets_asset_serial_unique_check()",
            "CREATE TRIGGER assets_asset_serial_unique_update "
            "BEFORE UPDATE OF serial_number ON assets_asset "
            "FOR EACH ROW EXECUTE FUNCTION assets_asset_serial_unique_check()",
        ]
        reverse = [
            "DROP TRIGGER IF EXISTS assets_asset_serial_unique_insert ON assets_asset",
            "DROP TRIGGER IF EXISTS assets_asset_serial_unique_update ON assets_asset",
            "DROP FUNCTION IF EXISTS assets_asset_serial_unique_check()",
        ]
        return forward, reverse

    raise NotImplementedError(
        "Asset serial-number uniqueness trigger is not implemented for "
        "database vendor: %r" % vendor)


def create_serial_uniqueness_trigger(apps, schema_editor):
    forward, _reverse = _serial_unique_sql(schema_editor.connection.vendor)
    for sql in forward:
        schema_editor.execute(sql)


def drop_serial_uniqueness_trigger(apps, schema_editor):
    _forward, reverse = _serial_unique_sql(schema_editor.connection.vendor)
    for sql in reverse:
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0002_assetattachment"),
    ]

    operations = [
        migrations.RunPython(
            report_existing_duplicates, migrations.RunPython.noop),
        migrations.RunPython(
            create_serial_uniqueness_trigger, drop_serial_uniqueness_trigger),
    ]
