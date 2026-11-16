"""Part 2: MonitoringEvent and MonitoringEventOccurrence."""

content = '''

class MonitoringEvent(models.Model):
    """Immutable normalized record of an external operational event."""

    class EventState(models.TextChoices):
        FIRING = "firing", "Firing"
        RECOVERED = "recovered", "Recovered"
        INFORMATIONAL = "informational", "Informational"
        UNKNOWN = "unknown", "Unknown"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        MINOR = "minor", "Minor"
        MAJOR = "major", "Major"
        CRITICAL = "critical", "Critical"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        NORMALIZED = "normalized", "Normalized"
        CORRELATED = "correlated", "Correlated"
        SUPPRESSED = "suppressed", "Suppressed"
        ALERTED = "alerted", "Alerted"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    class TargetType(models.TextChoices):
        ASSET = "asset", "Asset"
        CONFIGURATION_ITEM = "configuration_item", "Configuration Item"
        SERVICE = "service", "Service"
        HOST = "host", "Host"
        NETWORK_DEVICE = "network_device", "Network Device"
        APPLICATION = "application", "Application"
        DATABASE = "database", "Database"
        CLOUD_RESOURCE = "cloud_resource", "Cloud Resource"
        UNKNOWN = "unknown", "Unknown"

    event_id = models.CharField(max_length=50, unique=True)
    source = models.ForeignKey("MonitoringSource", on_delete=models.CASCADE, related_name="events")
    source_event_id = models.CharField(max_length=200, blank=True, default="")
    event_type = models.CharField(max_length=100)
    event_state = models.CharField(max_length=20, choices=EventState.choices, default=EventState.FIRING)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    fingerprint = models.CharField(max_length=128, unique=True)
    correlation_key = models.CharField(max_length=200, blank=True, default="")
    target_type = models.CharField(max_length=20, choices=TargetType.choices, default=TargetType.UNKNOWN)
    target_identifier = models.CharField(max_length=200, blank=True, default="")
    hostname = models.CharField(max_length=200, blank=True, default="")
    ip_address = models.CharField(max_length=45, blank=True, default="")
    service_name = models.CharField(max_length=200, blank=True, default="")
    metric_name = models.CharField(max_length=200, blank=True, default="")
    metric_value = models.CharField(max_length=200, blank=True, default="")
    threshold = models.CharField(max_length=200, blank=True, default="")
    environment = models.CharField(max_length=50, blank=True, default="")
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_events")
    configuration_item = models.ForeignKey("cmdb.ConfigurationItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_events")
    department = models.CharField(max_length=100, blank=True, default="")
    raw_payload_hash = models.CharField(max_length=128)
    normalized_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    processing_status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.RECEIVED)
    processing_error_code = models.CharField(max_length=50, blank=True, default="")
    processing_error_summary = models.TextField(blank=True, default="")
    duplicate_count = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["fingerprint"], name="event_fingerprint_idx"),
            models.Index(fields=["source", "event_type"], name="event_source_type_idx"),
            models.Index(fields=["event_state"], name="event_state_idx"),
            models.Index(fields=["severity"], name="event_severity_idx"),
            models.Index(fields=["occurred_at"], name="event_occurred_idx"),
            models.Index(fields=["processing_status"], name="event_processing_idx"),
            models.Index(fields=["fingerprint", "event_state"], name="event_fingerprint_state_idx"),
            models.Index(fields=["source", "occurred_at"], name="event_source_time_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["fingerprint"], name="unique_event_fingerprint"),
        ]

    def __str__(self):
        return f"{self.event_id}: {self.title[:80]}"
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 2 written")