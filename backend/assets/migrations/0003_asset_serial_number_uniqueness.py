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


CREATE_INSERT_TRIGGER = (
    "CREATE TRIGGER assets_asset_serial_unique_insert "
    "BEFORE INSERT ON assets_asset "
    "FOR EACH ROW WHEN NEW.serial_number <> '' AND EXISTS ("
    "  SELECT 1 FROM assets_asset other "
    "  WHERE other.serial_number = NEW.serial_number"
    ") "
    "BEGIN "
    "  SELECT RAISE(ABORT, 'duplicate serial number: serial numbers must "
    "be unique across all assets'); "
    "END"
)

CREATE_UPDATE_TRIGGER = (
    "CREATE TRIGGER assets_asset_serial_unique_update "
    "BEFORE UPDATE OF serial_number ON assets_asset "
    "FOR EACH ROW WHEN NEW.serial_number <> '' "
    "AND NEW.serial_number <> OLD.serial_number AND EXISTS ("
    "  SELECT 1 FROM assets_asset other "
    "  WHERE other.serial_number = NEW.serial_number "
    "    AND other.id <> NEW.id"
    ") "
    "BEGIN "
    "  SELECT RAISE(ABORT, 'duplicate serial number: serial numbers must "
    "be unique across all assets'); "
    "END"
)

DROP_TRIGGERS = [
    "DROP TRIGGER IF EXISTS assets_asset_serial_unique_insert",
    "DROP TRIGGER IF EXISTS assets_asset_serial_unique_update",
]


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0002_assetattachment"),
    ]

    operations = [
        migrations.RunPython(
            report_existing_duplicates, migrations.RunPython.noop),
        migrations.RunSQL(
            [CREATE_INSERT_TRIGGER, CREATE_UPDATE_TRIGGER], DROP_TRIGGERS),
    ]
