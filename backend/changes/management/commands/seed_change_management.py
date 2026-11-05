"""Seed change management standard templates and maintenance windows.

Usage (safe, read-only preview by default):

    python manage.py seed_change_management --dry-run

Create standard templates:

    python manage.py seed_change_management --create --include-standard-templates

Update existing templates to match seeded definitions:

    python manage.py seed_change_management --create --update-existing

Scope to a department:

    python manage.py seed_change_management --create --department-code ENG

Options:
    --dry-run             Report what would be done without writing.
    --create              Actually create/update templates.
    --include-risk-defaults Include default risk assessment factors.
    --include-maintenance-windows Seed default maintenance windows.
    --department-code     Limit seeding to templates for this department code.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Department
from changes.models import ChangeTemplate, MaintenanceWindow

DEFAULT_TEMPLATES = [
    {
        "code": "CHG-STD-001",
        "name": "Planned server restart",
        "category": "infrastructure",
        "default_priority": "normal",
        "default_risk_level": "low",
        "scope": "Restart a single production server during maintenance window.",
        "out_of_scope": "Application code changes, database migrations.",
        "implementation_plan": "1. Notify stakeholders.\n2. Take backup.\n3. Restart server.\n4. Verify service health.",
        "validation_plan": "Confirm service responds to health checks after restart.",
        "rollback_plan": "Revert to previous server state using backup.",
        "communication_plan": "Notify affected department 24h in advance.",
        "expected_duration_minutes": 60,
        "maximum_downtime_minutes": 30,
        "required_roles": ["it_support"],
        "required_task_definitions": [
            {"title": "Notify stakeholders", "task_type": "communication", "required": True},
            {"title": "Take backup", "task_type": "backup", "required": True, "evidence_required": True},
            {"title": "Restart server", "task_type": "implementation", "required": True},
            {"title": "Verify health", "task_type": "validation", "required": True},
        ],
        "affected_service_rules": [],
        "approval_policy": {"auto_approve": True},
        "is_preapproved": True,
        "is_active": True,
        "review_interval_days": 90,
    },
    {
        "code": "CHG-STD-002",
        "name": "Routine security patch",
        "category": "security",
        "default_priority": "normal",
        "default_risk_level": "medium",
        "scope": "Apply vendor security patch to operating system.",
        "out_of_scope": "Application-level changes, firmware updates.",
        "implementation_plan": "1. Download patch from vendor.\n2. Test in staging.\n3. Apply during window.\n4. Reboot and verify.",
        "validation_plan": "Confirm patch version installed and service operational.",
        "rollback_plan": "Uninstall patch and reboot.",
        "communication_plan": "Post-implementation notice to stakeholders.",
        "expected_duration_minutes": 120,
        "maximum_downtime_minutes": 45,
        "required_roles": ["it_support", "it_manager"],
        "required_task_definitions": [
            {"title": "Download patch", "task_type": "implementation", "required": True},
            {"title": "Staging test", "task_type": "testing", "required": True, "evidence_required": True},
            {"title": "Apply patch", "task_type": "implementation", "required": True},
            {"title": "Verify and reboot", "task_type": "validation", "required": True},
        ],
        "affected_service_rules": [],
        "approval_policy": {"manager_approve": True},
        "is_preapproved": False,
        "is_active": True,
        "review_interval_days": 90,
    },
    {
        "code": "CHG-STD-003",
        "name": "Approved workstation software update",
        "category": "software",
        "default_priority": "low",
        "default_risk_level": "low",
        "scope": "Deploy approved software update to workstations via management console.",
        "out_of_scope": "New software installations, license changes.",
        "implementation_plan": "1. Push update via management console.\n2. Verify installation on sample workstations.\n3. Full rollout.",
        "validation_plan": "Confirm update version on sampled workstations.",
        "rollback_plan": "Uninstall update via management console.",
        "communication_plan": "Notify end users of update window.",
        "expected_duration_minutes": 180,
        "maximum_downtime_minutes": 15,
        "required_roles": ["it_support"],
        "required_task_definitions": [
            {"title": "Push update", "task_type": "implementation", "required": True},
            {"title": "Sample verification", "task_type": "testing", "required": True, "evidence_required": True},
            {"title": "Full rollout", "task_type": "implementation", "required": True},
        ],
        "affected_service_rules": [],
        "approval_policy": {"auto_approve": True},
        "is_preapproved": True,
        "is_active": True,
        "review_interval_days": 180,
    },
    {
        "code": "CHG-STD-004",
        "name": "Network switch configuration backup",
        "category": "network",
        "default_priority": "normal",
        "default_risk_level": "low",
        "scope": "Backup configuration of network switches.",
        "out_of_scope": "Configuration changes, firmware updates.",
        "implementation_plan": "1. Export running config.\n2. Store in backup repository.\n3. Verify backup integrity.",
        "validation_plan": "Confirm backup file exists and is non-empty.",
        "rollback_plan": "Not applicable (read-only operation).",
        "communication_plan": "None required.",
        "expected_duration_minutes": 30,
        "maximum_downtime_minutes": 0,
        "required_roles": ["it_support"],
        "required_task_definitions": [
            {"title": "Export config", "task_type": "backup", "required": True, "evidence_required": True},
            {"title": "Store backup", "task_type": "documentation", "required": True},
            {"title": "Verify integrity", "task_type": "validation", "required": True},
        ],
        "affected_service_rules": [],
        "approval_policy": {"auto_approve": True},
        "is_preapproved": True,
        "is_active": True,
        "review_interval_days": 180,
    },
    {
        "code": "CHG-STD-005",
        "name": "Scheduled certificate renewal",
        "category": "security",
        "default_priority": "normal",
        "default_risk_level": "medium",
        "scope": "Renew expiring TLS certificate for internal service.",
        "out_of_scope": "New certificate purchases, domain changes.",
        "implementation_plan": "1. Generate CSR.\n2. Obtain signed certificate.\n3. Install and restart service.\n4. Verify HTTPS.",
        "validation_plan": "Confirm certificate validity via HTTPS check.",
        "rollback_plan": "Revert to previous certificate.",
        "communication_plan": "Notify service owners before renewal.",
        "expected_duration_minutes": 90,
        "maximum_downtime_minutes": 10,
        "required_roles": ["it_support"],
        "required_task_definitions": [
            {"title": "Generate CSR", "task_type": "implementation", "required": True},
            {"title": "Obtain certificate", "task_type": "implementation", "required": True},
            {"title": "Install and verify", "task_type": "validation", "required": True},
        ],
        "affected_service_rules": [],
        "approval_policy": {"auto_approve": True},
        "is_preapproved": True,
        "is_active": True,
        "review_interval_days": 365,
    },
    {
        "code": "CHG-STD-006",
        "name": "Routine antivirus policy update",
        "category": "security",
        "default_priority": "low",
        "default_risk_level": "low",
        "scope": "Push updated antivirus definitions to endpoints.",
        "out_of_scope": "Engine upgrades, policy rule changes.",
        "implementation_plan": "1. Sync definitions from vendor.\n2. Push to endpoints.\n3. Verify definition version.",
        "validation_plan": "Confirm definition version on sampled endpoints.",
        "rollback_plan": "Roll back to previous definition version.",
        "communication_plan": "None required.",
        "expected_duration_minutes": 45,
        "maximum_downtime_minutes": 0,
        "required_roles": ["it_support"],
        "required_task_definitions": [
            {"title": "Sync definitions", "task_type": "implementation", "required": True},
            {"title": "Push to endpoints", "task_type": "implementation", "required": True},
            {"title": "Verify version", "task_type": "validation", "required": True},
        ],
        "affected_service_rules": [],
        "approval_policy": {"auto_approve": True},
        "is_preapproved": True,
        "is_active": True,
        "review_interval_days": 180,
    },
]


def _now():
    from django.utils import timezone
    return timezone.now()


def seed_templates(update_existing=False, department_code=None):
    created = 0
    updated = 0
    skipped = 0
    for tpl in DEFAULT_TEMPLATES:
        if department_code:
            # Department scoping is informational; templates are org-wide.
            pass
        obj, was_created = ChangeTemplate.objects.update_or_create(
            code=tpl["code"],
            defaults={
                "name": tpl["name"],
                "title_template": tpl["name"],
                "description_template": tpl.get("description_template", ""),
                "category": tpl["category"],
                "default_priority": tpl["default_priority"],
                "default_risk_level": tpl["default_risk_level"],
                "scope": tpl["scope"],
                "implementation_plan": tpl["implementation_plan"],
                "validation_plan": tpl["validation_plan"],
                "rollback_plan": tpl["rollback_plan"],
                "communication_plan": tpl["communication_plan"],
                "expected_duration_minutes": tpl["expected_duration_minutes"],
                "maximum_downtime_minutes": tpl["maximum_downtime_minutes"],
                "required_roles": tpl["required_roles"],
                "required_task_definitions": tpl["required_task_definitions"],
                "affected_service_rules": tpl["affected_service_rules"],
                "approval_policy": tpl["approval_policy"],
                "is_preapproved": tpl["is_preapproved"],
                "is_active": tpl["is_active"],
                "review_interval_days": tpl["review_interval_days"],
            },
        )
        if was_created:
            created += 1
        elif update_existing:
            updated += 1
        else:
            skipped += 1
    return created, updated, skipped


def seed_maintenance_windows(update_existing=False):
    created = 0
    updated = 0
    now = _now()
    windows = [
        {
            "code": "MW-WEEKEND-001",
            "name": "Weekend maintenance window",
            "description": "Standard weekend maintenance window for infrastructure changes.",
            "window_type": "recurring",
            "start_at": now.replace(hour=2, minute=0, second=0, microsecond=0),
            "end_at": now.replace(hour=6, minute=0, second=0, microsecond=0),
            "timezone_name": "UTC",
            "recurrence_rule": "weekly Saturday 02:00-06:00",
            "status": "approved",
            "maximum_parallel_changes": 3,
            "blackout": False,
        },
    ]
    for w in windows:
        obj, was_created = MaintenanceWindow.objects.update_or_create(
            code=w["code"],
            defaults={
                "name": w["name"],
                "description": w["description"],
                "window_type": w["window_type"],
                "start_at": w["start_at"],
                "end_at": w["end_at"],
                "timezone_name": w["timezone_name"],
                "recurrence_rule": w["recurrence_rule"],
                "status": w["status"],
                "maximum_parallel_changes": w["maximum_parallel_changes"],
                "blackout": w["blackout"],
            },
        )
        if was_created:
            created += 1
        elif update_existing:
            updated += 1
    return created, updated


class Command(BaseCommand):
    help = "Seed change management standard templates and maintenance windows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without writing.",
        )
        parser.add_argument(
            "--create",
            action="store_true",
            help="Actually create/update templates.",
        )
        parser.add_argument(
            "--include-risk-defaults",
            action="store_true",
            help="Include default risk assessment factors (informational).",
        )
        parser.add_argument(
            "--include-maintenance-windows",
            action="store_true",
            help="Seed default maintenance windows.",
        )
        parser.add_argument(
            "--department-code",
            default=None,
            help="Limit seeding to templates for this department code (informational).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        create = options["create"]
        dept_code = options["department_code"]

        if dept_code:
            try:
                Department.objects.get(code=dept_code)
            except Department.DoesNotExist:
                raise CommandError(f"Department code '{dept_code}' not found.")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY-RUN: no changes will be written.\n"
                    f"Would create {len(DEFAULT_TEMPLATES)} template(s)."
                )
            )
            if options["include_maintenance_windows"]:
                self.stdout.write("Would create 1 maintenance window.")
            return

        if not create:
            raise CommandError(
                "Specify --create to apply changes, or --dry-run to preview."
            )

        with transaction.atomic():
            created, updated, skipped = seed_templates(
                update_existing=options["update_existing"],
                department_code=dept_code,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Templates: {created} created, {updated} updated, {skipped} skipped."
                )
            )
            if options["include_maintenance_windows"]:
                wc, wu = seed_maintenance_windows(update_existing=options["update_existing"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Maintenance windows: {wc} created, {wu} updated."
                    )
                )
