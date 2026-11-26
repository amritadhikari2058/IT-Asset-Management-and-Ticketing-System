"""Asset APIs: categories, assets, assignment, history, bulk.

- Ordinary asset updates pop 'assigned_to' (no silent overwrite).
- Assignment changes are explicit + write Assignment + AssetHistory rows.
- Bulk delete = soft delete only, blocked when history exists.
"""
import csv
import io
import logging
from zipfile import BadZipFile

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from openpyxl import load_workbook
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from common.permissions import IsActiveAuthenticated
from rest_framework.response import Response

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
    Disposal, Maintenance, Vendor,
)
from common.attachment_security import safe_original_filename
from assets import reports
from assets import reports
from assets.serializers import (
    AssetAssignSerializer, AssetAttachmentSerializer,
    AssetCategorySerializer, AssetHistorySerializer, AssetSerializer,
    AssignmentSerializer, DisposalSerializer, MaintenanceSerializer,
    KnowledgeBaseArticleSerializer,
    KnowledgeBaseArticleCreateUpdateSerializer,
    KnowledgeBaseArticleRevisionSerializer,
    KnowledgeBaseCategorySerializer,
    KnowledgeBaseCategoryCreateUpdateSerializer,
    KnowledgeBaseFeedbackSerializer,
    KnowledgeBaseRejectSerializer,
    KnowledgeBaseRestoreSerializer,
    KnowledgeBaseReviewDecisionSerializer,
    KnowledgeBaseSubmitReviewSerializer,
    KnowledgeBaseTagSerializer,
    KnowledgeBaseTagCreateUpdateSerializer,
    VendorSerializer,
)
from assets import kb_services
from assets.models import (KnowledgeBaseArticle, KnowledgeBaseArticleRevision,
                           KnowledgeBaseCategory, KnowledgeBaseTag,
                           KnowledgeBaseFeedback)
from common.audit import log_action
from common.models import Notification
from common.notifications import notify_user
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.serializers import validate_attachment_file

logger = logging.getLogger(__name__)



from .shared import *
from .shared import _history_maintenance, _notify_maintenance

class MaintenanceViewSet(viewsets.ModelViewSet):
    """Maintenance records for assets. IT staff manage; reads open."""

    queryset = Maintenance.objects.select_related(
        "asset", "assigned_to", "created_by").all()
    serializer_class = MaintenanceSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy",
                           "mark_overdue"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        asset_id = params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        status = params.get("status")
        if status:
            qs = qs.filter(status=status)
        maintenance_type = params.get("maintenance_type")
        if maintenance_type:
            qs = qs.filter(maintenance_type=maintenance_type)
        assigned_to = params.get("assigned_to")
        if assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q) | Q(asset__asset_tag__icontains=q)
                | Q(asset__name__icontains=q) | Q(vendor__icontains=q))
        if params.get("open") in ("true", "1"):
            qs = qs.filter(status__in=["scheduled", "in_progress", "overdue"])
        return qs.order_by("-scheduled_date", "-id")

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        _history_maintenance(obj, self.request.user, "created",
                             new={"status": obj.status,
                                  "scheduled_date": str(obj.scheduled_date)})
        log_action(actor=self.request.user, action="create", instance=obj)
        _notify_maintenance(obj, self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        old = {"status": instance.status, "assigned_to": instance.assigned_to_id,
               "scheduled_date": str(instance.scheduled_date)}
        obj = serializer.save()
        from django.utils import timezone
        stamped = False
        if obj.status != old["status"]:
            if obj.status == "in_progress" and not obj.start_date:
                obj.start_date = timezone.now()
                stamped = True
            if obj.status == "completed" and not obj.completion_date:
                obj.completion_date = timezone.now()
                stamped = True
            if stamped:
                obj.save(update_fields=["start_date", "completion_date"])
        _history_maintenance(obj, self.request.user, "updated", old=old,
                             new={k: str(v) for k, v in
                                  serializer.validated_data.items()})
        log_action(actor=self.request.user, action="update", instance=obj,
                   details={"old": old, "new": {
                       "status": obj.status,
                       "assigned_to": obj.assigned_to_id}})
        _notify_maintenance(obj, self.request.user, old=old)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        asset_tag = obj.asset.asset_tag
        obj.soft_delete(by_user=request.user, reason="maintenance removed")
        log_action(actor=request.user, action="soft_delete", instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def mark_overdue(self, request, pk=None):
        """Flag a scheduled/in-progress maintenance as overdue."""
        obj = self.get_object()
        if obj.status in ("completed", "cancelled"):
            return Response(
                {"detail": f"Cannot mark a {obj.status} maintenance "
                           f"overdue."}, status=400)
        obj.status = "overdue"
        obj.save(update_fields=["status", "updated_at"])
        _history_maintenance(obj, request.user, "status_change",
                             new={"status": "overdue"})
        log_action(actor=request.user, action="status_change",
                   instance=obj, details={"to": "overdue"})
        _notify_maintenance(obj, request.user)
        return Response(MaintenanceSerializer(obj).data)


