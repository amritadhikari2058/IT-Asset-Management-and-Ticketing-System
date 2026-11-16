"""Part 5: MonitoringAlertHistory."""
content = '''

class MonitoringAlertHistory(models.Model):
    """Immutable history of alert status/severity changes."""

    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        EVENT_CORRELATED = "event_correlated", "Event correlated"
        DUPLICATE_RECEIVED = "duplicate_received", "Duplicate received"
        SEVERITY_CHANGED = "severity_changed", "Severity changed"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        ASSIGNED = "assigned", "Assigned"
        SUPPRESSED = "suppressed", "Suppressed"
        UNSUPPRESSED = "unsuppressed", "Unsuppressed"
        TICKET_CREATED = "ticket_created", "Ticket created"
        TICKET_UPDATED = "ticket_updated", "Ticket updated"
        RECOVERED = "recovered", "Recovered"
        REOPENED = "reopened", "Reopened"
        FLAPPING_DETECTED = "flapping_detected", "Flapping detected"
        FLAPPING_CLEARED = "flapping_cleared", "Flapping cleared"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        AUTOMATION_FAILED = "automation_failed", "Automation failed"

    alert = models.ForeignKey("MonitoringAlert", on_delete=models.CASCADE, related_name="history_entries")
    event = models.ForeignKey("MonitoringEvent", null=True, blank=True, on_delete=models.SET_NULL, related_name="alert_history_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="alert_history_actors")
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    previous_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20, blank=True, default="")
    previous_severity = models.CharField(max_length=20, blank=True, default="")
    new_severity = models.CharField(max_length=20, blank=True, default="")
    detail = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["alert", "created_at"], name="alert_history_alert_time_idx"),
            models.Index(fields=["event_type"], name="alert_history_event_type_idx"),
            models.Index(fields=["created_at"], name="alert_history_time_idx"),
        ]

    def __str__(self):
        return f"{self.alert.alert_number} {self.event_type} at {self.created_at:%Y-%m-%d %H:%M}"
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 5 appended")