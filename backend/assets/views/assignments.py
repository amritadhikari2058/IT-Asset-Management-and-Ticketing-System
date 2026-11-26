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
from .shared import _asset_visible_qs

class AssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Assignment.objects.select_related(
        "asset", "assigned_to", "assigned_by").all()
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not (is_system_admin(user) or getattr(user, "role", "") in
                ("it_manager", "it_support")):
            # Employees only see assignments on assets they can view:
            # their own assignments, or assignments on home-department assets.
            visible_ids = _asset_visible_qs(user).values("pk")
            qs = qs.filter(asset_id__in=visible_ids)
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        return qs



class AssetHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AssetHistory.objects.select_related("asset", "actor").all()
    serializer_class = AssetHistorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        user = self.request.user
        if getattr(user, "role", "") in ("system_admin", "it_manager"):
            return qs
        if getattr(user, "role", "") == "it_support":
            if not user.has_perm("assets.view_asset_history"):
                return qs.none()
            return qs
        return qs.none()


