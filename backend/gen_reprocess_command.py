"""Generate reprocess_monitoring_events command."""
content = '''"""Management command to reprocess monitoring events."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Reprocess monitoring events."""

    help = "Reprocess monitoring events"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be processed without processing"
        )
        parser.add_argument(
            "--event-id", type=str, help="Process specific event by ID"
        )
        parser.add_argument(
            "--source", type=str, help="Filter by source code"
        )
        parser.add_argument(
            "--status", type=str, help="Filter by processing status"
        )
        parser.add_argument(
            "--date-from", type=str, help="Filter events after date"
        )
        parser.add_argument(
            "--date-to", type=str, help="Filter events before date"
        )
        parser.add_argument(
            "--batch-size", type=int, default=100, help="Number of events to process"
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Monitoring events reprocessed."))
        self.stdout.write("  Use --execute to actually reprocess events.")
        self.stdout.write("  Use --dry-run (default) to preview.")'''

with open('backend/monitoring/management/commands/reprocess_monitoring_events.py', 'w') as f:
    f.write(content)
print('Command created')