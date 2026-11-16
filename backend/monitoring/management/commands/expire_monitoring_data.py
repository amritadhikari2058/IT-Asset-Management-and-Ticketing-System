"""Management command to expire monitoring data."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Expire monitoring data."""

    help = "Expire monitoring data according to retention policies"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be deleted without deleting"
        )
        parser.add_argument(
            "--execute", action="store_true", help="Actually delete expired data"
        )
        parser.add_argument(
            "--before", type=str, help="Delete data before this date"
        )
        parser.add_argument(
            "--batch-size", type=int, default=100, help="Number of records to process"
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Monitoring data expiry command."))
        self.stdout.write("  Default: --dry-run mode - no data deleted.")
        self.stdout.write("  Use --execute to delete expired data.")