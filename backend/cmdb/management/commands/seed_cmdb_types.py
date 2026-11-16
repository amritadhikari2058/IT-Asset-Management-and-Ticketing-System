from django.core.management.base import BaseCommand
from cmdb.models import ConfigurationItemType

DEFAULT_TYPES = [
 ("Server","SERVER","hardware"),("Workstation","WORKSTATION","hardware"),("Laptop","LAPTOP","hardware"),
 ("Network Device","NETWORK_DEVICE","network"),("Printer","PRINTER","hardware"),("Storage Device","STORAGE_DEVICE","hardware"),
 ("Database","DATABASE","database"),("Business Application","BUSINESS_APPLICATION","application"),
 ("Software Product","SOFTWARE_PRODUCT","software"),("Cloud Service","CLOUD_SERVICE","cloud"),
 ("IT Service","IT_SERVICE","service"),("Facility","FACILITY","facility"),("Documentation","DOCUMENTATION","document"),
 ("User Account","USER_ACCOUNT","account"),("Virtual Machine","VIRTUAL_MACHINE","logical"),
]

class Command(BaseCommand):
    help = "Seed CMDB configuration item types."
    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True)
        parser.add_argument("--create", action="store_true")
        parser.add_argument("--update-existing", action="store_true")
    def handle(self, *args, **options):
        dry = options["dry_run"] and not options["create"]
        created = 0
        for name, code, cat in DEFAULT_TYPES:
            exists = ConfigurationItemType.objects.filter(code=code).exists()
            if exists:
                if options["update_existing"] and not dry:
                    ConfigurationItemType.objects.filter(code=code).update(name=name, category=cat)
                continue
            if not dry:
                ConfigurationItemType.objects.create(name=name, code=code, category=cat, is_system=True)
            created += 1
        self.stdout.write(f"{'DRY RUN ' if dry else ''}types to create: {created}")
