"""Part 3: MonitoringEventOccurrence and MonitoringIngestionAttempt."""
content = '''

class MonitoringEventOccurrence(models.Model):
    """Retain repeated occurrence timing without storing a full duplicate Event row."""

    event = models.ForeignKey("MonitoringEvent", on_delete=models.CASCADE, related_name="occurrences")
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    event_state = models.CharField(max_length=20, choices=MonitoringEvent.EventState.choices)
    metric_value = models.CharField(max_length=200, blank=True, default="")
    payload_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["event", "occurred_at"], name="occurrence_event_time_idx"),
            models.Index(fields=["event_state"], name="occurrence_state_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["event", "occurred_at"], name="unique_occurrence_per_event_time"),
        ]


class MonitoringIngestionAttempt(models.Model):
    """Record of an ingestion attempt for source health and abuse review."""

    class AuthenticationResult(models.TextChoices):
        SUCCESS = "success", "Success"
        MISSING = "missing", "Missing headers"
        INVALID = "invalid", "Invalid signature/auth"
        EXPIRED_GRACE = "expired_grace", "Previous secret expired grace period"
        IP_DENIED = "ip_denied", "IP address not allowed"
        RATE_LIMITED = "rate_limited", "Rate limit exceeded"

    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        PARTIALLY_ACCEPTED = "partially_accepted", "Partially accepted"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    source = models.ForeignKey("MonitoringSource", on_delete=models.CASCADE, related_name="ingestion_attempts")
    request_id = models.CharField(max_length=128, unique=True)
    received_at = models.DateTimeField(auto_now_add=True)
    remote_address_hash = models.CharField(max_length=128)
    authentication_result = models.CharField(max_length=30, choices=AuthenticationResult.choices, default=AuthenticationResult.SUCCESS)
    payload_size = models.PositiveIntegerField(default=0)
    event_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    processing_duration_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACCEPTED)
    error_code = models.CharField(max_length=50, blank=True, default="")
    error_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["source", "received_at"], name="ingest_source_time_idx"),
            models.Index(fields=["authentication_result"], name="ingest_auth_idx"),
            models.Index(fields=["status"], name="ingest_status_idx"),
        ]

    def __str__(self):
        return f"Ingest {self.request_id} from {self.source.code}"
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 3 appended")