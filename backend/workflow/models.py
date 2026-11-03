from django.db import models
from django.utils import timezone
from accounts.models import User, Department
from tickets.models import Ticket


class AutomationRule(models.Model):
    TRIGGER_CHOICES = [("ticket_created", "Ticket Created"), ("ticket_updated", "Ticket Updated"), ("status_changed", "Status Changed")]
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=True, db_index=True)
    trigger = models.CharField(max_length=30, choices=TRIGGER_CHOICES, default="ticket_created")
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="automation_rules_created")
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="automation_rules_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]


class RuleExecution(models.Model):
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="executions")
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="rule_executions")
    success = models.BooleanField(default=True)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ApprovalRequest(models.Model):
    STATUS_CHOICES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="approval_requests")
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approval_requests_made")
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_requests_assigned")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    reason = models.TextField(blank=True, default="")
    decision_comment = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_decisions")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
