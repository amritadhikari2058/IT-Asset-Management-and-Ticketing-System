"""Add asset/assignment integrity CHECK constraints without touching data.

Policy (identical to assets.0003)
--------------------------------
- Existing rows are NEVER deleted, rewritten or "fixed" by this migration.
  Inconsistent legacy rows are REPORTED during ``migrate`` so the decision
  about them stays a human one (see also ``GET /api/common/data-integrity/``).
- Each CHECK constraint is only added to the database when every existing row
  already satisfies it. When legacy violations exist the constraint is skipped
  with a printed report, while the SAME rule stays enforced for every new write
  by ``Asset.clean()`` / ``Assignment.clean()`` (called from ``save()``), by the
  DRF serializers and by the bulk endpoints.

Rules covered
-------------
1. ``asset_assigned_requires_holder``  - status="assigned" needs a holder.
2. ``asset_ineligible_no_holder``      - retired/lost assets keep no holder.
3. ``assignment_open_requires_holder`` - an open assignment needs a holder.
"""
from django.db import migrations, models


CONSTRAINTS = [
    ("Asset", models.CheckConstraint(
        name="asset_assigned_requires_holder",
        condition=(
            ~models.Q(status="assigned")
            | models.Q(assigned_to__isnull=False)
        ),
    )),
    ("Asset", models.CheckConstraint(
        name="asset_ineligible_no_holder",
        condition=(
            ~models.Q(status__in=["retired", "lost"])
            | models.Q(assigned_to__isnull=True)
        ),
    )),
    ("Assignment", models.CheckConstraint(
        name="assignment_open_requires_holder",
        condition=(
            models.Q(returned_at__isnull=False)
            | models.Q(assigned_to__isnull=False)
        ),
    )),
]

RULE_LABELS = {
    "asset_assigned_requires_holder":
        "asset(s) with status 'assigned' but no holder",
    "asset_ineligible_no_holder":
        "retired/lost asset(s) that still have a holder",
    "assignment_open_requires_holder":
        "open assignment(s) without a holder",
}


def _violations(model, constraint):
    """Rows that would fail this CHECK, evaluated read-only."""
    if constraint.name == "asset_assigned_requires_holder":
        qs = model.objects.filter(status="assigned", assigned_to__isnull=True)
        return [(o.pk, o.asset_tag, o.status) for o in qs[:50]]
    if constraint.name == "asset_ineligible_no_holder":
        qs = model.objects.filter(
            status__in=["retired", "lost"], assigned_to__isnull=False)
        return [(o.pk, o.asset_tag, o.status) for o in qs[:50]]
    if constraint.name == "assignment_open_requires_holder":
        qs = model.objects.filter(returned_at__isnull=True,
                                  assigned_to__isnull=True)
        return [(o.pk, f"asset #{o.asset_id}", "open") for o in qs[:50]]
    return []


def report_all_rules(apps, schema_editor):
    """Print every pre-existing inconsistency we know about. READ-ONLY."""
    Asset = apps.get_model("assets", "Asset")
    User = apps.get_model("accounts", "User")
    from django.db.models import Count

    lines = []

    for model_name, constraint in CONSTRAINTS:
        model = apps.get_model("assets", model_name)
        found = _violations(model, constraint)
        if found:
            lines.append(
                f"{constraint.name}: {RULE_LABELS[constraint.name]} -> "
                + ", ".join(f"#{pk} {label}" for pk, label, _ in found))

    holder_no_open = Asset.objects.filter(
        assigned_to__isnull=False).exclude(assignments__returned_at__isnull=True)
    for a in holder_no_open[:50]:
        lines.append(
            f"assignment_open_orphan: {a.asset_tag} has holder "
            f"user #{a.assigned_to_id} but no open assignment row")
    dup_open = (Asset.objects.filter(assignments__returned_at__isnull=True)
                .values("id").annotate(n=Count("id")).filter(n__gt=1))
    if dup_open:
        lines.append(
            "assignment_duplicate_open: "
            + ", ".join(
                f"asset #{r['id']} has {r['n']} open assignments"
                for r in dup_open[:50]))
    stale = User.objects.filter(
        is_deleted=True, assignments_received__returned_at__isnull=True)
    for u in stale[:50]:
        lines.append(
            f"assignment_to_deleted_user: user {u.employee_id or u.pk} is "
            f"soft-deleted but still holds open assignment(s)")

    if not lines:
        return
    print(
        "assets.0005: WARNING - pre-existing data inconsistencies found. "
        "Reported for manual resolution; no row is deleted or modified by "
        "this migration (see GET /api/common/data-integrity/):")
    for line in lines:
        print(f"assets.0005:   {line}")


