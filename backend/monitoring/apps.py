"""Monitoring application configuration."""

from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    name = "monitoring"
    verbose_name = "Monitoring Event and Alert Management"

    def ready(self):
        """Import signals and tasks when the app is ready."""
        import monitoring.signals  # noqa: F401
        import monitoring.tasks  # noqa: F401