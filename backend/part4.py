"""Part 4: MonitoringAlert."""
content = '''

class MonitoringAlert(models.Model):
    """Correlated operational condition created from one or more Events."""

    class AlertStatus(models.TextChoices):
        NEW = "new", "New"
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        SUPPRESSED = "suppressed", "Suppressed"
        RECOVERED = "recovered", "Recovered"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        FLAPPING = "flapping", "Flapping"

    class AlertSeverity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        MINOR = "minor", "Minor"
        MAJOR = "major", "Major"
        CRITICAL = "critical", "Critical"

    alert_number = models.CharField(max_length=20, unique=True, editable=False)
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True, default="")
    severity = models.CharField(max_length=20, choices=AlertSeverity.choices, default=AlertSeverity.INFO)
    status = models.CharField(max_length=20, choices=AlertStatus.choices, default=AlertStatus.NEW)
    source = models.ForeignKey("MonitoringSource", on_delete=models.CASCADE, related_name="alerts")
    fingerprint = models.CharField(max_length=128)
    correlation_key = models.CharField(max_length=200, blank=True, default="")
    first_event = models.ForeignKey("MonitoringEvent", null=True, blank=True, on_delete=models.SET_NULL, related_name="first_alert")
    latest_event = models.ForeignKey("MonitoringEvent", null=True, blank=True, on_delete=models.SET_NULL, related_name="latest_alert")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    recovered_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    last_state_change_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="acknowledged_alerts")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_alerts")
    department = models.CharField(max_length=100, blank=True, default="")
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_alerts")
    configuration_item = models.ForeignKey("cmdb.ConfigurationItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_alerts")
    service_catalogue_item = models.ForeignKey("services.ServiceCatalogueItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_alerts")
    queue = models.CharField(max_length=50, blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="")
    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_alerts")
    event_count = models.PositiveIntegerField(default=1)
    duplicate_event_count = models.PositiveIntegerField(default=0)
    suppression_count = models.PositiveIntegerField(default=0)
    flap_count = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    auto_ticket_created = models.BooleanField(default=False)
    auto_resolved = models.BooleanField(default=False)
    resolution_reason = models.TextField(blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-first_seen_at"]
        indexes = [
            models.Index(fields=["fingerprint"], name="alert_fingerprint_idx"),
            models.Index(fields=["source", "status"], name="alert_source_status_idx"),
            models.Index(fields=["severity"], name="alert_severity_idx"),
            models.Index(fields=["status"], name="alert_status_idx"),
            models.Index(fields=["fingerprint", "status"], name="alert_fingerprint_status_idx"),
            models.Index(fields=["first_seen_at"], name="alert_first_seen_idx"),
            models.Index(fields=["last_seen_at"], name="alert_last_seen_idx"),
            models.Index(fields=["alert_number"], name="alert_number_idx"),
            models.Index(fields=["event_count"], name="event_count_idx"),
            models.Index(fields=["flap_count"], name="flap_count_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["fingerprint", "status"], name="unique_active_alert_per_fingerprint_status", condition=models.Q(status__in=["open", "acknowledged", "new"])),
        ]

    def __str__(self):
        return f"ALT-{self.alert_number}: {self.title[:80]}"
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 4 written")