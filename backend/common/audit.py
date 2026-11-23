"""Single helper so every mutation writes a protected AuditLog row.

When :data:`common.settings.AUDIT_INTEGRITY_HASH_ENABLED` is True, each new
row also stores a deterministic SHA-256 ``integrity_hash`` chained from the
most recent AuditLog row, so a periodic integrity check can detect
out-of-band edits. Hash computation is best-effort: any failure there never
prevents the audit row itself from being written."""
from django.conf import settings as django_settings

from common.models import AuditLog
import hashlib


def _integrity_hash(previous_hash, action, entity_type, object_id, object_repr, timestamp, row_id):
    """Deterministic chain hash for one audit row.

    Inputs are the stable, non-editable fields that describe the event plus
    the previous row's hash, so the chain breaks if any earlier row is
    altered.
    """
    canonical = "|".join([
        ""
        if previous_hash is None else previous_hash,
        action,
        entity_type,
        str(object_id),
        str(object_repr)[:255],
        timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") if timestamp else "",
        str(row_id),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:128]


def _latest_audit_row():
    """Most recent audit row by timestamp, tie-broken by id, for chaining.

    Returns ``(hash, timestamp, id)`` or ``(None, None, None)`` when the log
    is empty.
    """
    row = AuditLog.objects.order_by("timestamp", "id").last()
    if row is None:
        return (None, None, None)
    return (getattr(row, "integrity_hash", None), row.timestamp, row.id)


def log_action(*, actor, action, instance, reason="", details=None):
    entity_type = f"{instance._meta.app_label}.{instance._meta.model_name}"
    enabled = getattr(django_settings, "AUDIT_INTEGRITY_HASH_ENABLED", False)
    previous_hash, previous_ts, previous_id = (None, None, None)
    if enabled:
        try:
            previous_hash, previous_ts, previous_id = _latest_audit_row()
        except Exception:
            # Defensive: a failure to read the previous row must not prevent
            # the audit write itself.
            previous_hash = None

    row = AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        entity_type=entity_type,
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        reason=reason or "",
        details=details or {},
    )

    if enabled and getattr(row, "id", None):
        try:
            row.integrity_hash = _integrity_hash(
                previous_hash,
                row.action,
                row.entity_type,
                row.object_id,
                row.object_repr,
                row.timestamp,
                row.id,
            )
            row.save(update_fields=["integrity_hash"])
        except Exception:
            # Non-fatal: the audit event is still recorded; integrity is just
            # not anchored for this row.
            pass

    return row
