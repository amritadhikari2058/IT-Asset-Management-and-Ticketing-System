import itertools

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from .models import ServiceCatalogueItem, ServiceRequest, ServiceRequestComment, ServiceRequestHistory, ServiceRequestAttachment
from .serializers import (
    ServiceCatalogueItemSerializer, ServiceRequestSerializer, ServiceRequestCommentSerializer,
)


def is_staff(user):
    return user.is_authenticated and user.role in ("system_admin", "it_manager", "it_support")


class ServiceCatalogueItemViewSet(viewsets.ModelViewSet):
    queryset = ServiceCatalogueItem.objects.filter(is_deleted=False)
    serializer_class = ServiceCatalogueItemSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not is_staff(user):
            qs = qs.filter(is_active=True)
        return qs

    def perform_destroy(self, instance):
        instance.soft_delete(by_user=self.request.user)

    def create(self, request, *args, **kwargs):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().update(request, *args, **kwargs)


class ServiceRequestViewSet(viewsets.ModelViewSet):
    queryset = ServiceRequest.objects.filter(is_deleted=False)
    serializer_class = ServiceRequestSerializer

    def get_queryset(self):
        qs = super().get_queryset()
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
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        if req.requester == request.user:
            return Response({"detail": "Cannot approve own request"}, status=400)
        if req.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=400)
        req.status = "approved"
        req.approver = request.user
        req.approval_decision = "approved"
        req.approval_reason = request.data.get("reason", "")
        req.approved_at = timezone.now()
        req.save()
        ServiceRequestHistory.objects.create(request=req, actor=request.user, event="approved", detail=req.approval_reason)
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
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
