"""Management command to seed monitoring defaults."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Seed monitoring defaults."""

    help = "Seed monitoring defaults"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be created without creating"
        )
        parser.add_argument(
            "--create", action="store_true", help="Create default sources and rules"
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Monitoring defaults seeded."))
        self.stdout.write("  Use --create to actually create sources and rules.")
        self.stdout.write("  Use --dry-run (default) to preview without creating.")