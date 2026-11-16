"""Part 8: AlertEscalationState."""
content = '''

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
'''

with open('backend/monitoring/models.py', 'a') as f:
    f.write(content)
print("Part 8 appended")