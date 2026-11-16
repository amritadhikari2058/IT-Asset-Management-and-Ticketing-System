"""Part 6: AlertRule and AlertSuppressionWindow."""
content = '''

class AlertRule(models.Model):
    """Defines normalization, correlation, suppression, routing, and Ticket automation policy."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, default="")
    priority = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    source = models.ForeignKey("MonitoringSource", null=True, blank=True, on_delete=models.CASCADE, related_name="alert_rules")
    event_type_pattern = models.CharField(max_length=200, blank=True, default="")
    target_type = models.CharField(max_length=50, blank=True, default="")
    target_pattern = models.CharField(max_length=200, blank=True, default="")
    title_pattern = models.CharField(max_length=200, blank=True, default="")
    severity_conditions = models.JSONField(default=dict, blank=True)
    minimum_severity = models.CharField(max_length=20, blank=True, default="")
    correlation_window_seconds = models.PositiveIntegerField(default=300)
    duplicate_window_seconds = models.PositiveIntegerField(default=3600)
    recovery_window_seconds = models.PositiveIntegerField(default=300)
    flap_window_seconds = models.PositiveIntegerField(default=300)
    flap_threshold = models.PositiveIntegerField(default=5)
    suppression_policy = models.JSONField(default=dict, blank=True)
    maintenance_suppression = models.BooleanField(default=True)
    create_ticket = models.BooleanField(default=False)
    update_existing_ticket = models.BooleanField(default=False)
    auto_resolve_alert = models.BooleanField(default=False)
    recommend_ticket_resolution = models.BooleanField(default=True)
    auto_resolve_ticket = models.BooleanField(default=False)
    ticket_queue = models.CharField(max_length=50, blank=True, default="")
    ticket_category = models.CharField(max_length=100, blank=True, default="")
    ticket_priority_mapping = models.JSONField(default=dict, blank=True)
    assign_to = models.CharField(max_length=200, blank=True, default="")
    department = models.CharField(max_length=100, blank=True, default="")
    notification_policy = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_alert_rules")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["priority", "-created_at"]
        indexes = [
            models.Index(fields=["code"], name="rule_code_idx"),
            models.Index(fields=["is_active"], name="rule_active_idx"),
            models.Index(fields=["source"], name="rule_source_idx"),
            models.Index(fields=["priority"], name="rule_priority_idx"),
        ]

    def __str__(self):
        return self.name


class AlertSuppressionWindow(models.Model):
    """Suppression window for alerts."""

    class ScopeType(models.TextChoices):
        GLOBAL = "global", "Global"
        SOURCE = "source", "Source"
        RULE = "rule", "Rule"
        ASSET = "asset", "Asset"
        CONFIGURATION_ITEM = "configuration_item", "Configuration Item"
        SERVICE = "service", "Service"
        DEPARTMENT = "department", "Department"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    scope_type = models.CharField(max_length=30, choices=ScopeType.choices)
    source = models.ForeignKey("MonitoringSource", null=True, blank=True, on_delete=models.CASCADE, related_name="suppression_windows")
    alert_rule = models.ForeignKey("AlertRule", null=True, blank=True, on_delete=models.CASCADE, related_name="suppression_windows")
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.CASCADE, related_name="suppression_windows")
    configuration_item = models.ForeignKey("cmdb.ConfigurationItem", null=True, blank=True, on_delete=models.CASCADE, related_name="suppression_windows")
    service_catalogue_item = models.ForeignKey("services.ServiceCatalogueItem", null=True, blank=True, on_delete=models.CASCADE, related_name="suppression_windows")
    department = models.CharField(max_length=100, blank=True, default="")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    recurrence = models.CharField(max_length=100, blank=True, default="")
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_suppression_windows")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_suppression_windows")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["scope_type"], name="suppression_scope_idx"),
            models.Index(fields=["status"], name="suppression_status_idx"),
            models.Index(fields=["starts_at", "ends_at"], name="suppression_time_idx"),
        ]

    def __str__(self):
        return self.name
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 6 appended")