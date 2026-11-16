"""Create monitoring models.py script."""
import os

# Remove existing models.py if it has only the header
models_path = "backend/monitoring/models.py"
if os.path.exists(models_path):
    with open(models_path, "r") as f:
        content = f.read()
    if content.strip().startswith('"""Monitoring models'):
        os.remove(models_path)

# Write the full models.py content in parts
# Part 1: Imports and start of MonitoringSource
with open(models_path, "w") as f:
    f.write('"""Monitoring models for event ingestion, alert correlation, and ticket automation."""\n')
    f.write('from django.conf import settings\n')
    f.write('from django.db import models\n')
    f.write('from django.utils import timezone\n')
    f.write('\n')
    f.write('class MonitoringSource(models.Model):\n')
    f.write('    """Represents an authorized external monitoring system or integration."""\n')
    f.write('\n')
    f.write('    class SourceType(models.TextChoices):\n')
    f.write('        GENERIC_WEBHOOK = "generic_webhook", "Generic Webhook"\n')
    f.write('        PROMETHEUS_ALERTMANAGER = "prometheus_alertmanager", "Prometheus Alertmanager"\n')
    f.write('        GRAFANA = "grafana", "Grafana"\n')
    f.write('        ZABBIX = "zabbix", "Zabbix"\n')
    f.write('        PRTG = "prtg", "PRTG"\n')
    f.write('        NAGIOS = "nagios", "Nagios"\n')
    f.write('        AZURE_MONITOR = "azure_monitor", "Microsoft Azure Monitor"\n')
    f.write('        AWS_CLOUDWATCH = "aws_cloudwatch", "AWS CloudWatch"\n')
    f.write('        VMWARE_VCENTER = "vmware_vcenter", "VMware vCenter"\n')
    f.write('        WINDOWS_EVENT = "windows_event", "Windows Event Forwarding"\n')
    f.write('        LINUX_AGENT = "linux_agent", "Linux monitoring agent"\n')
    f.write('        MANUAL = "manual", "Manual events"\n')
    f.write('        OTHER = "other", "Other"\n')
    f.write('\n')
    f.write('    class AuthenticationType(models.TextChoices):\n')
    f.write('        HMAC_SHA256 = "hmac_sha256", "HMAC-SHA256"\n')
    f.write('        BEARER_TOKEN_HASH = "bearer_token_hash", "Bearer token hash"\n')
    f.write('        API_KEY_HASH = "api_key_hash", "API key hash"\n')
    f.write('        MANUAL_INTERNAL = "manual_internal", "Manual internal"\n')
    f.write('\n')
    f.write('    class HealthStatus(models.TextChoices):\n')
    f.write('        HEALTHY = "healthy", "Healthy"\n')
    f.write('        DEGRADED = "degraded", "Degraded"\n')
    f.write('        UNHEALTHY = "unhealthy", "Unhealthy"\n')
    f.write('        UNKNOWN = "unknown", "Unknown"\n')
    f.write('\n')
    f.write('    class Status(models.TextChoices):\n')
    f.write('        ACTIVE = "active", "Active"\n')
    f.write('        DISABLED = "disabled", "Disabled"\n')
    f.write('        DEGRADED = "degraded", "Degraded"\n')
    f.write('        ERROR = "error", "Error"\n')
    f.write('        RETIRED = "retired", "Retired"\n')
    f.write('\n')
    f.write('    name = models.CharField(max_length=200)\n')
    f.write('    code = models.CharField(max_length=50, unique=True, help_text="Server-normalized integration code")\n')
    f.write('    source_type = models.CharField(max_length=30, choices=SourceType.choices, default=SourceType.OTHER)\n')
    f.write('    description = models.TextField(blank=True, default="")\n')
    f.write('    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)\n')
    f.write('\n')

print("Part 1 written successfully")