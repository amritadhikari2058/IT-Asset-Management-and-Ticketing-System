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

from common.models import SoftDeleteManager, SoftDeleteModel


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
        ("waiting_requester", "Waiting for Requester"),
        ("waiting_third_party", "Waiting for Third Party"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
        ("reopened", "Reopened"),
        ("cancelled", "Cancelled"),
        ("merged", "Merged"),
        ("archived", "Archived"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    # Statuses that are considered terminal / non-operational for SLA and
    # workload calculations.
    TERMINAL_STATUSES = frozenset({"resolved", "closed", "archived", "cancelled", "merged"})
    # Statuses where the SLA clock should not be running.
    SLA_PAUSED_STATUSES = frozenset({"waiting_requester", "waiting_third_party"})

    # Allowed next statuses per current status (bulk validates each ticket).
    VALID_TRANSITIONS = {
        "open": {"in_progress", "waiting_requester", "waiting_third_party",
                 "resolved", "closed", "cancelled", "merged", "archived"},
        "in_progress": {"waiting_requester", "waiting_third_party", "resolved",
                        "closed", "cancelled", "merged", "open", "archived"},
        "waiting_requester": {"in_progress", "resolved", "cancelled", "merged"},
        "waiting_third_party": {"in_progress", "waiting_requester", "resolved",
                                "closed", "cancelled", "merged"},
        "resolved": {"closed", "reopened", "merged"},
        "closed": {"reopened", "archived", "merged"},
        "reopened": {"in_progress", "resolved", "closed"},
        "cancelled": set(),
        "merged": set(),
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
    # Queue routing
    queue = models.ForeignKey(
        "TicketQueue", null=True, blank=True,
        on_delete=models.PROTECT, related_name="tickets",
        help_text="Support queue holding this ticket.",
    )
    # Parent-child relationships
    parent_ticket = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.PROTECT, related_name="child_tickets",
        help_text="Parent ticket when this is a child ticket.",
    )
    merged_into = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="merged_duplicates",
        help_text="Primary ticket this ticket was merged into (status merged).",
    )
    # Resolution
    resolution_code = models.ForeignKey(
        "TicketResolutionCode", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resolved_tickets",
        help_text="Code used when the ticket was resolved.",
    )
    resolution_summary = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resolved_tickets_by",
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reopened_tickets_by",
        help_text="User who reopened this ticket.")
    reopen_count = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
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
            models.Index(fields=["queue"], name="ticket_queue_idx"),
            models.Index(fields=["parent_ticket"], name="ticket_parent_idx"),
            models.Index(fields=["merged_into"], name="ticket_merged_into_idx"),
            models.Index(fields=["resolved_at"], name="ticket_resolved_at_idx"),
            models.Index(fields=["closed_at"], name="ticket_closed_at_idx"),
            models.Index(fields=["reopened_at"], name="ticket_reopened_at_idx"),
            # Composite index for dashboard summary queries: status + priority + assignee
            models.Index(
                fields=["status", "priority", "assignee"],
                name="ticket_status_prio_assignee",
            ),
            # Composite index for recent ticket queries: status + created_at
            models.Index(
                fields=["status", "created_at"],
                name="ticket_status_created_at_idx",
            ),
            # Composite index for requester-scoped queries
            models.Index(
                fields=["requester", "status"],
                name="ticket_requester_status_idx",
            ),
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

    def get_paused_duration(self, as_of=None):
        """Total paused time for this ticket.

        Completed pause intervals are counted once. An active pause is
        counted up to ``as_of`` (defaults to now). Overlapping intervals
        are merged so they cannot be double-counted.
        """
        from django.utils import timezone

        if as_of is None:
            as_of = timezone.now()

        intervals = []
        for pause in self.sla_pauses.filter(is_deleted=False):
            start = pause.started_at
            end = pause.ended_at if pause.ended_at is not None else as_of
            if end < start:
                end = start
            intervals.append((start, end))

        intervals.sort()
        total = timedelta()
        current_start = None
        current_end = None
        for start, end in intervals:
            if current_end is None or start > current_end:
                if current_end is not None:
                    total += current_end - current_start
                current_start, current_end = start, end
            else:
                current_end = max(current_end, end)
        if current_end is not None:
            total += current_end - current_start
        return total

    def get_sla_due_at(self):
        """Effective SLA deadline after accounting for paused time.
        
        This is the authoritative calculation that considers:
        - The original sla_due_at
        - All completed pause intervals
        - Any currently active pause interval (counted up to now)
        - Multiple pause/resume cycles
        - Overlapping intervals (merged, no double-counting)
        - Tickets with no pause records (returns sla_due_at)
        - Tickets with null sla_due_at (returns None)
        """
        if not self.sla_due_at:
            return None
        return self.sla_due_at + self.get_paused_duration()

    def get_effective_sla_due_at(self):
        """Alias for ``get_sla_due_at`` for clarity in consumer code.
        
        Use ``get_sla_due_at`` or ``get_effective_sla_due_at`` interchangeably;
        both compute the effective deadline by adding accumulated paused
        duration to the persisted ``sla_due_at``.
        """
        return self.get_sla_due_at()

    def update_sla_due_on_priority_change(self, old_priority=None):
        """Recompute the persisted SLA deadline for a changed priority.

        The persisted value remains the unpaused base deadline; paused time
        is applied dynamically by ``get_sla_due_at``. This method preserves
        the accumulated pause time so the effective deadline remains correct
        after the priority change.

        - A priority change must use the applicable SLA configuration.
        - Existing pause history must not be lost.
        - The effective deadline must remain correct.
        - Unchanged priorities must not trigger unnecessary recalculation.
        """
        sla = self.priority_sla
        if not sla or not self.pk:
            return

        # Only recalculate if the priority actually changed.
        # old_priority is passed in by save() to avoid re-fetching from the
        # DB after the new priority has already been persisted, which would
        # make the comparison always equal (new == new) and silently skip
        # SLA recalculation.
        if old_priority is not None and old_priority == self.priority:
            return

        # A priority change starts a fresh SLA clock for the new priority.
        # Paused time accumulated so far remains applicable dynamically via
        # get_sla_due_at(); the persisted value is the unpaused base deadline.
        self.sla_due_at = timezone.now() + timedelta(
            hours=sla.target_resolution_hours)
        self.save(update_fields=["sla_due_at", "updated_at"])

    def save(self, *args, **kwargs):
        old_status = None
        old_priority = None
        if self.pk:
            try:
                old = Ticket.objects.only("status", "priority").get(pk=self.pk)
                old_status = old.status
                old_priority = old.priority
            except Ticket.DoesNotExist:
                old_status = None
                old_priority = None
        super().save(*args, **kwargs)

        WAITING = {"waiting_requester", "waiting_third_party"}
        leaving = bool(old_status in WAITING and self.status not in WAITING)
        if leaving:
            TicketSlaPause.objects.filter(
                ticket=self, ended_at__isnull=True, is_deleted=False
            ).update(ended_at=timezone.now())

        if old_priority is not None and old_priority != self.priority:
            self.update_sla_due_on_priority_change(old_priority)

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
    SLA deadline (breach threshold).  When null, the default is 80ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¯% of
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
    source_message_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Message-ID of the inbound email this note came from",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_message_id"],
                condition=models.Q(source_message_id__gt=""),
                name="uniq_ticketnote_source_message",
            ),
        ]

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
    content_hash = models.CharField(
        max_length=64, blank=True, default="",
        help_text="SHA-256 hex digest of the attachment content for deduplication"
    )
    # Stable inbound source identity for true idempotent retries. These are
    # set for email-ingested attachments and left blank/null for manual uploads
    # and legacy rows created before this field existed.
    source_message_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True,
        help_text="Message-ID of the inbound email this attachment came from"
    )
    source_part_index = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Deterministic MIME attachment ordinal within the source email"
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["source_message_id", "source_part_index"],
                condition=(
                    models.Q(source_message_id__gt="")
                    & models.Q(source_part_index__isnull=False)
                ),
                name="uniq_ticketattach_source_part",
            ),
        ]

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


