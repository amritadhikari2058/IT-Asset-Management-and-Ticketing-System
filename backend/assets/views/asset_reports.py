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

class AssetReportViewSet(viewsets.ReadOnlyModelViewSet):
    """Asset reporting and analytics endpoints (IT staff only).

    Read-only aggregation endpoints:
    - /assets/reports/financial/  — purchase cost overview
    - /assets/reports/maintenance/ — maintenance analytics
    - /assets/reports/warranty/ — warranty monitoring
    - /assets/reports/utilization/ — asset utilization insights
    - /assets/reports/inventory/ — filtered asset inventory for export
    """
    permission_classes = [IsActiveAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsITStaff()]
        return super().get_permissions()

    def list(self, request):
        """Route to the appropriate report based on ?report= query param.

        Supported reports: financial, maintenance, warranty, utilization, inventory.
        """
        report = (request.query_params.get("report") or "").strip()
        params = dict(request.query_params)
        # Strip routing params
        params.pop("report", None)
        params.pop("page", None)
        params.pop("page_size", None)

        if report == "financial":
            data = reports.financial_overview_data()
        elif report == "maintenance":
            data = reports.maintenance_analytics_data(params)
        elif report == "warranty":
            data = reports.warranty_monitoring_data(params)
        elif report == "utilization":
            data = reports.utilization_data()
        elif report == "inventory":
            data = reports.asset_report_data(params)
        elif report == "assets_by_department":
            data = reports.assets_by_department()
        elif report == "assets_by_location":
            data = reports.assets_by_location()
        elif report == "assets_with_incomplete_info":
            data = reports.assets_with_incomplete_info()
        elif report == "warranty_by_department":
            data = reports.warranty_by_department(params)
        elif report == "warranty_by_category":
            data = reports.warranty_by_category(params)
        elif report == "warranty_by_vendor":
            data = reports.warranty_by_vendor(params)
        elif report == "purchase_cost_by_department":
            data = reports.purchase_cost_by_department()
        elif report == "purchase_cost_trends":
            data = reports.purchase_cost_trends()
        else:
            return Response(
                {"detail": "Unsupported report. Supported: financial, maintenance, warranty, utilization, inventory, "
                 "assets_by_department, assets_by_location, assets_with_incomplete_info, "
                 "warranty_by_department, warranty_by_category, warranty_by_vendor, "
                 "purchase_cost_by_department, purchase_cost_trends."},
                status=400)

        return Response(data)