class AddConstraintsIfClean(migrations.operations.base.Operation):
    """Add several CHECK constraints, skipping the ones legacy data breaks.

    All constraints declared here are also recorded in the migration state so
    that ``makemigrations --check`` stays clean; only the ones that existing
    rows already satisfy are actually executed against the database (existing
    data is never modified by migrations).
    """

    def __init__(self, constraints):
        self.constraints = list(constraints)

    def state_forwards(self, app_label, state):
        for model_name, constraint in self.constraints:
            state.add_constraint(app_label, model_name.lower(), constraint)

    def database_forwards(self, app_label, schema_editor, from_state,
                          to_state):
        for model_name, constraint in self.constraints:
            model = from_state.apps.get_model(app_label, model_name.lower())
            found = _violations(model, constraint)
            if found:
                print(
                    f"assets.0005: database CHECK {constraint.name} NOT "
                    "added - existing rows violate it and existing data is "
                    "never modified by migrations. The same rule is still "
                    "enforced for every new write by the application:")
                for pk, label, extra in found:
                    print(f"assets.0005:   #{pk} {label} ({extra})")
                continue
            schema_editor.add_constraint(model, constraint)

    def database_backwards(self, app_label, schema_editor, from_state,
                           to_state):
        for model_name, constraint in reversed(self.constraints):
            model = from_state.apps.get_model(app_label, model_name.lower())
            try:
                schema_editor.remove_constraint(model, constraint)
            except Exception:
                # Constraint was never added (skipped because of legacy
                # data); nothing to reverse.
                pass

    def deconstruct(self):
        return (
            "assets.migrations.0005_asset_assignment_integrity."
            "AddConstraintsIfClean",
            {"constraints": [(mn, c) for mn, c in self.constraints]},
            False,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0004_asset_department"),
    ]

    operations = [
        migrations.RunPython(report_all_rules, migrations.RunPython.noop),
        AddConstraintsIfClean(CONSTRAINTS),
        migrations.RunSQL(
            [
                """
                CREATE TRIGGER IF NOT EXISTS assets_asset_serial_unique_insert
                BEFORE INSERT ON assets_asset FOR EACH ROW
                WHEN NEW.serial_number <> ''
                AND EXISTS (
                    SELECT 1 FROM assets_asset other
                    WHERE other.serial_number = NEW.serial_number
                )
                BEGIN
                    SELECT RAISE(ABORT, 'duplicate serial number: serial numbers must be unique across all assets');
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS assets_asset_serial_unique_update
                BEFORE UPDATE OF serial_number ON assets_asset FOR EACH ROW
                WHEN NEW.serial_number <> ''
                AND NEW.serial_number <> OLD.serial_number
                AND EXISTS (
                    SELECT 1 FROM assets_asset other
                    WHERE other.serial_number = NEW.serial_number
                      AND other.id <> NEW.id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'duplicate serial number: serial numbers must be unique across all assets');
                END
                """,
            ],
            [
                "DROP TRIGGER IF EXISTS assets_asset_serial_unique_insert",
                "DROP TRIGGER IF EXISTS assets_asset_serial_unique_update",
            ],
        ),
    ]
