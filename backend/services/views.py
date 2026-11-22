import itertools

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import permissions, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.models import User
from tickets.models import Ticket
from .models import ServiceCatalogueItem, ServiceRequest, ServiceRequestComment, ServiceRequestHistory, ServiceRequestAttachment
from .serializers import (
    ServiceCatalogueItemSerializer, ServiceRequestSerializer, ServiceRequestCommentSerializer,
    ServiceRequestAttachmentSerializer,
)
from .service_ticketing import ensure_ticket_for_service_request
from tickets.serializers import TicketLinkSerializer


def is_staff(user):
    return user.is_authenticated and user.role in ("system_admin", "it_manager", "it_support")


class ServiceCatalogueItemViewSet(viewsets.ModelViewSet):
    queryset = ServiceCatalogueItem.objects.filter(is_deleted=False)
    serializer_class = ServiceCatalogueItemSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        role = getattr(self.request.user, "role", "")
        if role == "it_support":
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not is_staff(user):
            qs = qs.filter(is_active=True)
        return qs

    def perform_destroy(self, instance):
        role = getattr(self.request.user, "role", "")
        if role == "it_support":
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Forbidden")
        instance.soft_delete(by_user=self.request.user)

    def create(self, request, *args, **kwargs):
        role = getattr(request.user, "role", "")
        if role == "it_support" or not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        role = getattr(request.user, "role", "")
        if role == "it_support" or not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        role = getattr(request.user, "role", "")
        if role == "it_support" or not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        role = getattr(request.user, "role", "")
        if role == "it_support" or not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().destroy(request, *args, **kwargs)


class ServiceRequestViewSet(viewsets.ModelViewSet):
    queryset = ServiceRequest.objects.filter(is_deleted=False)
    serializer_class = ServiceRequestSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related(
            "catalogue_item", "requester", "assigned_to",
            "fulfilment_ticket__assignee",
        ).prefetch_related(
            Prefetch(
                "comments",
                queryset=ServiceRequestComment.objects.select_related("author"),
                to_attr="_prefetched_comments",
            ),
            Prefetch(
                "history",
                queryset=ServiceRequestHistory.objects.select_related("actor"),
            ),
            "attachments",
        )
        user = self.request.user
        if not is_staff(user):
            qs = qs.filter(requester=user)
        return qs

    def perform_create(self, serializer):
        item = serializer.validated_data["catalogue_item"]
        req = serializer.save(
            requester=self.request.user,
            department=self.request.user.home_department,
            approval_required=item.requires_approval,
            status="pending_approval" if item.requires_approval else "submitted",
            request_number=f"SR-{timezone.now().strftime('%Y%m%d')}-{ServiceRequest.objects.count()+1:04d}",
        )
        ServiceRequestHistory.objects.create(request=req, actor=self.request.user, event="created", detail="Request submitted")
        if item.requires_approval:
            ServiceRequestHistory.objects.create(request=req, actor=self.request.user, event="approval_required", detail="Pending approval")
        # Automatic Ticket creation for catalogue items that create a Ticket
        # and do not require approval. Runs in the same atomic block as the
        # Request (DRF wraps perform_create), so a failure rolls the Request
        # back and the user can retry once configuration is fixed.
        if item.creates_ticket and not item.requires_approval:
            ensure_ticket_for_service_request(req, self.request.user)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        if req.requester != request.user and not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        if req.status in ("fulfilled", "cancelled", "rejected"):
            return Response({"detail": "Cannot cancel"}, status=400)
        req.status = "cancelled"
        req.resolved_at = timezone.now()
        req.save(update_fields=["status", "resolved_at"])
        ServiceRequestHistory.objects.create(request=req, actor=request.user, event="cancelled", detail="Cancelled")
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        req = self.get_object()
        role = getattr(request.user, "role", "")
        if role == "it_support":
            return Response({"detail": "Forbidden"}, status=403)
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        if req.requester == request.user:
            return Response({"detail": "Cannot approve own request"}, status=400)
        if req.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=400)
        item = req.catalogue_item
        with transaction.atomic():
            req.status = "approved"
            req.approver = request.user
            req.approval_decision = "approved"
            req.approval_reason = request.data.get("reason", "")
            req.approved_at = timezone.now()
            req.save(
                update_fields=[
                    "status", "approver", "approval_decision",
                    "approval_reason", "approved_at", "updated_at",
                ])
            ServiceRequestHistory.objects.create(
                request=req, actor=request.user, event="approved",
                detail=req.approval_reason)
            # Automatic Ticket creation for catalogue items that create a
            # Ticket. If it fails, the whole approval (save + history) rolls
            # back and the Request stays pending_approval.
            if getattr(item, "creates_ticket", False):
                ensure_ticket_for_service_request(req, request.user)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
        role = getattr(request.user, "role", "")
        if role == "it_support":
            return Response({"detail": "Forbidden"}, status=403)
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        if req.requester == request.user:
            return Response({"detail": "Cannot reject own request"}, status=400)
        if req.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=400)
        req.status = "rejected"
        req.approver = request.user
        req.approval_decision = "rejected"
        req.approval_reason = request.data.get("reason", "")
        req.approved_at = timezone.now()
        req.resolved_at = timezone.now()
        req.save()
        ServiceRequestHistory.objects.create(request=req, actor=request.user, event="rejected", detail=req.approval_reason)
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        req = self.get_object()
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        uid = request.data.get("assigned_to")
        user = User.objects.filter(pk=uid).first() if uid else None
        req.assigned_to = user
        if req.status == "approved":
            req.status = "in_progress"
        req.save()
        ServiceRequestHistory.objects.create(request=req, actor=request.user, event="assigned", detail=f"Assigned to {user}" if user else "Unassigned")
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        req = self.get_object()
        body = request.data.get("body", "").strip()
        if not body:
            return Response({"detail": "Body required"}, status=400)
        is_internal = bool(request.data.get("is_internal", False))
        if is_internal and not is_staff(request.user):
            is_internal = False
        c = ServiceRequestComment.objects.create(request=req, author=request.user, body=body, is_internal=is_internal)
        return Response(ServiceRequestCommentSerializer(c).data, status=201)

    @action(detail=True, methods=["post"], url_path="create-ticket")
    def create_ticket(self, request, pk=None):
        """Manual recovery: create (or return the existing) linked Ticket.

        Staff-only. Useful for configuration repair or legacy requests where
        the automatic Ticket was never created. Idempotent: returns the
        existing Ticket with HTTP 200 when one is already linked.
        """
        req = self.get_object()
        role = getattr(request.user, "role", "")
        if role == "it_support":
            return Response({"detail": "Forbidden"}, status=403)
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        item = req.catalogue_item
        if not getattr(item, "creates_ticket", False):
            return Response(
                {"detail": "Catalogue item is not configured to create Tickets."},
                status=400,
            )
        if req.status in ("cancelled", "rejected", "fulfilled"):
            return Response(
                {"detail": "Cannot create a Ticket for a %s request." % req.status},
                status=400,
            )
        if getattr(item, "requires_approval", False) and req.status != "approved":
            return Response(
                {"detail": "Request must be approved before a Ticket can be created."},
                status=400,
            )
        if req.fulfilment_ticket_id:
            ticket = Ticket.objects.filter(pk=req.fulfilment_ticket_id).first()
            if ticket is not None:
                return Response(
                    {"created": False,
                     "ticket": TicketLinkSerializer(ticket,
                                                    context={"request": request}).data},
                    status=200,
                )
        try:
            ticket, created = ensure_ticket_for_service_request(
                req, request.user)
        except ValidationError as exc:
            return Response(exc.detail, status=400)
        return Response(
            {"created": created,
             "ticket": TicketLinkSerializer(ticket,
                                            context={"request": request}).data},
            status=201 if created else 200,
        )


