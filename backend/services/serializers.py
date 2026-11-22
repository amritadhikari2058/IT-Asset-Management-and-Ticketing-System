from rest_framework import serializers
from .models import (
    ServiceCatalogueItem, ServiceRequest, ServiceRequestComment,
    ServiceRequestHistory, ServiceRequestAttachment,
)
from tickets.serializers import TicketLinkSerializer


def _is_staff(user):
    return bool(user and user.is_authenticated and user.role in
                ("system_admin", "it_manager", "it_support"))


class ServiceCatalogueItemSerializer(serializers.ModelSerializer):
    ticket_category_name = serializers.CharField(
        source="ticket_category.name", read_only=True)
    ticket_automation_ready = serializers.SerializerMethodField(read_only=True)

    def get_ticket_automation_ready(self, obj):
        return bool(obj.creates_ticket and obj.ticket_category_id
                    and obj.ticket_category.is_active)

    class Meta:
        model = ServiceCatalogueItem
        fields = [
            "id", "name", "description", "category", "icon", "is_active",
            "requires_approval", "creates_ticket", "ticket_category",
            "ticket_category_name", "ticket_automation_ready",
            "estimated_fulfilment_hours", "instructions", "form_fields",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at",
                            "ticket_category_name",
                            "ticket_automation_ready"]


class ServiceRequestAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceRequestAttachment
        fields = ["id", "request", "file", "uploaded_by", "uploaded_at",
                  "size", "content_type"]
        read_only_fields = ["uploaded_by", "uploaded_at", "size", "content_type"]


class ServiceRequestCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.email", read_only=True)

    class Meta:
        model = ServiceRequestComment
        fields = ["id", "author", "author_name", "body", "is_internal", "created_at"]
        read_only_fields = ["author", "created_at"]


class ServiceRequestHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = ServiceRequestHistory
        fields = ["id", "event", "detail", "actor", "actor_name", "created_at"]


class ServiceRequestSerializer(serializers.ModelSerializer):
    catalogue_item_name = serializers.CharField(source="catalogue_item.name", read_only=True)
    requester_name = serializers.CharField(source="requester.email", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.email", read_only=True, allow_null=True)
    comments = serializers.SerializerMethodField(read_only=True)
    history = ServiceRequestHistorySerializer(many=True, read_only=True)
    attachments = ServiceRequestAttachmentSerializer(many=True, read_only=True)
    fulfilment_ticket = TicketLinkSerializer(read_only=True)
    ticket_creation_status = serializers.SerializerMethodField(read_only=True)

    def get_comments(self, obj):
        user = self.context.get("request").user if self.context.get("request") else None
        prefetched = getattr(obj, "_prefetched_comments", None)
        if prefetched is None:
            qs = obj.comments.all()
            if not _is_staff(user):
                qs = qs.filter(is_internal=False)
        elif _is_staff(user):
            qs = prefetched
        else:
            qs = [comment for comment in prefetched
                  if not comment.is_internal]
        return ServiceRequestCommentSerializer(qs, many=True).data

    def get_ticket_creation_status(self, obj):
        """Safe, non-sensitive summary of Ticket creation state.

        - "created": a linked Ticket exists.
        - "pending": the catalogue item creates Tickets but none is linked yet.
        - "none": the catalogue item does not create Tickets.
        """
        if obj.fulfilment_ticket_id:
            return "created"
        item = getattr(obj, "catalogue_item", None)
        if item is not None and getattr(item, "creates_ticket", False):
            return "pending"
        return "none"

    class Meta:
        model = ServiceRequest
        fields = [
            "id", "request_number", "requester", "requester_name", "department",
            "catalogue_item", "catalogue_item_name", "answers", "description",
            "priority", "status", "assigned_to", "assigned_to_name",
            "approval_required", "approver", "approval_decision", "approval_reason",
            "approved_at", "fulfilment_ticket", "fulfilment_details", "resolved_at",
            "submitted_at", "updated_at", "comments", "history", "attachments",
            "ticket_creation_status",
        ]
        read_only_fields = [
            "request_number", "requester", "status", "approver", "approval_decision",
            "approval_reason", "approved_at", "fulfilment_ticket", "resolved_at",
            "submitted_at", "updated_at", "ticket_creation_status",
        ]
