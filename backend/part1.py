"""Part 1: Imports and MonitoringSource."""
content = '''"""Monitoring models for event ingestion, alert correlation, and ticket automation."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class MonitoringSource(models.Model):
    """Represents an authorized external monitoring system or integration."""

    class SourceType(models.TextChoices):
        GENERIC_WEBHOOK = "generic_webhook", "Generic Webhook"
        PROMETHEUS_ALERTMANAGER = "prometheus_alertmanager", "Prometheus Alertmanager"
        GRAFANA = "grafana", "Grafana"
        ZABBIX = "zabbix", "Zabbix"
        PRTG = "prtg", "PRTG"
        NAGIOS = "nagios", "Nagios"
        AZURE_MONITOR = "azure_monitor", "Microsoft Azure Monitor"
        AWS_CLOUDWATCH = "aws_cloudwatch", "AWS CloudWatch"
        VMWARE_VCENTER = "vmware_vcenter", "VMware vCenter"
        WINDOWS_EVENT = "windows_event", "Windows Event Forwarding"
        LINUX_AGENT = "linux_agent", "Linux monitoring agent"
        MANUAL = "manual", "Manual events"
        OTHER = "other", "Other"

    class AuthenticationType(models.TextChoices):
        HMAC_SHA256 = "hmac_sha256", "HMAC-SHA256"
        BEARER_TOKEN_HASH = "bearer_token_hash", "Bearer token hash"
        API_KEY_HASH = "api_key_hash", "API key hash"
        MANUAL_INTERNAL = "manual_internal", "Manual internal"

    class HealthStatus(models.TextChoices):
        HEALTHY = "healthy", "Healthy"
        DEGRADED = "degraded", "Degraded"
        UNHEALTHY = "unhealthy", "Unhealthy"
        UNKNOWN = "unknown", "Unknown"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"
        DEGRADED = "degraded", "Degraded"
        ERROR = "error", "Error"
        RETIRED = "retired", "Retired"

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    source_type = models.CharField(max_length=30, choices=SourceType.choices, default=SourceType.OTHER)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    authentication_type = models.CharField(
        max_length=30, choices=AuthenticationType.choices, default=AuthenticationType.MANUAL_INTERNAL
    )
    secret_hash = models.CharField(max_length=128)
    previous_secret_hash = models.CharField(max_length=128, null=True, blank=True)
    allowed_ip_networks = models.CharField(max_length=500, blank=True, default="")
    allowed_event_types = models.CharField(max_length=500, blank=True, default="")
    allowed_target_patterns = models.CharField(max_length=500, blank=True, default="")
    default_severity_mapping = models.JSONField(default=dict, blank=True)
    default_queue = models.CharField(max_length=50, blank=True, default="")
    default_category = models.CharField(max_length=100, blank=True, default="")
    rate_limit_per_minute = models.PositiveIntegerField(default=60)
    maximum_payload_bytes = models.PositiveIntegerField(default=10485760)
    timestamp_tolerance_seconds = models.PositiveIntegerField(default=300)
    enable_ticket_creation = models.BooleanField(default=True)
    enable_auto_resolution = models.BooleanField(default=False)
    last_event_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    health_status = models.CharField(max_length=20, choices=HealthStatus.choices, default=HealthStatus.UNKNOWN)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_monitoring_sources")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    soft_delete = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="deleted_monitoring_sources")

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"], name="source_code_idx"),
            models.Index(fields=["source_type"], name="source_type_idx"),
            models.Index(fields=["status"], name="source_status_idx"),
            models.Index(fields=["is_active"], name="source_is_active_idx"),
            models.Index(fields=["health_status"], name="source_health_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()})"

    def clean(self):
        import ipaddress
        if self.allowed_ip_networks:
            for cidr in self.allowed_ip_networks.split(","):
                cidr = cidr.strip()
                if cidr:
                    try:
                        ipaddress.ip_network(cidr, strict=False)
                    except ValueError:
                        raise ValueError(f"Invalid CIDR: '{cidr}'")
'''

with open('backend/monitoring/models.py', 'w') as f:
    f.write(content)
print("Part 1 written")