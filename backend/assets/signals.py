from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def ensure_asset_serial_uniqueness_triggers(sender, **kwargs):
    if sender.name != "assets":
        return
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(__file__), "migrations", "0003_asset_serial_number_uniqueness.py")
    spec = importlib.util.spec_from_file_location("serial_uniq_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _serial_unique_sql = mod._serial_unique_sql
    from django.db import connection

    vendor = connection.vendor
    if vendor not in ("sqlite", "postgresql"):
        return
    forward, _reverse = _serial_unique_sql(vendor)
    with connection.cursor() as cursor:
        for sql in forward:
            cursor.execute(sql)
