"""Workflow models (Phase 19): automation rules, executions, approvals."""
from django.db import models
from accounts.models import User
from tickets.models import Ticket


class AutomationRule(models.Model):
    TRIGGER_CHOICES = [
        ("ticket_created", "Ticket Created"),
        ("ticket_updated", "Ticket Updated"),
        ("status_changed", "Status Changed"),
    ]
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=True, db_index=True)
    trigger = models.CharField(
        max_length=30, choices=TRIGGER_CHOICES, default="ticket_created")
    # {"category_id": 1, "priority": "high", "department_id": 2,
    #  "status": "open"} — equality only (see workflow.services).
    conditions = models.JSONField(default=dict, blank=True)
    # [{"type": "assign", "user_id": 5}, {"type": "priority", "value":
    #  "high"}, {"type": "status", "value": "in_progress"},
    #  {"type": "note", "text": "..."}, {"type": "notify", "user_id": ...}]
    actions = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="automation_rules_created")
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="automation_rules_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.trigger})"


class RuleExecution(models.Model):
    """One automation-rule run against one ticket (execution history)."""
    rule = models.ForeignKey(
        AutomationRule, on_delete=models.CASCADE, related_name="executions")
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="rule_executions")
    success = models.BooleanField(default=True)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="ruleexec_created_idx"),
        ]

    def __str__(self):
        return f"Execution #{self.pk} rule={self.rule_id} " \
               f"ticket={self.ticket_id} ({'ok' if self.success else 'fail'})"


class ApprovalRequest(models.Model):
    """Approval request for a sensitive ticket operation.

    Lifecycle: pending -> approved/rejected (terminal). The requester
    cannot decide their own request, a decided request cannot be decided
    again, and an approved decision applies the requested operation to
    the ticket.
    """
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    OPERATION_CHOICES = [
        ("other", "Other"),
        ("change_priority", "Change priority"),
        ("change_status", "Change status"),
        ("reassign", "Reassign"),
    ]
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="approval_requests")
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="approval_requests_made")
    approver = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approval_requests_assigned")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending",
        db_index=True)
    # Which operation the approver is being asked to permit.
    operation = models.CharField(
        max_length=30, choices=OPERATION_CHOICES, default="other")
    # Shape depends on operation: {"priority": ...} / {"status": ...} /
    # {"user_id": ...}. Validated at the API layer (serializer).
    context = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    decision_comment = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approval_decisions")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Approval #{self.pk} ticket #{self.ticket_id} ({self.status})"

    @property
    def is_decided(self):
        return self.status != "pending"
