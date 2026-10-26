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
from django.db import models

from common.models import SoftDeleteModel


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
        ]

    def __str__(self):
        return f"{self.asset_tag} - {self.name}"


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

    def __str__(self):
        who = self.assigned_to or "—"
        return f"{self.asset_id} -> {who} @ {self.assigned_at:%Y-%m-%d}"


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
