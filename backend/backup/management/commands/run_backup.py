"""Management command to run backup jobs from the command line."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from backup.models import BackupJob


class Command(BaseCommand):
    help = "Create and run a backup job (config, database, files, media)."

    def add_arguments(self, parser):
        parser.add_argument("type", choices=["config", "database", "files", "media"],
                            help="Type of backup to run.")
        parser.add_argument("--target", default="",
                            help="Optional target host/path for the backup.")
        parser.add_argument("--async", action="store_true",
                            help="Enqueue via Celery instead of running inline.")

    def handle(self, *args, **options):
        job_type = options["type"]
        target = options.get("target", "")
        use_async = options.get("async", False)

        job = BackupJob.objects.create(
            job_type=job_type,
            status="pending",
            target=target,
        )
        self.stdout.write(f"Created BackupJob #{job.pk} ({job_type})")

        if use_async:
            from backup.tasks import run_backup_job
            run_backup_job.delay(str(job.pk))
            self.stdout.write(self.style.SUCCESS(
                f"Enqueued BackupJob #{job.pk} via Celery."))
        else:
            from backup.tasks import run_backup_job
            result = run_backup_job.apply(args=[str(job.pk)])
            self.stdout.write(self.style.SUCCESS(
                f"BackupJob #{job.pk} finished: {result.get('status')}"))
            if result.get("error"):
                self.stdout.write(self.style.WARNING(f"Error: {result['error']}"))
