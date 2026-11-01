"""Assets domain: managed categories, assets, assignment + asset history.

Rules enforced:
- Category is a managed dropdown (FK, never free text). Deleting a category
  that still has assets is blocked with a clear message (PROTECT + view check).
- General asset updates NEVER silently overwrite assignment. Assignment
  changes go through the explicit assign/return endpoints which write history.
- Assignment + history rows are PROTECTed: hard deletion of an asset/user is
  blocked while history exists. Soft deletion never cascades.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from common.models import SoftDeleteModel


def _eligible(user):
    """An employee is assignable when active, not soft-deleted, and not a
    system-level account that should not hold assets."""
    return bool(
        user
        and user.is_active
        and not getattr(user, "is_deleted", False)
        and getattr(user, "role", "") != "system_admin"
    )


def asset_attachment_upload_to(instance, filename):
    """Safe filename: uuid + whitelisted extension, no user paths.

    Mirrors tickets.attachment_upload_to under a separate prefix so
    ticket and asset files never collide.
    """
    import os
    import uuid

    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    safe_ext = "".join(c for c in ext if c.isalnum())[:10]
    return f"asset_attachments/{uuid.uuid4().hex}" + (
        f".{safe_ext}" if safe_ext else "")


class AssetCategory(SoftDeleteModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("hard_delete_assetcategory", "Can permanently delete asset categories"),
            ("restore_assetcategory", "Can restore soft-deleted asset categories"),
        ]

    def __str__(self):
        return self.name


class Asset(SoftDeleteModel):
    STATUS_CHOICES = [
        ("available", "Available"),
        ("assigned", "Assigned"),
        ("in_repair", "In repair"),
        ("retired", "Retired"),
        ("lost", "Lost"),
        ("disposed", "Disposed"),
    ]

    asset_tag = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        AssetCategory, on_delete=models.PROTECT, related_name="assets"
    )
    # Optional (blank allowed, several blanks fine); non-blank values are
    # unique across ALL assets, including soft-deleted ones: a recycled
    # asset still reserves its serial so a restore can never collide.
    # Enforced twice: AssetSerializer.validate_serial_number (friendly
    # field error) and DB triggers in 0003 (concurrency backstop). Triggers
    # instead of a UNIQUE index because the live database already holds
    # duplicate serials that must be preserved (see 0003 report) - an index
    # could not be created over conflicting rows without deleting or
    # rewriting existing assets.
    serial_number = models.CharField(max_length=100, blank=True, default="")
    # Optional owning department. Nullable so legacy/unknown assets still
    # import cleanly; PROTECT keeps a department from being removed while
    # assets still reference it (deactivate instead).
    department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="available"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assets_assigned",
    )
    location = models.CharField(max_length=200, blank=True, default="")
    purchase_date = models.DateField(null=True, blank=True)
    warranty_expiry = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_tag"]
        permissions = [
            ("hard_delete_asset", "Can permanently delete assets"),
            ("restore_asset", "Can restore soft-deleted assets"),
            ("view_asset_history", "Can view asset history"),
            ("view_asset_maintenance", "Can view asset maintenance"),
            ("manage_asset_maintenance", "Can manage asset maintenance"),
            ("manage_asset_disposal", "Can manage asset disposal"),
        ]
        constraints = [
            # An assigned asset must have a holder.
            models.CheckConstraint(
                name="asset_assigned_requires_holder",
                condition=(
                    ~models.Q(status="assigned")
                    | models.Q(assigned_to__isnull=False)
                ),
            ),
            # A retired, lost, or disposed asset cannot have a holder.
            models.CheckConstraint(
                name="asset_ineligible_no_holder",
                condition=(
                    ~models.Q(status__in=["retired", "lost", "disposed"])
                    | models.Q(assigned_to__isnull=True)
                ),
            ),
        ]

    def clean(self):
        """Asset + assignment consistency rules.

        - An asset may only be ``assigned`` when it has a holder and an open
          (not-yet-returned) assignment.
        - A holder implies ``assigned`` status.
        - Retired / lost / disposed assets cannot be assigned.
        """
        super().clean()
        if self.status == "assigned" and not self.assigned_to_id:
            raise ValidationError(
                {"status": "An assigned asset must have a holder.",
                 "assigned_to": "Set a holder to mark the asset assigned."})
        if self.assigned_to_id and self.status != "assigned":
            raise ValidationError(
                {"assigned_to": "A holder requires status 'assigned'.",
                 "status": "Set status 'assigned' when assigning a holder."})
        if self.status in ("retired", "lost", "disposed") and self.assigned_to_id:
            raise ValidationError(
                {"assigned_to": f"A {self.get_status_display()} asset cannot "
                                "have a holder.",
                 "status": f"Clear the holder before setting status "
                           f"'{self.status}'."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset_tag} - {self.name}"

    @property
    def has_open_maintenance(self):
        """True when the asset has a maintenance that is not yet completed
        or cancelled (i.e. scheduled / in-progress / overdue)."""
        return self.maintenance.filter(
            status__in=["scheduled", "in_progress", "overdue"]).exists()

    @property
    def upcoming_maintenance(self):
        """Earliest upcoming (not completed/cancelled) maintenance, if any."""
        return self.maintenance.filter(
            status__in=["scheduled", "in_progress", "overdue"]).order_by(
                "scheduled_date", "id").first()


class Maintenance(SoftDeleteModel):
    """Maintenance record for an asset.

    Lifecycle: scheduled -> in_progress -> completed, or cancelled. A
    maintenance whose scheduled date passes without completion is treated
    as overdue (computed via ``is_overdue``; the status may also be set to
    ``overdue`` explicitly).
    """

    MAINTENANCE_TYPE_CHOICES = [
        ("preventive", "Preventive"),
        ("corrective", "Corrective"),
        ("inspection", "Inspection"),
        ("upgrade", "Upgrade"),
        ("cleaning", "Cleaning"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("in_progress", "In progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("overdue", "Overdue"),
    ]

    RENEWAL_CHOICES = [
        ("none", "One‑off"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
    ]

    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="maintenance")
    title = models.CharField(max_length=200)
    maintenance_type = models.CharField(
        max_length=20, choices=MAINTENANCE_TYPE_CHOICES, default="preventive")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="scheduled")
    scheduled_date = models.DateTimeField()
    start_date = models.DateTimeField(null=True, blank=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_tasks",
        help_text="Technician / responsible employee.",
    )
    vendor = models.CharField(
        max_length=200, blank=True, default="",
        help_text="External service provider, where applicable.")
    cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    resolution_notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    recurrence = models.CharField(
        max_length=10, choices=RENEWAL_CHOICES, default="none",
        help_text="Repeats the maintenance schedule when set.")

    class Meta:
        ordering = ["-scheduled_date", "-id"]
        permissions = [
            ("manage_asset_maintenance", "Can manage asset maintenance"),
        ]

    def __str__(self):
        return f"{self.asset.asset_tag} - {self.title} ({self.status})"

    @property
    def is_overdue(self):
        if self.status in ("completed", "cancelled"):
            return False
        if not self.scheduled_date:
            return False
        from django.utils import timezone
        return timezone.now() > self.scheduled_date


class MaintenanceReminder(models.Model):
    """Track maintenance reminders to avoid duplicate notifications.

    One record per (maintenance, level) ensures we only fire a given notification
    type once per maintenance item until the state changes.
    """
    LEVEL_CHOICES = (
        ("before", "Before scheduled date"),
        ("overdue", "Overdue notification"),
    )

    maintenance = models.ForeignKey(
        Maintenance, on_delete=models.CASCADE, related_name="reminders")
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("maintenance", "level")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Maint #{self.maintenance_id} {self.level}"


class KnowledgeBaseCategory(models.Model):
    """Category for knowledge‑base articles."""
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=50, unique=True, help_text="Short identifier, used in URLs.")
    description = models.TextField(blank=True, default="")
    is_published = models.BooleanField(default=True, help_text="Visible to employees in the portal.")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="kb_categories_created")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class KnowledgeBaseTag(models.Model):
    """Tag for knowledge‑base articles."""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class KnowledgeBaseArticle(models.Model):
    """A knowledge‑base article that employees can browse and search."""
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("published", "Published"),
        ("archived", "Archived"),
    )

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    category = models.ForeignKey(
        KnowledgeBaseCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="articles")
    tags = models.ManyToManyField(
        KnowledgeBaseTag, blank=True, related_name="articles")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="kb_articles_authored")
    content = models.TextField(
        help_text="Rich but controlled article content (markdown‑style, no HTML).")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="published")
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def increment_view(self):
        """Atomically increment the view counter."""
        KnowledgeBaseArticle.objects.filter(pk=self.pk).update(view_count=F("view_count") + 1)


class Disposal(SoftDeleteModel):
    """Asset disposal record.

    Disposal is a distinct lifecycle event from retirement or marking an
    asset lost. A disposed asset must have its assignment resolved first
    (holder cleared / open assignment closed) and cannot be assigned
    afterwards. Disposal requires approval before completion.
    """

    DISPOSAL_METHOD_CHOICES = [
        ("recycled", "Recycled"),
        ("donated", "Donated"),
        ("sold", "Sold"),
        ("scrapped", "Scrapped"),
        ("returned_to_vendor", "Returned to vendor"),
        ("other", "Other"),
    ]

    APPROVAL_STATUS_CHOICES = [
        ("pending", "Pending approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="disposals")
    disposal_date = models.DateTimeField(null=True, blank=True)
    disposal_reason = models.TextField()
    disposal_method = models.CharField(
        max_length=30, choices=DISPOSAL_METHOD_CHOICES, default="other")
    disposal_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    responsible_person = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="disposals_responsible",
        help_text="Person carrying out the disposal.")
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_STATUS_CHOICES, default="pending")
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="disposals_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="disposals_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        permissions = [
            ("manage_asset_disposal", "Can manage asset disposal"),
        ]

    def __str__(self):
        return f"{self.asset.asset_tag} disposal ({self.approval_status})"

    @property
    def is_completed(self):
        return bool(self.disposal_date)

    def clean(self):
        super().clean()
        if self.approval_status in ("approved", "rejected") and not self.approver:
            raise ValidationError(
                {"approver": "An approver is required when approval is "
                             "not pending."})
        if self.disposal_date and self.approval_status != "approved":
            raise ValidationError(
                {"disposal_date": "A disposal date can only be set once the "
                                  "disposal is approved."})


class Assignment(models.Model):
    """Assignment history. Survives employee deactivation + asset retirement."""

    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignments_received",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignments_given",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            # An open (not-yet-returned) assignment must name a holder.
            models.CheckConstraint(
                name="assignment_open_requires_holder",
                condition=(
                    models.Q(returned_at__isnull=False)
                    | models.Q(assigned_to__isnull=False)
                ),
            ),
        ]

    def clean(self):
        """One open assignment per asset; eligible, active employee only."""
        super().clean()
        # The employee must exist and be eligible.
        if self.assigned_to_id and not _eligible(self.assigned_to):
            raise ValidationError(
                {"assigned_to": "Choose an active, non-deleted employee."})
        # The asset must exist, not be soft-deleted, and be assignable.
        if self.asset_id:
            try:
                asset = Asset.all_objects.get(pk=self.asset_id)
            except Asset.DoesNotExist:
                asset = None
            if asset is None:
                raise ValidationError({"asset": "Unknown asset."})
            if asset.is_deleted:
                raise ValidationError(
                    {"asset": "Cannot assign a soft-deleted asset."})
            if asset.status in ("retired", "lost"):
                raise ValidationError(
                    {"asset": f"Cannot assign a {asset.get_status_display()} "
                             "asset."})
            # Only one open (unreturned) assignment per asset.
            open_q = asset.assignments.filter(returned_at__isnull=True)
            if self.pk:
                open_q = open_q.exclude(pk=self.pk)
            if open_q.exists():
                holder = open_q.first().assigned_to
                raise ValidationError(
                    {"asset": f"Asset already assigned to "
                             f"{holder.employee_id if holder else '?'}; "
                             f"return it first."})
        # An open assignment requires a holder.
        if self.returned_at is None and not self.assigned_to_id:
            raise ValidationError(
                {"assigned_to": "An open assignment needs a holder."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        who = self.assigned_to or "—"
        return f"{self.asset_id} -> {who} @ {self.assigned_at:%Y-%m-%d}"


class AssetAssignment(models.Model):
    """Asset assignment change record."""

    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="asset_assignments")
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="asset_assignments_employee")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="asset_assignments_given")
    note = models.TextField(blank=True, default="")
    effective_from = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.asset.asset_tag} assigned to {self.employee_id}"


class AssetHistory(models.Model):
    """Append-only asset change log. Not editable/deletable via API."""

    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="history"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_history_entries",
    )
    action = models.CharField(max_length=40)  # created/updated/status_change/...
    timestamp = models.DateTimeField(auto_now_add=True)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["timestamp"]
        permissions = [
            ("view_asset_history", "Can view asset history"),
        ]

    def __str__(self):
        return f"{self.asset_id} {self.action} by {self.actor} @ {self.timestamp:%Y-%m-%d %H:%M}"


class AssetAttachment(SoftDeleteModel):
    """Private asset files. Same lifecycle as TicketAttachment.

    - UUID storage names under asset_attachments/ (no traversal).
    - Soft delete keeps the bytes; restore re-exposes them.
    - Permanent deletion unlinks the file only when no retained record
      still references the same stored file (see recycle-bin flow).
    """

    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(upload_to=asset_attachment_upload_to)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Attachment {self.original_filename or self.pk} on {self.asset_id}"
