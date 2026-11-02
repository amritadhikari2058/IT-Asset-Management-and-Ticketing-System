"""Celery configuration for the IT Ticketing & Asset Management System."""
import os

from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('it_asset_ticketing')

# Broker and backend from environment variables, with sensible defaults.
app.conf.broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
app.conf.result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Task execution defaults: bounded retries with exponential backoff so a
# transient failure (e.g. SMTP/IMAP hiccup) is retried automatically while a
# permanent failure surfaces as a failed task (see BackgroundTaskRun).
app.conf.task_default_retry_policy = {
    'max_retries': int(os.getenv('CELERY_TASK_MAX_RETRIES', '3')),
    'retry_backoff': int(os.getenv('CELERY_TASK_RETRY_BACKOFF', '60')),
    'interval_start': 0,
}
# Hard ceiling per task run (seconds) - protects beat/worker from hangs.
app.conf.task_time_limit = int(os.getenv('CELERY_TASK_TIME_LIMIT', '300'))
app.conf.task_soft_time_limit = int(
    os.getenv('CELERY_TASK_TIME_LIMIT', '300')) - 30

# Worker concurrency (CPU-bound tasks such as SLA scans).
app.conf.worker_concurrency = int(os.getenv('CELERY_CONCURRENCY', '4'))

# Using a string here means the worker doesn't have to serialize
# the configuration to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodiscover tasks from all installed Django apps.
app.autodiscover_tasks()

# Import apps tasks so they are registered.
import tickets.tasks  # noqa: F401
import assets.tasks  # noqa: F401
import common.tasks  # noqa: F401


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