class ServiceRequestAttachmentViewSet(viewsets.ModelViewSet):
    """Upload and protected download of Service Request attachments.

    Visibility: staff see all attachments; employees see attachments on
    their own requests only. Downloads are permission-checked and never
    expose storage URLs directly.
    """
    serializer_class = ServiceRequestAttachmentSerializer

    def get_queryset(self):
        qs = ServiceRequestAttachment.objects.select_related("request")
        user = self.request.user
        if is_staff(user):
            return qs.all()
        return qs.filter(request__requester=user)

    def perform_create(self, serializer):
        req = serializer.validated_data.get("request")
        if not is_staff(self.request.user) and req.requester != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot attach to this request.")
        from tickets.serializers import validate_attachment_file
        upload = serializer.validated_data.get("file")
        if upload is not None:
            validate_attachment_file(upload)
        serializer.save(
            uploaded_by=self.request.user,
            size=getattr(upload, "size", 0) or 0,
            content_type=getattr(upload, "content_type", "") or "")
        ServiceRequestHistory.objects.create(
            request=req, actor=self.request.user, event="attachment_added",
            detail="Attachment added")

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.is_deleted = True
        obj.save(update_fields=["is_deleted"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Permission-checked download. Never expose storage URLs directly."""
        import mimetypes
        import os
        from django.http import FileResponse
        from common.attachment_security import (
            add_download_security_headers,
            safe_content_disposition_filename,
        )
        obj = self.get_object()
        try:
            handle = obj.file.open("rb")
        except FileNotFoundError:
            return Response({"detail": "File missing from storage."},
                            status=410)
        name = os.path.basename(obj.file.name)
        resp = FileResponse(
            handle,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream")
        safe_name = safe_content_disposition_filename(name)
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        add_download_security_headers(resp)
        return resp
