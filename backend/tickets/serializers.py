from rest_framework import serializers

from tickets.models import (
    Ticket, TicketAttachment, TicketBulkImportOperation, TicketCategory,
    TicketHistory, TicketKbArticle, TicketNote, TicketSLA,
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
    queue_name = serializers.CharField(
        source="queue.name", read_only=True, allow_null=True
    )
    sla_due_at = serializers.DateTimeField(read_only=True)
    sla_breached = serializers.BooleanField(read_only=True)
    is_overdue = serializers.SerializerMethodField(read_only=True)
    source_service_request = serializers.SerializerMethodField(read_only=True)

    def get_is_overdue(self, obj):
        return obj.is_overdue

    def get_source_service_request(self, obj):
        """Safe, minimal linked Service Request reference (no PII/answers)."""
        request = self.context.get("request")
        prefetched = getattr(obj, "_ticket_source_service_requests", None)
        if prefetched is None:
            sr = obj.service_requests.filter(is_deleted=False).select_related(
                "catalogue_item").first()
        else:
            sr = prefetched[0] if prefetched else None
        if sr is None:
            return None
        return {
            "id": sr.pk,
            "request_number": sr.request_number,
            "catalogue_item_name": sr.catalogue_item.name
            if getattr(sr, "catalogue_item_id", None) else None,
            "status": sr.status,
            "url": request.build_absolute_uri(
                f"/api/services/requests/{sr.pk}/") if request
            else "/api/services/requests/%d/" % sr.pk,
        }

    class Meta:
        model = Ticket
        fields = ["id", "title", "description", "category", "category_name",
                  "priority", "status", "requester", "requester_email",
                  "assignee", "assignee_email", "department",
                  "department_name", "queue", "queue_name",
                  "on_behalf_reason", "asset",
                  "resolution_notes", "resolved_at", "closed_at",
                  "sla_due_at", "sla_breached", "is_overdue",
                  "source_service_request",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "requester", "queue", "resolved_at", "closed_at",
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


class CachedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        caches = self.context.get("bulk_related_objects", {})
        related_objects = caches.get(self.field_name)
        if related_objects is None:
            return super().to_internal_value(data)
        try:
            pk = (self.pk_field.to_internal_value(data)
                  if self.pk_field is not None else data)
            return related_objects[pk]
        except (KeyError, TypeError):
            self.fail("does_not_exist", pk_value=data)


def _ticket_related_queryset(field_name):
    relation = Ticket._meta.get_field(field_name).remote_field
    return relation.model._default_manager.all()


class TicketBulkImportSerializer(TicketSerializer):
    category = CachedPrimaryKeyRelatedField(
        queryset=_ticket_related_queryset("category"))
    assignee = CachedPrimaryKeyRelatedField(
        queryset=_ticket_related_queryset("assignee"),
        required=False, allow_null=True)
    department = CachedPrimaryKeyRelatedField(
        queryset=_ticket_related_queryset("department"),
        required=False, allow_null=True)
    asset = CachedPrimaryKeyRelatedField(
        queryset=_ticket_related_queryset("asset"),
        required=False, allow_null=True)


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
        read_only_fields = ["id", "ticket", "author", "created_at"]


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
        # original_filename is server-controlled (set from the uploaded file
        # by the view) so a client cannot relabel an existing attachment.
        read_only_fields = ["id", "uploaded_by", "created_at",
                            "original_filename"]

    def get_fields(self):
        # ticket is writable at creation (perform_create validates it) but
        # read-only on updates to prevent attachment reassignment (IDOR).
        fields = super().get_fields()
        if self.instance is not None:
            fields["ticket"].read_only = True
        return fields

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


class TicketLinkSerializer(serializers.ModelSerializer):
    """Minimal, safe linked-Ticket representation for Service Requests.

    Exposes only fields a requester/staff need to identify and open the
    Ticket; excludes notes, attachments, description, and any staff-only
    data.
    """
    assignee_email = serializers.CharField(source="assignee.email",
                                           read_only=True, allow_null=True)
    url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "title", "status", "priority", "assignee_email",
                  "url"]
        read_only_fields = fields

    def get_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/tickets/{obj.pk}/")
        return "/api/tickets/%d/" % obj.pk


class TicketBulkImportOperationSerializer(serializers.ModelSerializer):
    """Read-only operational view of a ticket bulk import.

    Intentionally omits token, request fingerprint, preview payload, and
    stored result bodies to avoid exposing sensitive or other-user data.
    """

    user_email = serializers.CharField(source="user.email", read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_stale_processing = serializers.SerializerMethodField()
    result_available = serializers.SerializerMethodField()
    error_detail = serializers.SerializerMethodField()

    class Meta:
        from tickets.models import TicketBulkImportOperation
        model = TicketBulkImportOperation
        fields = [
            "id", "user", "user_email", "status",
            "total_rows", "processed_count", "successful_count", "failed_count",
            "result_format", "result_status_code", "result_available",
            "error_detail", "is_expired", "is_stale_processing",
            "created_at", "updated_at", "started_at", "completed_at", "expires_at",
        ]
        read_only_fields = fields

    def get_is_expired(self, obj):
        return bool(obj.is_expired)

    def get_is_stale_processing(self, obj):
        if obj.status != obj.STATUS_PROCESSING or not obj.started_at:
            return False
        from django.conf import settings
        from django.utils import timezone
        from datetime import timedelta
        stale_after = int(getattr(
            settings, "TICKET_BULK_IMPORT_PROCESSING_STALE_SECONDS", 300) or 300)
        return timezone.now() - obj.started_at > timedelta(seconds=stale_after)

    def get_result_available(self, obj):
        return obj.status == obj.STATUS_COMPLETED and bool(
            obj.result_format and (obj.result_json is not None or obj.result_csv))

    def get_error_detail(self, obj):
        from tickets.bulk_import_reconciliation import sanitize_import_diagnostic
        return sanitize_import_diagnostic(getattr(obj, "error_detail", ""))