class TicketQueue(SoftDeleteModel):
    """Support queue that owns/holds tickets awaiting or in work.

    Queues route unassigned tickets, group members, and drive assignment
    strategies. Deactivation (not deletion) is preferred; deletion is
    blocked while active tickets reference the queue.
    """

    ASSIGNMENT_STRATEGY_CHOICES = [
        ("manual", "Manual"),
        ("round_robin", "Round Robin"),
        ("least_open_tickets", "Least Open Tickets"),
        ("category_owner", "Category Owner"),
        ("department_queue", "Department Queue"),
    ]

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=40, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    department = models.ForeignKey(
        "accounts.Department",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_queues",
        help_text="Optional: restricts queue to a department; null = cross-department IT queue.",
    )
    default_category = models.ForeignKey(
        "tickets.TicketCategory",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="queues_defaulting_here",
    )
    default_priority = models.CharField(
        max_length=20, choices=Ticket.PRIORITY_CHOICES, blank=True, default=""
    )
    is_active = models.BooleanField(default=True)
    email_address = models.EmailField(blank=True, default="")
    assignment_strategy = models.CharField(
        max_length=30, choices=ASSIGNMENT_STRATEGY_CHOICES, default="manual"
    )
    allow_self_claim = models.BooleanField(default=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_queues",
        help_text="Active IT Manager or System Admin.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_queues",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"], name="queue_code_idx"),
            models.Index(fields=["is_active", "department"], name="queue_active_dept_idx"),
            models.Index(fields=["manager"], name="queue_manager_idx"),
        ]
        permissions = [
            ("manage_ticketqueue", "Can manage ticket queues and memberships"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.manager_id and not self._manager_eligible(self.manager):
            raise ValidationError(
                {"manager": "Queue manager must be an active IT Manager or System Admin."}
            )

    @staticmethod
    def _manager_eligible(user):
        if user is None or not getattr(user, "pk", None):
            return False
        role = getattr(user, "role", "")
        return bool(
            getattr(user, "is_active", False)
            and not getattr(user, "is_deleted", False)
            and (role in ("system_admin", "it_manager") or getattr(user, "is_superuser", False))
        )


class TicketQueueMembership(SoftDeleteModel):
    """Links an IT staff member to a queue with a role and capabilities."""

    ROLE_CHOICES = [
        ("manager", "Queue Manager"),
        ("agent", "Agent"),
        ("observer", "Observer"),
    ]

    queue = models.ForeignKey(
        TicketQueue, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="queue_memberships",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    can_claim = models.BooleanField(default=True)
    can_assign_others = models.BooleanField(default=False)
    can_view_all = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["queue", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["queue", "user"],
                condition=models.Q(is_deleted=False, is_active=True),
                name="one_active_membership_per_queue_user",
            ),
        ]
        indexes = [
            models.Index(fields=["queue", "is_active"], name="membership_queue_active_idx"),
            models.Index(fields=["user", "is_active"], name="membership_user_active_idx"),
            models.Index(fields=["role"], name="membership_role_idx"),
        ]

    def __str__(self):
        return f"{self.user} -> {self.queue} ({self.role})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.user_id and not self._staff_eligible(self.user):
            raise ValidationError(
                {"user": "Only active IT staff can be queue members."}
            )
        if self.role == "observer" and (self.can_claim or self.can_assign_others):
            raise ValidationError(
                {"role": "Observer cannot claim or assign others."}
            )

    @staticmethod
    def _staff_eligible(user):
        if user is None or not getattr(user, "pk", None):
            return False
        role = getattr(user, "role", "")
        return bool(
            getattr(user, "is_active", False)
            and not getattr(user, "is_deleted", False)
            and (role in ("system_admin", "it_manager", "it_support")
                 or getattr(user, "is_superuser", False))
        )


class TicketWatcher(SoftDeleteModel):
    """A user subscribed to ticket updates without being the assignee."""

    WATCH_TYPE_CHOICES = [
        ("watcher", "Watcher"),
        ("follower", "Follower"),
        ("requester_delegate", "Requester Delegate"),
        ("manager", "Manager"),
    ]

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="watchers"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_watches",
    )
    watch_type = models.CharField(max_length=30, choices=WATCH_TYPE_CHOICES, default="watcher")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="added_watches",
    )
    is_active = models.BooleanField(default=True)
    muted_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "user"],
                condition=models.Q(is_deleted=False, is_active=True),
                name="one_active_watcher_per_ticket_user",
            ),
        ]
        indexes = [
            models.Index(fields=["ticket", "is_active"], name="watcher_ticket_active_idx"),
            models.Index(fields=["user", "is_active"], name="watcher_user_active_idx"),
            models.Index(fields=["muted_until"], name="watcher_muted_until_idx"),
        ]

    def __str__(self):
        return f"{self.user} watches #{self.ticket_id} ({self.watch_type})"

    def is_muted(self):
        from django.utils import timezone
        return bool(self.muted_until and timezone.now() < self.muted_until)


