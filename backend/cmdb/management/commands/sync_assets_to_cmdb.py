"""Synchronize assets into the CMDB configuration items.

Dry-run by default: use --execute to write. The sync itself is idempotent
(manual CIs are preserved; asset-sourced CIs are refreshed).
"""

import argparse

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Synchronize assets into CMDB configuration items."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--dry-run", action="store_true",
            help="Report what would happen without writing (default).",
        )
        group.add_argument(
            "--execute", action="store_true",
            help="Actually run the synchronization.",
        )
        parser.add_argument("--asset-id", type=int,
                            help="Sync only this asset.")
        parser.add_argument("--category-id", type=int,
                            help="Sync only assets in this category.")
        parser.add_argument("--department-id", type=int,
                            help="Sync only assets in this department.")
        parser.add_argument(
            "--batch-size", type=int, default=100,
            help="Maximum number of assets to process (default 100).",
        )
        parser.add_argument(
            "--create-missing", action=argparse.BooleanOptionalAction,
            default=True,
            help="Create a CI when the asset has none (default: true).",
        )
        parser.add_argument(
            "--update-existing", action=argparse.BooleanOptionalAction,
            default=True,
            help="Refresh CIs already linked to an asset (default: true).",
        )

    def handle(self, *args, **options):
        from assets.models import Asset

        from cmdb.models import ConfigurationItem
        from cmdb.services import sync_asset_to_ci

        execute = options["execute"]
        batch = max(int(options["batch_size"] or 100), 1)

        qs = Asset.objects.filter(is_deleted=False).order_by("id")
        if options.get("asset_id"):
            qs = qs.filter(id=options["asset_id"])
        if options.get("category_id"):
            qs = qs.filter(category_id=options["category_id"])
        if options.get("department_id"):
            qs = qs.filter(department_id=options["department_id"])
        qs = qs[:batch]

        created = 0
        updated = 0
        skipped = 0
        would_create = 0
        would_update = 0
        would_skip = 0

        for asset in qs:
            linked = ConfigurationItem.objects.filter(
                asset=asset, is_deleted=False,
            ).exists()
            if not execute:
                if linked and options["update_existing"]:
                    would_update += 1
                elif linked:
                    would_skip += 1
                elif options["create_missing"]:
                    would_create += 1
                else:
                    would_skip += 1
                continue
            ci, was_created = sync_asset_to_ci(
                asset,
                create_missing=options["create_missing"],
                update_existing=options["update_existing"],
            )
            if was_created:
                created += 1
            elif ci is None or not linked:
                skipped += 1
            elif options["update_existing"] and ci.source == "asset_sync":
                updated += 1
            else:
                skipped += 1

        if execute:
            self.stdout.write(
                self.style.SUCCESS(
                    f"created: {created}, updated: {updated}, "
                    f"skipped: {skipped}"
                )
            )
        else:
            self.stdout.write(
                f"DRY RUN: would create: {would_create}, "
                f"would update: {would_update}, would skip: {would_skip}"
            )
            self.stdout.write(self.style.WARNING(
                "Dry run only. Use --execute to write changes.",
            ))
