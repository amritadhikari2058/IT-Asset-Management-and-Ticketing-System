"""Seed reusable lifecycle templates.

Idempotent: keyed on ``code`` so repeated execution never duplicates.
Default is a dry-run that only reports what would be created/updated.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Department
from lifecycle import models as lm

ONBOARDING_ITEMS = [
    ("Confirm employee account details", "account", "it", "it_support", 0, True, False, "none"),
    ("Confirm department and reporting structure", "account", "manager", "it_manager", 0, True, False, "none"),
    ("Prepare email account", "email", "it", "it_support", 1, True, False, "none"),
    ("Prepare required business-application access", "access", "it", "it_support", 2, True, False, "none"),
    ("Assign laptop or workstation", "hardware", "it", "it_support", 3, True, False, "none"),
    ("Assign accessories", "hardware", "it", "it_support", 4, True, False, "none"),
    ("Configure network or VPN access", "network", "it", "it_support", 5, True, False, "none"),
    ("Apply security baseline", "security", "it", "it_support", 6, True, False, "none"),
    ("Provide IT security induction", "training", "employee", "employee", 7, False, False, "none"),
    ("Confirm first-day readiness", "documentation", "manager", "it_manager", 8, True, False, "none"),
]

OFFBOARDING_ITEMS = [
    ("Confirm effective date", "documentation", "manager", "it_manager", 0, True, False, "none"),
    ("Review assigned Assets", "asset_return", "it", "it_support", 0, True, False, "none"),
    ("Recover laptop or workstation", "asset_return", "it", "it_support", 1, True, False, "none"),
    ("Recover accessories", "asset_return", "it", "it_support", 2, True, False, "none"),
    ("Record lost or damaged equipment", "asset_return", "it", "it_support", 3, True, False, "none"),
    ("Revoke VPN access", "access", "it", "it_support", 4, True, False, "none"),
    ("Revoke business-application access", "access", "it", "it_support", 5, True, False, "none"),
    ("Transfer required files", "data_transfer", "employee", "employee", 6, True, False, "none"),
    ("Revoke active tokens", "security", "it", "it_support", 7, True, False, "revoke_tokens"),
    ("Deactivate account", "account", "it", "system_admin", 8, True, False, "deactivate_account"),
    ("Confirm final IT clearance", "documentation", "manager", "it_manager", 9, True, False, "none"),
]

TRANSFER_ITEMS = [
    ("Confirm new department", "documentation", "manager", "it_manager", 0, True, False, "none"),
    ("Review current Assets", "asset_return", "it", "it_support", 0, True, False, "none"),
    ("Review access differences", "access", "it", "it_support", 1, True, False, "none"),
    ("Remove obsolete access", "access", "it", "it_support", 2, True, False, "none"),
    ("Grant required access", "access", "it", "it_support", 3, True, False, "none"),
    ("Apply department change", "account", "manager", "system_admin", 4, True, False, "none"),
    ("Confirm completion", "documentation", "manager", "it_manager", 5, True, False, "none"),
]


def _upsert_template(case_type, code, name, department, is_global, create):
    defaults = {
        "name": name,
        "case_type": case_type,
        "department": department,
        "is_global": is_global,
        "is_active": True,
        "version": 1,
    }
    obj, created = lm.LifecycleTemplate.objects.update_or_create(
        code=code, defaults=defaults)
    if create and created:
        return obj, True
    return obj, created


def _seed_items(template, items, create):
    for (title, category, responsibility, role, offset, required,
         evidence, automation) in items:
        lm.LifecycleTemplateItem.objects.update_or_create(
            template=template, sequence=offset,
            defaults={
                "title": title, "category": category,
                "responsibility": responsibility,
                "default_assignee_role": role,
                "required": required, "due_offset_days": offset,
                "blocks_completion": required,
                "requires_evidence": evidence,
                "automation_type": automation,
                "automation_config": {},
            })
    if create:
        template.version = timezone.now().year  # bumped on material change
        template.save(update_fields=["version", "updated_at"])


class Command(BaseCommand):
    help = "Seed reusable onboarding / offboarding / transfer lifecycle templates."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True,
                            help="Report actions without writing (default).")
        parser.add_argument("--create", action="store_true",
                            help="Persist templates (overrides --dry-run).")
        parser.add_argument("--update-existing", action="store_true",
                            help="Update existing templates instead of skipping.")
        parser.add_argument("--department-code", default=None,
                            help="Only seed templates for this department code (global templates always seeded).")
        parser.add_argument("--include-onboarding", action="store_true", default=True)
        parser.add_argument("--include-offboarding", action="store_true", default=True)
        parser.add_argument("--include-transfer", action="store_true", default=True)

    def handle(self, *args, **options):
        create = options["create"]
        dry_run = not create
        dept_code = options["department_code"]
        department = None
        if dept_code:
            try:
                department = Department.objects.get(code=dept_code)
            except Department.DoesNotExist:
                self.stderr.write(f"Department {dept_code} not found.")
                return

        def should(sections, key):
            return options.get(key, False)

        planned = []
        if should(None, "include_onboarding"):
            planned.append(("onboarding", "ONB-EMPLOYEE", "Employee Onboarding",
                            department, False))
        if should(None, "include_offboarding"):
            planned.append(("offboarding", "OFF-EMPLOYEE", "Employee Offboarding",
                            department, False))
        if should(None, "include_transfer"):
            planned.append(("transfer", "TRF-EMPLOYEE", "Employee Transfer",
                            department, False))

        for case_type, code, name, dept, is_global in planned:
            action = "would create/update" if dry_run else "created/updated"
            self.stdout.write(f"{action} template {code} ({case_type})")
            if not dry_run:
                tmpl, _ = _upsert_template(case_type, code, name, dept,
                                           is_global, create)
                if case_type == "onboarding":
                    _seed_items(tmpl, ONBOARDING_ITEMS, create)
                elif case_type == "offboarding":
                    _seed_items(tmpl, OFFBOARDING_ITEMS, create)
                else:
                    _seed_items(tmpl, TRANSFER_ITEMS, create)

        if dry_run:
            self.stdout.write("Dry-run complete. Pass --create to persist.")
        else:
            self.stdout.write("Seed complete.")