class CannedResponse(SoftDeleteModel):
    """Approved standard reply template usable on ticket notes."""

    VISIBILITY_CHOICES = [
        ("public_reply", "Public Reply"),
        ("internal_note", "Internal Note"),
        ("both", "Both"),
    ]

    title = models.CharField(max_length=200)
    code = models.CharField(max_length=60, unique=True, blank=True, default="")
    body = models.TextField(help_text="Plain text or safely validated limited markup.")
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="internal_note")
    category = models.CharField(max_length=100, blank=True, default="")
    queue = models.ForeignKey(
        TicketQueue, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="canned_responses"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="canned_responses",
    )
    is_shared = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_canned_responses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["is_active", "is_shared"], name="canned_active_shared_idx"),
            models.Index(fields=["owner"], name="canned_owner_idx"),
            models.Index(fields=["queue"], name="canned_queue_idx"),
            models.Index(fields=["category"], name="canned_category_idx"),
        ]

    def __str__(self):
        return self.title


class TicketTemplate(SoftDeleteModel):
    """Template that pre-fills a new ticket from a standard pattern."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=60, unique=True, blank=True, default="")
    title_template = models.CharField(max_length=255)
    description_template = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        TicketCategory, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="templates"
    )
    queue = models.ForeignKey(
        TicketQueue, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="templates"
    )
    priority = models.CharField(max_length=20, choices=Ticket.PRIORITY_CHOICES, blank=True, default="")
    default_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="default_templates"
    )
    default_status = models.CharField(max_length=20, blank=True, default="open")
    required_asset = models.BooleanField(default=False)
    note_templates = models.JSONField(default=list, blank=True,
                                      help_text="List of {title, body, is_internal} note previews.")
    custom_fields = models.JSONField(default=dict, blank=True,
                                     help_text="Allowlisted bounded custom field values.")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_templates",
    )
    is_shared = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_ticket_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "is_shared"], name="template_active_shared_idx"),
            models.Index(fields=["owner"], name="template_owner_idx"),
            models.Index(fields=["category"], name="template_category_idx"),
        ]

    def __str__(self):
        return self.name


class TicketRelation(SoftDeleteModel):
    RELATION_TYPE_CHOICES = [
        ("related", "Related"),
        ("duplicate", "Duplicate"),
        ("parent", "Parent"),
        ("child", "Child"),
        ("caused_by", "Caused By"),
        ("blocks", "Blocks"),
        ("blocked_by", "Blocked By"),
        ("follow_up", "Follow Up"),
    ]

    source_ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="relations_as_source"
    )
    target_ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="relations_as_target"
    )
    relation_type = models.CharField(max_length=20, choices=RELATION_TYPE_CHOICES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_ticket_relations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_ticket", "target_ticket", "relation_type"],
                name="unique_relation_pair_type",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_ticket=models.F("target_ticket")),
                name="relation_no_self_reference",
            ),
        ]
        indexes = [
            models.Index(fields=["source_ticket"], name="relation_source_idx"),
            models.Index(fields=["target_ticket"], name="relation_target_idx"),
            models.Index(fields=["relation_type"], name="relation_type_idx"),
        ]

    def __str__(self):
        return f"#{self.source_ticket_id} {self.relation_type} -> #{self.target_ticket_id}"


class TicketMergeRecord(SoftDeleteModel):
    """Immutable record of a ticket merged into a primary ticket."""

    primary_ticket = models.ForeignKey(
        Ticket, on_delete=models.PROTECT, related_name="merge_records_as_primary"
    )
    merged_ticket = models.ForeignKey(
        Ticket, on_delete=models.PROTECT, related_name="merge_records_as_merged"
    )
    merged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="performed_merges",
    )
    merged_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()
    merge_summary = models.TextField(blank=True, default="")
    transferred_notes_count = models.PositiveIntegerField(default=0)
    transferred_attachments_count = models.PositiveIntegerField(default=0)
    transferred_watchers_count = models.PositiveIntegerField(default=0)
    previous_status = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-merged_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["merged_ticket"],
                name="one_merge_record_per_merged_ticket",
            ),
            models.CheckConstraint(
                condition=~models.Q(primary_ticket=models.F("merged_ticket")),
                name="merge_no_self_merge",
            ),
        ]
        indexes = [
            models.Index(fields=["primary_ticket"], name="mergerecord_primary_idx"),
            models.Index(fields=["merged_ticket"], name="mergerecord_merged_idx"),
        ]

    def __str__(self):
        return f"#{self.merged_ticket_id} -> #{self.primary_ticket_id}"


class TicketSlaPause(SoftDeleteModel):
    """Interval during which a ticket's SLA clock is paused."""

    PAUSE_TYPE_CHOICES = [
        ("waiting_requester", "Waiting for Requester"),
        ("waiting_third_party", "Waiting for Third Party"),
        ("approved_hold", "Approved Hold"),
    ]

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="sla_pauses"
    )
    reason = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="started_sla_pauses",
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="ended_sla_pauses",
    )
    pause_type = models.CharField(max_length=30, choices=PAUSE_TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["ticket", "started_at"], name="sla_pause_ticket_idx"),
            models.Index(fields=["pause_type"], name="sla_pause_type_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket"],
                condition=models.Q(ended_at__isnull=True, is_deleted=False),
                name="uniq_active_sla_pause_per_ticket",
            )
        ]

    def __str__(self):
        return f"#{self.ticket_id} pause {self.pause_type} @ {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def duration(self):
        if not self.started_at:
            return None
        end = self.ended_at
        if end is None:
            return None
        return end - self.started_at




