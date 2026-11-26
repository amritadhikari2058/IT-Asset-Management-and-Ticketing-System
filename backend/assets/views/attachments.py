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
from .shared import _asset_visible_qs, _positive_pk_param

class AssetAttachmentViewSet(viewsets.ModelViewSet):
    """Private asset files. Same lifecycle as ticket attachments.

    Reads (list/retrieve/download) are scoped to assets visible to the
    caller. Writes (upload/edit/delete) require IT staff, matching the
    asset mutation rules. No public URLs are ever generated.
    """

    queryset = AssetAttachment.objects.all()
    serializer_class = AssetAttachmentSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        # Only attachments on visible assets (private files, no public URLs).
        # Visibility is applied first; ``?asset=`` can only narrow it.
        visible_ids = _asset_visible_qs(self.request.user).values("pk")
        qs = AssetAttachment.objects.filter(asset_id__in=visible_ids)
        raw = self.request.query_params.get("asset")
        if raw not in (None, ""):
            asset_pk = _positive_pk_param(raw)
            if asset_pk is None:
                return qs.none()
            qs = qs.filter(asset_id=asset_pk)
        return qs

    def perform_create(self, serializer):
        asset = serializer.validated_data.get("asset")
        if asset and asset.pk:
            visible = _asset_visible_qs(self.request.user).filter(
                pk=asset.pk).exists()
            if not visible:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Cannot attach to this asset.")
        upload = serializer.validated_data.get("file")
        obj = serializer.save(
            uploaded_by=self.request.user,
            original_filename=safe_original_filename(
                getattr(upload, "name", "")))
        log_action(actor=self.request.user, action="create", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Soft delete keeps the physical file (record retained).
        obj.soft_delete(by_user=request.user, reason="attachment removed")
        log_action(actor=request.user, action="soft_delete", instance=obj)
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
        obj = self.get_object()  # scoped to visible assets above
        if obj.is_deleted:
            return Response(
                {"detail": "Attachment is deleted."}, status=404)
        try:
            handle = obj.file.open("rb")
        except FileNotFoundError:
            return Response(
                {"detail": "File missing from storage."}, status=410)
        name = obj.original_filename or os.path.basename(
            obj.file.name)
        resp = FileResponse(
            handle,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream")
        safe_name = safe_content_disposition_filename(name)
        resp["Content-Disposition"] = (
            f'attachment; filename="{safe_name}"')
        add_download_security_headers(resp)
        return resp


