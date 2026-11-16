"""Monitoring models for event ingestion, alert correlation, and ticket automation."""

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
        return self.name

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


class AlertEscalationState(models.Model):
    """Tracks escalation state for an alert."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        STOPPED = "stopped", "Stopped"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    alert = models.ForeignKey("MonitoringAlert", on_delete=models.CASCADE, related_name="escalation_states")
    policy = models.ForeignKey("MonitoringEscalationPolicy", on_delete=models.CASCADE, related_name="escalation_states")
    level = models.PositiveIntegerField(default=1)
    next_escalation_at = models.DateTimeField()
    last_escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_count = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["alert", "policy"], name="escalation_alert_policy_idx"),
            models.Index(fields=["state"], name="escalation_state_idx"),
            models.Index(fields=["next_escalation_at"], name="escalation_next_idx"),
        ]

    def __str__(self):
        return f"{self.alert.alert_number} escalation {self.state}"


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
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_acknowledged_alerts")
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
