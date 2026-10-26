from rest_framework import serializers

from tickets.models import (
    Ticket, TicketAttachment, TicketCategory, TicketHistory, TicketNote,
)


class TicketCategorySerializer(serializers.ModelSerializer):
    ticket_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TicketCategory
        fields = ["id", "name", "description", "is_active",
                  "ticket_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class TicketSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    requester_email = serializers.CharField(source="requester.email", read_only=True)
    assignee_email = serializers.CharField(source="assignee.email", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True
    )

    class Meta:
        model = Ticket
        fields = ["id", "title", "description", "category", "category_name",
                  "priority", "status", "requester", "requester_email",
                  "assignee", "assignee_email", "department",
                  "department_name", "on_behalf_reason", "asset",
                  "resolution_notes", "resolved_at", "closed_at",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "requester", "resolved_at", "closed_at",
                            "created_at", "updated_at"]

    def validate(self, attrs):
        # Backend validates category ID exists + is active (unless staff
        # explicitly uses an inactive one — blocked here for consistency).
        category = attrs.get("category")
        if category and not category.is_active:
            raise serializers.ValidationError(
                {"category": "Selected category is deactivated."}
            )
        return attrs

    def validate_assignee(self, user):
        # Eligible assignees are existing, non-deleted, active users.
        # Applies to creation and single updates (field-level, so it runs
        # before anything is saved). None (unassign/omitted) stays valid.
        # Unknown or soft-deleted PKs never reach here: the FK field
        # itself rejects them against the soft-delete-filtered manager.
        if user is not None and not user.is_active:
            raise serializers.ValidationError(
                "Selected user is inactive and cannot be assigned tickets."
            )
        return user


class TicketNoteSerializer(serializers.ModelSerializer):
    author_email = serializers.CharField(source="author.email", read_only=True)

    class Meta:
        model = TicketNote
        fields = ["id", "ticket", "author", "author_email", "body",
                  "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class TicketHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = TicketHistory
        fields = ["id", "ticket", "actor", "actor_email", "action",
                  "timestamp", "old_values", "new_values", "note"]
        read_only_fields = fields


class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = ["id", "ticket", "file", "original_filename",
                  "uploaded_by", "created_at"]
        read_only_fields = ["id", "uploaded_by", "created_at"]

    def validate_file(self, f):
        return validate_attachment_file(f)


def validate_attachment_file(f):
    """Shared upload policy for ticket AND asset attachments.

    Single implementation: extension whitelist, size cap, executable /
    script blocking. Raises serializers.ValidationError on violation.
    """
    from django.conf import settings
    import os

    ext = os.path.splitext(getattr(f, "name", "") or "")[1].lower().lstrip(".")
    allowed = [e.lower() for e in
               getattr(settings, "ATTACHMENT_ALLOWED_EXTENSIONS", [])]
    if ext not in allowed:
        raise serializers.ValidationError(
            f"Extension '.{ext}' not allowed. Allowed: {allowed}")
    max_bytes = (getattr(settings, "ATTACHMENT_MAX_SIZE_MB", 10)
                 * 1024 * 1024)
    if f.size and f.size > max_bytes:
        raise serializers.ValidationError(
            f"File too large ({f.size} bytes). "
            f"Limit: {max_bytes:.0f} bytes.")
    ctype = getattr(f, "content_type", "") or ""
    # Block executables / scripts regardless of extension claim.
    if ctype.startswith(("application/x-ms", "application/x-sh",
                          "application/x-executable")) or \
            ext in ("exe", "bat", "cmd", "sh", "ps1", "msi"):
        raise serializers.ValidationError("Executable files are blocked.")
    return f
