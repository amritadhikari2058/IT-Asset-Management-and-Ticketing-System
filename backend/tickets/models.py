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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
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
