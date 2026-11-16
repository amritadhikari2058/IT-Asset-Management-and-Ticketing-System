from django.core.management.base import BaseCommand
from cmdb.services import sync_asset_to_ci

class Command(BaseCommand):
    help = "Sync assets to CMDB."
    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--asset-id", type=int)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--create-missing", action="store_true", default=True)
        parser.add_argument("--update-existing", action="store_true", default=True)
    def handle(self, *args, **options):
        from assets.models import Asset
        dry = options["dry_run"] and not options["execute"]
        qs = Asset.objects.filter(is_deleted=False)
        if options.get("asset_id"):
            qs = qs.filter(id=options["asset_id"])
        qs = qs[:options["batch_size"]]
        created = 0
        for asset in qs:
            if dry:
                created += 1
                continue
            sync_asset_to_ci(asset, create_missing=options["create_missing"], update_existing=options["update_existing"])
            created += 1
        self.stdout.write(f"{'DRY RUN ' if dry else ''}processed: {created}")