class TicketResolutionCode(SoftDeleteModel):
    """Admin-managed code used when resolving a ticket."""

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=60, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)
    requires_summary = models.BooleanField(default=True)
    requires_kb_link = models.BooleanField(default=False)
    marks_known_error = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_resolution_codes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "category"], name="resolutioncode_active_cat_idx"),
        ]

    def __str__(self):
        return self.name


class TicketSatisfactionSurvey(SoftDeleteModel):
    """Requester satisfaction survey offered after ticket resolution/closure."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("submitted", "Submitted"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ]

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="satisfaction_surveys"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_satisfaction_surveys",
    )
    token_hash = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    resolution_helpful = models.BooleanField(null=True, blank=True)
    response_time_satisfied = models.BooleanField(null=True, blank=True)
    communication_satisfied = models.BooleanField(null=True, blank=True)
    comments = models.TextField(blank=True, default="")
    offered_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-offered_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "requester"],
                condition=models.Q(is_deleted=False, status="pending"),
                name="one_active_survey_per_ticket_requester",
            ),
        ]
        indexes = [
            models.Index(fields=["ticket", "status"], name="survey_ticket_status_idx"),
            models.Index(fields=["requester", "status"], name="survey_requester_status_idx"),
            models.Index(fields=["expires_at", "status"], name="survey_expiry_idx"),
        ]

    def __str__(self):
        return f"Survey #{self.ticket_id} for {self.requester_id} ({self.status})"


class SavedTicketView(SoftDeleteModel):
    """User-saved ticket filter view with validated filters/ordering/columns."""

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_ticket_views",
    )
    description = models.TextField(blank=True, default="")
    filters = models.JSONField(default=dict, blank=True,
                               help_text="Validated filter key/operator/value JSON.")
    ordering = models.CharField(max_length=200, blank=True, default="")
    columns = models.JSONField(default=list, blank=True,
                               help_text="Allowlisted columns to return.")
    is_shared = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner"],
                condition=models.Q(is_deleted=False, is_default=True),
                name="one_default_view_per_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "is_default"], name="savedview_owner_default_idx"),
            models.Index(fields=["is_shared"], name="savedview_shared_idx"),
        ]

    def __str__(self):
        return self.name


class TicketBulkImportOperation(models.Model):
    """Tracks a ticket bulk-import operation for idempotent preview/confirm.

    Scoped to (user, token) so a client can safely retry the same operation
    (e.g. lost response) without duplicating tickets, while different users and
    intentionally separate imports remain isolated.
    """

    STATUS_PREVIEWED = "previewed"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PREVIEWED, "Previewed"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_bulk_import_operations",
    )
    token = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PREVIEWED)
    request_fingerprint = models.CharField(max_length=128, blank=True, default="")
    preview_payload = models.JSONField(default=dict, blank=True)
    result_format = models.CharField(max_length=10, blank=True, default="")
    result_json = models.JSONField(null=True, blank=True)
    result_csv = models.TextField(blank=True, default="")
    result_status_code = models.PositiveSmallIntegerField(default=200)
    error_detail = models.TextField(blank=True, default="")
    total_rows = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    successful_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "token"],
                name="uniq_tbi_user_token",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "created_at"],
                         name="tbi_user_created_idx"),
            models.Index(fields=["expires_at"],
                         name="tbi_expires_idx"),
        ]

    def __str__(self):
        return f"Ticket bulk import {self.token} ({self.user_id}, {self.status})"

    @property
    def is_expired(self):
        return bool(self.expires_at and timezone.now() >= self.expires_at)


class TicketBulkImportRowOutcome(models.Model):
    """Durable per-row outcome for a tokenized ticket bulk import.

    For operations using this tracking mechanism, a successful outcome and its
    committed ticket/required transactional writes are recorded atomically in
    the same per-row transaction. Legacy operations created before row-level
    tracking may have no outcomes and cannot be fully reconstructed.
    """

    OUTCOME_SUCCEEDED = "succeeded"
    OUTCOME_FAILED = "failed"
    OUTCOME_CHOICES = [
        (OUTCOME_SUCCEEDED, "Succeeded"),
        (OUTCOME_FAILED, "Failed"),
    ]

    operation = models.ForeignKey(
        TicketBulkImportOperation,
        on_delete=models.CASCADE,
        related_name="row_outcomes",
    )
    row_index = models.PositiveIntegerField(
        help_text="0-based index in the normalized import row sequence.")
    row_number = models.PositiveIntegerField(
        help_text="1-based row number reported by the import API.")
    row_fingerprint = models.CharField(
        max_length=64, blank=True, default="",
        help_text="SHA-256 of the canonical normalized row payload (evidence only).")
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES)
    ticket = models.ForeignKey(
        "tickets.Ticket",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="bulk_import_row_outcomes",
    )
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["operation", "row_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "row_index"],
                name="uniq_tbi_row_outcome_op_idx",
            ),
            models.CheckConstraint(
                condition=models.Q(row_number__gte=1),
                name="tbi_row_outcome_row_number_gte_1",
            ),
        ]
        indexes = [
            models.Index(fields=["operation", "outcome"],
                         name="tbi_row_outcome_op_out_idx"),
            models.Index(fields=["ticket"],
                         name="tbi_row_outcome_ticket_idx"),
        ]

    def __str__(self):
        return (f"Ticket bulk import row {self.operation_id}:{self.row_index} "
                f"({self.outcome})")