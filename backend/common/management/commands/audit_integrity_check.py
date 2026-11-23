"""Audit-log integrity check management command.

Recomputes the deterministic SHA-256 chain hash for every AuditLog row and
reports any row whose stored ``integrity_hash`` does not match the recomputed
value. This detects out-of-band edits to the audit log when integrity chaining
is enabled (see ``backend/config/settings.py``,
``AUDIT_INTEGRITY_HASH_ENABLED``, and ``common/audit.py``).

The check is safe and read-only: it never writes, deletes, or otherwise
modifies audit rows. It does not require the integrity-hashing feature to be
enabled — for rows without a stored hash it simply reports them as unsealed.

Usage::

    python manage.py audit_integrity_check
    python manage.py audit_integrity_check -- repairing is intentionally not
    provided by this command; repair, if ever needed, should be a controlled
    DBA/ops action, not an automated one.
"""
from django.core.management.base import BaseCommand

from common.models import AuditLog


def _integrity_hash(previous_hash, action, entity_type, object_id, object_repr, timestamp, row_id):
    """Replicate the chain hash used when integrity hashing is enabled."""
    canonical = "|".join([
        "" if previous_hash is None else previous_hash,
        action,
        entity_type,
        str(object_id),
        str(object_repr)[:255],
        timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") if timestamp else "",
        str(row_id),
    ])
    import hashlib
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:128]


class Command(BaseCommand):
    help = (
        "Check the integrity chain of the protected AuditLog. Read-only; reports "
        "any row whose stored integrity_hash does not match the recomputed value."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after inspecting this many rows (useful for a quick probe).",
        )

    def handle(self, *args, **options):
        if AuditLog.objects.count() == 0:
            self.stdout.write(self.style.SUCCESS("AuditLog is empty. Nothing to check."))
            return

        limit = options["limit"]
        rows = AuditLog.objects.order_by("timestamp", "id")
        if limit:
            rows = rows[:limit]

        total = 0
        unsealed = 0
        mismatch = 0
        error = 0

        previous_hash = None
        for row in rows:
            total += 1
            stored = getattr(row, "integrity_hash", None) or ""
            if not stored:
                unsealed += 1
                previous_hash = None
                continue

            try:
                expected = _integrity_hash(
                    previous_hash,
                    row.action,
                    row.entity_type,
                    row.object_id,
                    row.object_repr,
                    row.timestamp,
                    row.id,
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.stderr.write(
                    self.style.ERROR(f"Row {row.id}: could not recompute hash: {exc}")
                )
                error += 1
                previous_hash = None
                continue

            if expected != stored:
                mismatch += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"MISMATCH row={row.id} action={row.action} "
                        f"entity={row.entity_type}:{row.object_id} "
                        f"stored={stored[:16]}... expected={expected[:16]}..."
                    )
                )

            previous_hash = stored

        self.stdout.write("")
        self.stdout.write(f"Inspected: {total}")
        self.stdout.write(f"Unsealed (no stored hash): {unsealed}")
        self.stdout.write(f"Integrity mismatches: {mismatch}")
        self.stdout.write(f"Hash-recompute errors: {error}")

        if mismatch:
            self.stdout.write(
                self.style.ERROR(
                    "The audit log integrity chain is broken. Investigate rows above "
                    "before relying on the log for accountability."
                )
            )
        elif unsealed and not mismatch:
            self.stdout.write(
                self.style.WARNING(
                    "The audit log is internally consistent for sealed rows, but some "
                    "rows have no integrity hash. Enable AUDIT_INTEGRITY_HASH_ENABLED to "
                    "anchor new rows; legacy rows can be resealed as a controlled ops task."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Audit log integrity chain is internally consistent for all inspected rows."
                )
            )
