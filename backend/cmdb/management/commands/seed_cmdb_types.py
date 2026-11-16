"""Seed the standard CMDB configuration item types.

Dry-run by default: use --create to actually write. With --create,
--update-existing refreshes name/category of already-present types.
"""

from django.core.management.base import BaseCommand

from cmdb.models import ConfigurationItemType

DEFAULT_TYPES = [
    ("Server", "SERVER", "hardware"),
    ("Workstation", "WORKSTATION", "hardware"),
    ("Laptop", "LAPTOP", "hardware"),
    ("Network Device", "NETWORK_DEVICE", "network"),
    ("Printer", "PRINTER", "hardware"),
    ("Storage Device", "STORAGE_DEVICE", "hardware"),
    ("Database", "DATABASE", "database"),
    ("Business Application", "BUSINESS_APPLICATION", "application"),
    ("Software Product", "SOFTWARE_PRODUCT", "software"),
    ("Cloud Service", "CLOUD_SERVICE", "cloud"),
    ("IT Service", "IT_SERVICE", "service"),
    ("Facility", "FACILITY", "facility"),
    ("Documentation", "DOCUMENTATION", "document"),
    ("User Account", "USER_ACCOUNT", "account"),
    ("Virtual Machine", "VIRTUAL_MACHINE", "logical"),
]


class Command(BaseCommand):
    help = "Seed the standard CMDB configuration item types."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing (default).",
        )
        group.add_argument(
            "--create", action="store_true",
            help="Actually create the missing types.",
        )
        parser.add_argument(
            "--update-existing", action="store_true",
            help="With --create: refresh name/category of existing types.",
        )

    def handle(self, *args, **options):
        execute = options["create"]
        dry = not execute
        update_existing = options["update_existing"]

        would_create = []
        would_update = []
        created_codes = []
        updated_codes = []

        for name, code, category in DEFAULT_TYPES:
            existing = ConfigurationItemType.objects.filter(code=code).first()
            if existing is None:
                if execute:
                    ConfigurationItemType.objects.create(
                        name=name, code=code, category=category,
                        is_system=True,
                    )
                    created_codes.append(code)
                else:
                    would_create.append(code)
                continue
            if existing.name != name or existing.category != category:
                if execute and update_existing:
                    existing.name = name
                    existing.category = category
                    existing.save(update_fields=["name", "category", "updated_at"])
                    updated_codes.append(code)
                else:
                    would_update.append(code)

        prefix = "DRY RUN: " if dry else ""
        self.stdout.write(
            f"{prefix}created: {len(created_codes)}, "
            f"updated: {len(updated_codes)}"
        )
        if created_codes:
            self.stdout.write(f"created: {', '.join(created_codes)}")
        if updated_codes:
            self.stdout.write(f"updated: {', '.join(updated_codes)}")
        if would_create:
            self.stdout.write(f"would create: {', '.join(would_create)}")
        if would_update:
            self.stdout.write(f"would update: {', '.join(would_update)}")
        if dry:
            self.stdout.write(self.style.WARNING(
                "Dry run only. Use --create to write changes.",
            ))
