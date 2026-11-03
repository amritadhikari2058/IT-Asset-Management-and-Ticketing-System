from rest_framework import serializers

from tickets.models import (
    Ticket, TicketAttachment, TicketCategory, TicketHistory, TicketKbArticle,
    TicketNote, TicketSLA,
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
    sla_due_at = serializers.DateTimeField(read_only=True)
    sla_breached = serializers.BooleanField(read_only=True)
    is_overdue = serializers.SerializerMethodField(read_only=True)

    def get_is_overdue(self, obj):
        return obj.is_overdue

    class Meta:
        model = Ticket
        fields = ["id", "title", "description", "category", "category_name",
                  "priority", "status", "requester", "requester_email",
                  "assignee", "assignee_email", "department",
                  "department_name", "on_behalf_reason", "asset",
                  "resolution_notes", "resolved_at", "closed_at",
                  "sla_due_at", "sla_breached", "is_overdue",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "requester", "resolved_at", "closed_at",
                            "sla_due_at", "sla_breached", "is_overdue",
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


class TicketSLASerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketSLA
        fields = ["id", "priority", "target_resolution_hours", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


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


class TicketKbArticleSerializer(serializers.ModelSerializer):
    """Links KB articles to tickets (staff curates, employee votes helpful)."""

    article_title = serializers.CharField(source="article.title",
                                          read_only=True)
    article_slug = serializers.CharField(source="article.slug",
                                         read_only=True)
    article_status = serializers.CharField(source="article.status",
                                           read_only=True)
    linked_by_email = serializers.CharField(
        source="linked_by.email", read_only=True)

    class Meta:
        model = TicketKbArticle
        fields = ["id", "ticket", "article", "article_title", "article_slug",
                  "article_status", "helpful", "linked_by", "linked_by_email",
                  "linked_at"]
        read_only_fields = ["id", "linked_by", "linked_at",
                            "article_title", "article_slug",
                            "article_status", "linked_by_email"]

    def validate(self, attrs):
        user = self.context["request"].user
        ticket = attrs.get("ticket") or getattr(self.instance, "ticket", None)
        article = attrs.get("article") or getattr(
            self.instance, "article", None)
        if self.instance is None and ticket and article:
            if TicketKbArticle.objects.filter(
                    ticket=ticket, article=article, is_deleted=False).exists():
                raise serializers.ValidationError(
                    {"article": "This KB article is already linked to the "
                                "ticket."})
        return attrs
