from django.core.management.base import BaseCommand
from cmdb.models import ConfigurationItem, ConfigurationBaseline
from cmdb.services import evaluate_configuration_drift

class Command(BaseCommand):
    help = "Evaluate configuration drift."
    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--ci-id", type=int)
        parser.add_argument("--batch-size", type=int, default=100)
    def handle(self, *args, **options):
        dry = options["dry_run"] and not options["execute"]
        qs = ConfigurationItem.objects.filter(is_deleted=False)
        if options.get("ci_id"):
            qs = qs.filter(id=options["ci_id"])
        qs = qs[:options["batch_size"]]
        count = 0
        for ci in qs:
            if dry:
                count += 1
                continue
            evaluate_configuration_drift(ci)
            count += 1
        self.stdout.write(f"{'DRY RUN ' if dry else ''}processed: {count}")
