"""Shared soft-deletion infrastructure + protected audit log.

Policy enforced here (code-level):
- Normal ``delete()`` / ``QuerySet.delete()`` NEVER hard-deletes.
  It only flips ``is_deleted`` and stores deletion metadata.
- Real removal is ONLY via ``hard_delete()`` and MUST be gated by the
  System-Admin-only permission at the view layer (see tickets/assets/
  accounts views + recycle-bin API). This model layer intentionally does
  NOT check roles so tests/scripts can call it directly; views enforce.
- Soft deletion never cascades: related tickets/assets/history are kept.
  Hard deletion is blocked by PROTECT FKs when history exists.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """Default queryset hides soft-deleted rows."""

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    def soft_delete(self, by_user=None, reason=""):
        """Bulk soft-delete without loading rows one by one."""
        return self.alive().update(
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by=by_user,
            deletion_reason=reason or "",
        )

    def delete(self):
        """Override: bulk QuerySet.delete() soft-deletes instead of removing."""
        return self.soft_delete()

    def hard_delete(self):
        """Real bulk removal. Call ONLY from System-Admin recycle-bin flow."""
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Default manager: ordinary queries exclude deleted records."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            is_deleted=False
        )

    def with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            is_deleted=True
        )


class SoftDeleteModel(models.Model):
    """Abstract base adding consistent soft-deletion fields.

    Concrete models get:
      objects      -> hides deleted (use everywhere operationally)
      all_objects  -> includes deleted (recycle bin / admin only)
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted",
    )
    deletion_reason = models.TextField(blank=True, default="")

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self, by_user=None, reason=""):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.deletion_reason = reason or ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def restore(self):
        """Restore preserving PK + history. Callers validate FKs/uniqueness."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.deletion_reason = ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def delete(self, using=None, keep_parents=False, by_user=None, reason=""):
        """Single-object delete() soft-deletes. Never hard-deletes."""
        self.soft_delete(
            by_user=by_user if hasattr(by_user, "pk") else None,
            reason=reason or "",
        )
        return (1, {self._meta.label: 1})

    def hard_delete(self, using=None, keep_parents=False):
        """Real removal. Views must enforce System-Admin-only + audit."""
        return super().delete(using=using, keep_parents=keep_parents)


class AuditLog(models.Model):
    """Protected, append-only log. NEVER soft-deleted, NEVER edited via API.

    ``object_id`` is a string so the log survives hard deletion of the target.
    """

    ACTION_CHOICES = [
        ("create", "Create"),
        ("update", "Update"),
        ("soft_delete", "Soft delete"),
        ("restore", "Restore"),
        ("hard_delete", "Permanent delete"),
        ("bulk_create", "Bulk create"),
        ("bulk_update", "Bulk update"),
        ("bulk_soft_delete", "Bulk soft delete"),
        ("status_change", "Status change"),
        ("assignment", "Assignment change"),
        ("deactivate", "Deactivate"),
        ("reactivate", "Reactivate"),
        ("retire", "Retire"),
        ("note", "Note / comment"),
        ("password_reset", "Password reset"),
        ("export", "Export"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=100)  # e.g. "tickets.Ticket"
    object_id = models.CharField(max_length=100)
    object_repr = models.CharField(max_length=255, blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    reason = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        permissions = [
            ("view_audit_logs", "Can view audit logs"),
        ]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.actor} {self.action} {self.entity_type}:{self.object_id}"


class Notification(SoftDeleteModel):
    """In-app notification. Soft-deletable; never hard-deleted except by Admin."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    is_read = models.BooleanField(default=False)
    entity_type = models.CharField(max_length=100, blank=True, default="")
    object_id = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"To {self.recipient_id}: {self.title[:60]}"


class PrivacyErasureRequest(models.Model):
    """System-Admin-only privacy erasure workflow (initial version).

    Not a GDPR-compliance claim. Flow: create (reason + scope + confirm) ->
    review dependencies/retention -> execute or reject. The audit log records
    request + outcome WITHOUT the erased personal data (IDs + scope only).
    ``reviewed_by``/approval fields exist so two-person approval can be added
    later; they are not enforced yet.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("executed", "Executed"),
        ("rejected", "Rejected"),
    ]

    entity_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    scope = models.TextField()  # which data to erase, e.g. "email, name, phone"
    reason = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="erasure_requests")
    reviewed_by = models.ForeignKey(  # reserved for future approval step
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="erasure_reviews")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (f"Erasure {self.entity_type}:{self.object_id} "
                f"[{self.status}]")
