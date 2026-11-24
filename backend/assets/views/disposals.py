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

class DisposalViewSet(viewsets.ModelViewSet):
    """Asset disposal workflow: draft -> approve/reject -> complete.

    A disposed asset keeps its distinct status and can never be assigned
    again. Disposal requires the asset's assignment to be resolved first.
    """

    queryset = Disposal.objects.select_related(
        "asset", "responsible_person", "approver", "created_by").all()
    serializer_class = DisposalSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy",
                           "approve", "reject", "complete"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        asset_id = params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        approval_status = params.get("approval_status")
        if approval_status:
            qs = qs.filter(approval_status=approval_status)
        disposal_method = params.get("disposal_method")
        if disposal_method:
            qs = qs.filter(disposal_method=disposal_method)
        if params.get("completed") in ("true", "1"):
            qs = qs.filter(disposal_date__isnull=False)
        elif params.get("completed") in ("false", "0"):
            qs = qs.filter(disposal_date__isnull=True)
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(asset__asset_tag__icontains=q)
                | Q(asset__name__icontains=q)
                | Q(disposal_reason__icontains=q))
        return qs.order_by("-created_at", "-id")

    def perform_create(self, serializer):
        # A disposal starts pending. IT Support cannot mint an already-approved
        # record (the approve() action denies them the same decision), and no
        # one can complete a disposal at creation time: completion is the
        # complete() action, which also disposes the asset.
        requested_status = (serializer.validated_data.get("approval_status")
                            or "pending")
        if (requested_status != "pending"
                and getattr(self.request.user, "role", "") == "it_support"):
            raise PermissionDenied(
                "Only an IT Manager or System Admin can approve or reject "
                "a disposal.")
        if serializer.validated_data.get("disposal_date") is not None:
            raise ValidationError(
                {"disposal_date": "Use the complete action to record a "
                                  "disposal date; it also disposes the asset."})
        obj = serializer.save(created_by=self.request.user)
        _history_disposal(obj, self.request.user, "created",
                          new={"approval_status": obj.approval_status})
        log_action(actor=self.request.user, action="create", instance=obj)
        if obj.approval_status in ("approved", "rejected"):
            # A manager may create an already-decided record: keep metadata
            # and the decision trail identical to create + approve()/reject().
            approved = obj.approval_status == "approved"
            obj.approver = self.request.user
            obj.approved_at = timezone.now() if approved else None
            obj.save(update_fields=["approver", "approved_at"])
            _history_disposal(obj, self.request.user,
                              "approved" if approved else "rejected",
                              new={"approval_status": obj.approval_status})
            log_action(actor=self.request.user,
                       action="approve" if approved else "reject",
                       instance=obj,
                       details={"asset": obj.asset.asset_tag})
        _notify_disposal(obj, self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        # Approval is a manager/admin decision: the dedicated approve() action
        # rejects IT Support, so the generic update path must not let the same
        # user set it either.
        requested_status = serializer.validated_data.get("approval_status")
        status_changed = (requested_status is not None
                          and requested_status != instance.approval_status)
        if (status_changed
                and getattr(self.request.user, "role", "") == "it_support"):
            raise PermissionDenied(
                "Only an IT Manager or System Admin can approve or reject "
                "a disposal.")
        # approve()/reject() refuse to decide a completed disposal; the
        # generic path must not rewrite the decision afterwards either.
        if status_changed and instance.is_completed:
            raise ValidationError(
                {"approval_status": "A completed disposal's approval status "
                                    "cannot be changed."})
        # The asset is the subject of the approval: re-pointing the record
        # after a decision would let complete() dispose an asset that was
        # never approved.
        requested_asset = serializer.validated_data.get("asset")
        if (requested_asset is not None
                and requested_asset.pk != instance.asset_id
                and instance.approval_status != "pending"):
            raise ValidationError(
                {"asset": "The asset cannot be changed after the disposal "
                          "has been approved or rejected."})
        # Completion is owned by the complete() action, which also disposes
        # the asset. Setting the date here would mark the disposal completed
        # while leaving the asset untouched (and bypassing approval).
        requested_date = serializer.validated_data.get("disposal_date")
        if (requested_date is not None
                and requested_date != instance.disposal_date):
            raise ValidationError(
                {"disposal_date": "Use the complete action to record a "
                                  "disposal date; it also disposes the asset."})
        old = {"approval_status": instance.approval_status,
               "disposal_date": str(instance.disposal_date)}
        obj = serializer.save()
        non_status_changes = {k: v for k, v in
                              serializer.validated_data.items()
                              if k != "approval_status"}
        if obj.approval_status != old["approval_status"]:
            # Same metadata/history/audit/notification as approve()/reject().
            _record_disposal_decision(obj, self.request.user,
                                      old["approval_status"])
        if non_status_changes or obj.approval_status == old["approval_status"]:
            _history_disposal(obj, self.request.user, "updated", old=old,
                              new={k: str(v)
                                   for k, v in non_status_changes.items()})
            log_action(actor=self.request.user, action="update", instance=obj,
                       details={"old": old, "new": {
                           "approval_status": obj.approval_status,
                           "disposal_date": str(obj.disposal_date)}})

    @action(detail=True, methods=["post"], permission_classes=[IsITStaff])
    def approve(self, request, pk=None):
        # Only IT Manager or System Admin can approve
        role = getattr(request.user, "role", "")
        if role == "it_support":
            # NB: no local Response import here - it would shadow the
            # module-level name and leave it unbound for authorized users.
            return Response({"detail": "Forbidden"}, status=403)
        obj = self.get_object()
        if obj.is_completed:
            return Response(
                {"detail": "Disposal already completed."}, status=400)
        old_status = obj.approval_status
        obj.approval_status = "approved"
        _record_disposal_decision(obj, request.user, old_status)
        return Response(DisposalSerializer(obj).data)

    @action(detail=True, methods=["post"], permission_classes=[IsITStaff])
    def reject(self, request, pk=None):
        role = getattr(request.user, "role", "")
        if role == "it_support":
            return Response({"detail": "Forbidden"}, status=403)
        obj = self.get_object()
        if obj.is_completed:
            return Response(
                {"detail": "Cannot reject a completed disposal."}, status=400)
        old_status = obj.approval_status
        obj.approval_status = "rejected"
        _record_disposal_decision(obj, request.user, old_status)
        return Response(DisposalSerializer(obj).data)

    @action(detail=True, methods=["post"], permission_classes=[IsITStaff])
    def complete(self, request, pk=None):
        role = getattr(request.user, "role", "")
        if role == "it_support":
            return Response({"detail": "Forbidden"}, status=403)
        obj = self.get_object()
        if obj.approval_status != "approved":
            return Response(
                {"detail": "Disposal must be approved before completion."},
                status=400)
        if obj.is_completed:
            return Response(DisposalSerializer(obj).data)
        _complete_disposal(obj, request.user)
        obj.refresh_from_db()
        return Response(DisposalSerializer(obj).data)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_completed:
            return Response(
                {"detail": "Completed disposals cannot be deleted."},
                status=409)
        obj.soft_delete(by_user=request.user, reason="disposal removed")
        log_action(actor=request.user, action="soft_delete", instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)
