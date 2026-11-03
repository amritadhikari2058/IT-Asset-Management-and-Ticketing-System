"""Tickets domain: managed ticket categories, tickets, notes, history.

Rules enforced:
- TicketCategory is separate from AssetCategory (different concepts).
- Category dropdown validated backend-side; only privileged staff can
  create/edit categories (views enforce; employees get 403).
- Department is selectable at ticket creation (defaults to requester's
  home department). Visibility: own tickets + home-department tickets
  for employees; IT staff / admins see operational scope.
- Status transitions validated per-ticket (bulk validates each row).
- History + notes are PROTECTed so hard deletion is blocked while they
  exist. Soft deletion never removes history/notes.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from datetime import timedelta

from common.models import SoftDeleteModel


def attachment_upload_to(instance, filename):
    """Safe filename: uuid + whitelisted extension, no user paths.

    Prevents path traversal (original name never used as a path) and
    collisions. Original name is stored in ``original_filename``.
    """
    import os
    import uuid

    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    safe_ext = "".join(c for c in ext if c.isalnum())[:10]
    return f"ticket_attachments/{uuid.uuid4().hex}" + (
        f".{safe_ext}" if safe_ext else "")


class TicketCategory(SoftDeleteModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("hard_delete_ticketcategory", "Can permanently delete ticket categories"),
            ("restore_ticketcategory", "Can restore soft-deleted ticket categories"),
        ]

    def __str__(self):
        return self.name


class Ticket(SoftDeleteModel):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
        ("reopened", "Reopened"),
        ("archived", "Archived"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    # Allowed next statuses per current status (bulk validates each ticket).
    VALID_TRANSITIONS = {
        "open": {"in_progress", "resolved", "closed", "archived"},
        "in_progress": {"resolved", "open", "closed"},
        "resolved": {"closed", "reopened"},
        "closed": {"reopened", "archived"},
        "reopened": {"in_progress", "resolved", "closed"},
        "archived": set(),
    }

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.ForeignKey(
        TicketCategory, on_delete=models.PROTECT, related_name="tickets"
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="open"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tickets_requested",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_assigned",
    )
    # Department the ticket is FOR (selectable at creation per your call).
    department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    on_behalf_reason = models.TextField(blank=True, default="")
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    resolution_notes = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # SLA tracking: due date computed from priority target at creation; flagged
    # breached once past due without resolution. SLA targets live in
    # TicketSLA configuration (admin-configurable per priority).
    sla_due_at = models.DateTimeField(null=True, blank=True)
    sla_breached = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="ticket_status_idx"),
            models.Index(fields=["assignee"], name="ticket_assignee_idx"),
            models.Index(fields=["requester"], name="ticket_requester_idx"),
            models.Index(fields=["sla_due_at"], name="ticket_sla_due_idx"),
            models.Index(fields=["department"], name="ticket_department_idx"),
            models.Index(fields=["created_at"], name="ticket_created_at_idx"),
            models.Index(fields=["priority"], name="ticket_priority_idx"),
        ]
        permissions = [
            ("hard_delete_ticket", "Can permanently delete tickets"),
            ("restore_ticket", "Can restore soft-deleted tickets"),
            ("view_ticket_history", "Can view ticket history"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.title} [{self.status}]"

    @classmethod
    def can_transition(cls, from_status, to_status):
        if from_status == to_status:
            return True
        return to_status in cls.VALID_TRANSITIONS.get(from_status, set())

    @property
    def is_overdue(self):
        """Ticket is past its SLA due date and not yet resolved/closed."""
        if self.status in ("resolved", "closed", "archived"):
            return False
        if not self.sla_due_at:
            return False
        from django.utils import timezone
        return timezone.now() > self.sla_due_at

    @property
    def priority_sla(self):
        """Active SLA configuration for this ticket's priority (or None).

        Read-only lookup used by SLA notification paths; missing/inactive
        config means no SLA clock is attached, so notifications no-op.
        """
        from tickets.models import TicketSLA
        try:
            return TicketSLA.objects.get(
                priority=self.priority, is_active=True, is_deleted=False)
        except (TicketSLA.DoesNotExist, TicketSLA.MultipleObjectsReturned):
            return None


class TicketSLA(SoftDeleteModel):
    """SLA target per ticket priority. Admin-configurable.

    target_resolution_hours is the clock within which a ticket of this
    priority should be resolved. Used to compute sla_due_at on creation and
    to flag overdue tickets.

    escalation_hours: if set, send a notification this many hours before the
    SLA deadline (breach threshold).  When null, the default is 80 % of
    target_resolution_hours.

    breach_hours: if set, send a breach notification this many hours after the
    SLA deadline.  When null, the default is target_resolution_hours + 4.
    """

    priority = models.CharField(
        max_length=20, choices=Ticket.PRIORITY_CHOICES, unique=True)
    target_resolution_hours = models.PositiveIntegerField(
        default=24,
        help_text="Target resolution window in hours for this priority.")
    escalation_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Hours before the SLA deadline to send an escalation notification.")
    breach_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Hours after the SLA deadline to send a breach notification.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority"]
        permissions = [
            ("manage_ticketsla", "Can manage ticket SLA configuration"),
        ]

    def __str__(self):
        return f"SLA {self.get_priority_display()}: {self.target_resolution_hours}h"

    def escalation_deadline(self, from_dt=None):
        """Return the datetime at which an escalation notification should fire.

        ``from_dt`` is the SLA deadline (ticket ``sla_due_at``); when omitted
        the current time is used. Defaults to the configured escalation
        window before the deadline (escalation_hours or 80% of the target).
        """
        from django.utils import timezone
        ref = from_dt or timezone.now()
        if self.escalation_hours:
            return ref - timedelta(hours=self.escalation_hours)
        # default: 80% of target before the deadline
        return ref - timedelta(hours=max(1, self.target_resolution_hours * 4 // 5))

    def breach_deadline(self, from_dt=None):
        """Return the datetime at which a breach notification should fire.

        ``from_dt`` is the SLA deadline (ticket ``sla_due_at``); when omitted
        the current time is used. Defaults to the configured breach window
        after the deadline (breach_hours or target + 4).
        """
        from django.utils import timezone
        ref = from_dt or timezone.now()
        if self.breach_hours:
            return ref + timedelta(hours=self.breach_hours)
        # default: 4 hours after the target window
        return ref + timedelta(hours=self.target_resolution_hours + 4)


class SLAEscalation(models.Model):
    """Track SLA escalation events to prevent duplicate notifications.

    One record per (ticket, level) ensures we only fire a given notification
    type once per ticket until the state changes.
    """

    LEVEL_CHOICES = (
        ("approach", "Approaching deadline"),
        ("breach", "SLA breached"),
    )

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="sla_escalations")
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("ticket", "level")
        ordering = ["-created_at"]

    def __str__(self):
        return f"SLA #{self.ticket_id} {self.level}"


class TicketNote(models.Model):
    """Internal notes (is_internal=True) vs requester-visible updates (False)."""

    ticket = models.ForeignKey(
        Ticket, on_delete=models.PROTECT, related_name="notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_notes",
    )
    body = models.TextField()
    is_internal = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        scope = "internal" if self.is_internal else "visible"
        return f"Note on #{self.ticket_id} ({scope}) by {self.author}"


class TicketHistory(models.Model):
    """Append-only ticket change log. Not editable/deletable via API."""

    ticket = models.ForeignKey(
        Ticket, on_delete=models.PROTECT, related_name="history"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_history_entries",
    )
    action = models.CharField(max_length=40)
    timestamp = models.DateTimeField(auto_now_add=True)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["timestamp"]
        permissions = [
            ("view_ticket_history", "Can view ticket history"),
        ]

    def __str__(self):
        return f"#{self.ticket_id} {self.action} by {self.actor} @ {self.timestamp:%Y-%m-%d %H:%M}"


class TicketAttachment(SoftDeleteModel):
    ticket = models.ForeignKey(
        Ticket, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(upload_to=attachment_upload_to)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Attachment {self.original_filename or self.pk} on #{self.ticket_id}"


class TicketKbArticle(SoftDeleteModel):
    """Links a KB article to a ticket, for staff-curated associations and
    employee-marked "solved by article" feedback.

    A ticket can reference many KB articles; an article can be referenced by
    many tickets. The `helpful` flag records whether the requester said the
    article solved their issue (set by the requester, updated by them only).
    """
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="kb_articles")
    article = models.ForeignKey(
        "assets.KnowledgeBaseArticle", on_delete=models.CASCADE,
        related_name="linked_tickets")
    helpful = models.BooleanField(null=True, blank=True,
                                  help_text="Requester's 'solved by article' "
                                            "vote; null = not yet voted.")
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_kb_links",
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-linked_at"]
        unique_together = [("ticket", "article")]
        indexes = [
            models.Index(fields=["ticket"], name="ticket_kb_ticket_idx"),
            models.Index(fields=["article"], name="ticket_kb_article_idx"),
            models.Index(fields=["helpful"], name="ticket_kb_helpful_idx"),
        ]

    def __str__(self):
        return f"#{self.ticket_id} <-> KB#{self.article_id}"


class AutomationRule(SoftDeleteModel):
    """Ticket automation rule (workflows, Phase 19).

    A rule bundles a trigger (an event that starts evaluation), optional
    conditions (all must match for the ticket at that moment) and an
    ordered list of actions. Rules are evaluated when the trigger fires
    (see ``tickets.automation``); every evaluation that reaches the
    action list records a ``WorkflowExecution`` row.

    Structures are validated at the API layer (serializer); the model
    keeps plain JSON so managers/admin can inspect without parsing.
    """

    TRIGGER_CHOICES = [
        ("ticket_created", "Ticket created"),
        ("status_changed", "Status changed"),
        ("priority_changed", "Priority changed"),
        ("assignment_changed", "Assignee changed"),
        ("sla_breached", "SLA breached"),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    trigger = models.CharField(
        max_length=30, choices=TRIGGER_CHOICES, db_index=True)
    # [{"field": "priority", "operator": "equals", "value": "critical"}, ...]
    conditions = models.JSONField(default=list, blank=True)
    # [{"type": "add_note", "params": {"body": "...", "is_internal": True}}, ...]
    actions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="automation_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("manage_automationrule", "Can manage ticket automation rules"),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_trigger_display()})"


class TicketApproval(SoftDeleteModel):
    """Approval request for a sensitive ticket operation (Phase 19).

    Lifecycle: ``pending`` -> ``approved``/``rejected`` (terminal). The
    deciding user must differ from the requester, and a decision applies
    the requested operation to the ticket (approved) or leaves the ticket
    untouched (rejected). Approvals respect ticket visibility: employees
    see approvals on tickets they can already see.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    OPERATION_CHOICES = [
        ("change_priority", "Change priority"),
        ("change_status", "Change status"),
        ("reassign", "Reassign"),
    ]

    ticket = models.ForeignKey(
        Ticket, on_delete=models.PROTECT, related_name="approvals")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="approvals_requested",
    )
    operation = models.CharField(max_length=30, choices=OPERATION_CHOICES)
    # Shape depends on operation: {"priority": ...} / {"status": ...} /
    # {"user_id": ...}. Validated at the API layer.
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending",
        db_index=True)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="approvals_decided",
    )
    decision_comment = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["ticket"], name="approval_ticket_idx"),
            models.Index(fields=["requested_by"],
                         name="approval_requester_idx"),
        ]
        permissions = [
            ("decide_ticketapproval", "Can approve or reject ticket approvals"),
        ]

    def __str__(self):
        return (
            f"Approval #{self.pk} ticket #{self.ticket_id} "
            f"{self.operation} ({self.status})")

    @property
    def is_decided(self):
        return self.status != "pending"


class WorkflowExecution(SoftDeleteModel):
    """Record of one automation rule evaluation (execution history).

    One row per (rule, event) pair that reached the action list. Reads
    only, append via ``tickets.automation``.
    """

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failure", "Failure"),
    ]

    rule = models.ForeignKey(
        AutomationRule, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="executions")
    ticket = models.ForeignKey(
        Ticket, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="workflow_executions")
    trigger = models.CharField(max_length=30, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="success")
    # [{"field": ..., "operator": ..., "value": ...}, ...] as evaluated.
    matched_conditions = models.JSONField(default=list, blank=True)
    # Action outcome list eventually surfaced in detail views:
    # [{"type": ..., "result": ...}, ...]
    results = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["rule"], name="wexec_rule_idx"),
            models.Index(fields=["ticket"], name="wexec_ticket_idx"),
            models.Index(fields=["status"], name="wexec_status_idx"),
            models.Index(fields=["created_at"], name="wexec_created_idx"),
        ]

    def __str__(self):
        return (
            f"Execution #{self.pk} rule={self.rule_id} "
            f"ticket={self.ticket_id} ({self.status})")
