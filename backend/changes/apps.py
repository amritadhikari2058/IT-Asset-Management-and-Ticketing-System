"""Change management application configuration."""
from django.apps import AppConfig


class ChangesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "changes"
    verbose_name = "Change Management"
