"""Part 7: TargetMapping and MonitoringEscalationPolicy."""
content = '''

class TargetMapping(models.Model):
    """Maps source target identifiers to existing records."""

    class Confidence(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"
        UNKNOWN = "unknown", "Unknown"

    source = models.ForeignKey("MonitoringSource", on_delete=models.CASCADE, related_name="target_mappings")
    source_target_identifier = models.CharField(max_length=200)
    target_type = models.CharField(max_length=50)
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="target_mappings")
    configuration_item = models.ForeignKey("cmdb.ConfigurationItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="target_mappings")
    service_catalogue_item = models.ForeignKey("services.ServiceCatalogueItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="target_mappings")
    department = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)
    confidence = models.CharField(max_length=20, choices=Confidence.choices, default=Confidence.UNKNOWN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_target_mappings")
    last_matched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confidence", "-created_at"]
        indexes = [
            models.Index(fields=["source", "source_target_identifier"], name="mapping_source_target_idx"),
            models.Index(fields=["target_type"], name="mapping_target_type_idx"),
            models.Index(fields=["is_active"], name="mapping_active_idx"),
        ]

    def __str__(self):
        return f"{self.source_target_identifier} -> {self.target_type}"


class MonitoringEscalationPolicy(models.Model):
    """Escalation policy for alerts."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    minimum_severity = models.CharField(max_length=20, default="warning")
    acknowledgement_timeout_minutes = models.PositiveIntegerField(default=60)
    repeat_interval_minutes = models.PositiveIntegerField(default=30)
    maximum_repeats = models.PositiveIntegerField(default=3)
    escalation_users = models.CharField(max_length=500, blank=True, default="")
    escalation_department = models.CharField(max_length=100, blank=True, default="")
    escalation_queue = models.CharField(max_length=100, blank=True, default="")
    notify_system_admin = models.BooleanField(default=False)
    notify_it_manager = models.BooleanField(default=True)
    create_ticket_on_timeout = models.BooleanField(default=False)
    raise_ticket_priority_on_timeout = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_escalation_policies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"], name="escalation_code_idx"),
            models.Index(fields=["is_active"], name="escalation_active_idx"),
        ]

    def __str__(self):
        return self.name
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 7 appended")