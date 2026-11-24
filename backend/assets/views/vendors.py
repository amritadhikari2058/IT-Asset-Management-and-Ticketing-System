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

class VendorViewSet(viewsets.ModelViewSet):
    """Vendor / supplier CRUD.

    System Admin: full CRUD + activate/deactivate.
    IT Manager: create, update, activate, deactivate.
    IT Support: list, retrieve (read-only).
    Employee: no access to Vendor API; minimal vendor identity may appear via Asset serializer.
    """
    queryset = Vendor.objects.annotate(
        asset_count=Count("assets"),
        stock_item_count=Count("stock_items")
    ).all()
    serializer_class = VendorSerializer
    permission_classes = [IsActiveAuthenticated]
    filter_backends = []
    filterset_fields = ["is_active", "is_deleted", "name", "code", "email"]
    search_fields = ["name", "code", "contact_person", "email", "phone"]
    ordering_fields = ["name", "code", "created_at", "updated_at", "asset_count", "stock_item_count"]
    ordering = ["name"]

    def get_queryset(self):
        user = self.request.user
        role = getattr(user, "role", "")
        if role == "employee":
            # Employees cannot enumerate vendors via the Vendor API
            return Vendor.objects.none()
        # IT Manager and System Admin see everything (including soft-deleted)
        # IT Support sees non-deleted only
        if role == "it_support":
            base_qs = Vendor.objects  # excludes deleted
        else:
            base_qs = Vendor.all_objects  # includes deleted for managers/admins
        qs = base_qs.annotate(
            asset_count=Count("assets"),
            stock_item_count=Count("stock_items")
        )
        # IT Support: force is_deleted=False so it cannot be overridden by
        # query params
        if role == "it_support":
            qs = qs.filter(is_deleted=False)

        # ---- Search ----
        q = (self.request.query_params.get("search") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
                | Q(contact_person__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
            )

        # ---- Filters ----
        params = self.request.query_params
        for field in ("is_active", "is_deleted", "name", "code", "email"):
            val = params.get(field)
            if val is not None and val != "":
                # IT Support: never expose deleted vendors regardless of params
                if role == "it_support" and field == "is_deleted":
                    continue
                if field in ("name", "code", "email"):
                    qs = qs.filter(**{field + "__iexact": val})
                else:
                    # is_active / is_deleted: accept "true"/"false" strings
                    if isinstance(val, str) and val.lower() in ("true", "false"):
                        val = val.lower() == "true"
                    qs = qs.filter(**{field: val})

        # ---- Ordering ----
        allowed_ordering = {
            "name": "name",
            "code": "code",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "asset_count": "asset_count",
            "stock_item_count": "stock_item_count",
        }
        raw_ordering = (params.get("ordering") or "").strip()
        if raw_ordering:
            direction = ""
            field = raw_ordering
            if field.startswith("-"):
                direction = "-"
                field = field[1:]
            elif field.startswith("+"):
                field = field[1:]
            if field in allowed_ordering:
                qs = qs.order_by(direction + allowed_ordering[field], "id")
            else:
                qs = qs.order_by("name", "id")
        else:
            qs = qs.order_by("name", "id")

        return qs

    def get_permissions(self):
        role = getattr(self.request.user, "role", "")
        # Employees denied access to Vendor API entirely
        if role == "employee":
            from rest_framework.permissions import BasePermission
            class Deny(BasePermission):
                def has_permission(self, request, view):
                    return False
            return [Deny()]
        # IT Support can list and retrieve non-deleted vendors (read-only)
        if role == "it_support":
            if self.action in ("list", "retrieve"):
                return [IsActiveAuthenticated()]
            from rest_framework.permissions import BasePermission
            class Deny(BasePermission):
                def has_permission(self, request, view):
                    return False
            return [Deny()]
        # IT Manager has full access
        if role == "it_manager":
            return [IsITStaff()]
        # System Admin has full access
        if getattr(self.request.user, "is_superuser", False) or role == "system_admin":
            return [IsSystemAdmin()]
        return super().get_permissions()

    def perform_create(self, serializer):
        # Guard against concurrent duplicate creation: the DB unique
        # constraint on name/code is the backstop, but we acquire the
        # vendor row lock inside a transaction so the losing request gets a
        # controlled 400 instead of an IntegrityError 500.
        try:
            with transaction.atomic():
                obj = serializer.save()
                from common.audit import log_action
                log_action(actor=self.request.user, action="create", instance=obj,
                           reason="vendor created")
        except IntegrityError:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"detail": "A vendor with that name or code already exists."})

    def perform_update(self, serializer):
        # Lock the vendor row inside the transaction so concurrent updates
        # cannot silently overwrite each other (lost update). Use a plain
        # queryset (no annotations) because select_for_update() is not
        # compatible with GROUP BY on PostgreSQL.
        #
        # IMPORTANT: serializer.instance points to the object fetched by
        # DRF's get_object() (unlocked). We must point it at the locked
        # object so serializer.save() writes to the row we hold the lock on.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]
        with transaction.atomic():
            obj = Vendor.objects.select_for_update().get(
                pk=lookup_value)
            self.check_object_permissions(self.request, obj)
            serializer.instance = obj
            serializer.save()
            # Re-fetch with annotations so the response includes
            # asset_count / stock_item_count
            obj = Vendor.objects.annotate(
                asset_count=Count("assets"),
                stock_item_count=Count("stock_items")
            ).get(pk=obj.pk)
            serializer.instance = obj
            from common.audit import log_action
            log_action(actor=self.request.user, action="update", instance=obj,
                       reason="vendor updated")

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate a deactivated vendor."""
        try:
            obj = Vendor.all_objects.get(pk=pk)
        except Vendor.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)
        if obj.is_deleted:
            return Response(
                {"detail": "Cannot activate a deleted vendor. Restore it first."},
                status=400)
        if obj.is_active:
            return Response({"detail": "Vendor is already active."}, status=400)
        with transaction.atomic():
            obj = Vendor.objects.select_for_update().get(pk=obj.pk)
            if obj.is_deleted:
                return Response(
                    {"detail": "Cannot activate a deleted vendor. Restore it first."},
                    status=400)
            obj.is_active = True
            obj.save(update_fields=["is_active", "updated_at"])
            from common.audit import log_action
            log_action(actor=request.user, action="activate", instance=obj,
                       reason="vendor activated")
        return Response(VendorSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate a vendor. Deactivation is allowed even if referenced;
        referenced records retain the inactive vendor. Deletion is blocked when referenced.
        """
        try:
            obj = Vendor.all_objects.get(pk=pk)
        except Vendor.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)
        if obj.is_deleted:
            return Response(
                {"detail": "Cannot deactivate a deleted vendor."}, status=400)
        if not obj.is_active:
            return Response({"detail": "Vendor is already inactive."}, status=400)
        with transaction.atomic():
            obj = Vendor.objects.select_for_update().get(pk=obj.pk)
            if obj.is_deleted:
                return Response(
                    {"detail": "Cannot deactivate a deleted vendor."}, status=400)
            if not obj.is_active:
                return Response({"detail": "Vendor is already inactive."}, status=400)
            # Check for referencing assets/stock items for warning
            asset_count = obj.assets.count()
            stock_item_count = obj.stock_items.count()
            obj.is_active = False
            obj.save(update_fields=["is_active", "updated_at"])
            from common.audit import log_action
            log_action(actor=request.user, action="deactivate", instance=obj,
                       reason="vendor deactivated")
        data = VendorSerializer(obj).data
        if asset_count > 0 or stock_item_count > 0:
            data["warning"] = (
                f"Vendor deactivated. {asset_count} asset(s) and {stock_item_count} stock item(s) "
                f"still reference this vendor (inactive vendors are excluded from new selections)."
            )
        return Response(data)

    def destroy(self, request, *args, **kwargs):
        from rest_framework.response import Response
        from rest_framework import status
        try:
            instance = Vendor.all_objects.get(pk=kwargs["pk"])
        except Vendor.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)
        if instance.is_deleted:
            return Response(
                {"detail": "Vendor is already deleted."}, status=400)
        # Check for referencing records before soft-delete (under lock)
        with transaction.atomic():
            instance = Vendor.objects.select_for_update().get(pk=instance.pk)
            if instance.is_deleted:
                return Response(
                    {"detail": "Vendor is already deleted."}, status=400)
            asset_count = instance.assets.count()
            stock_item_count = instance.stock_items.count()
            if asset_count > 0 or stock_item_count > 0:
                return Response({
                    "detail": f"Cannot soft-delete vendor: "
                               f"{asset_count} asset(s) and "
                               f"{stock_item_count} stock item(s) "
                               f"reference it.",
                    "hint": "Deactivate the vendor instead, or reassign records first."
                }, status=status.HTTP_409_CONFLICT)
            instance.soft_delete(by_user=request.user,
                                 reason="vendor removed")
            from common.audit import log_action
            log_action(actor=request.user, action="soft_delete", instance=instance,
                       reason="vendor soft-deleted")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Restore a soft-deleted vendor, respecting uniqueness constraints."""
        try:
            instance = Vendor.all_objects.get(pk=pk)
        except Vendor.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)
        if not instance.is_deleted:
            return Response({"detail": "Vendor is not deleted."}, status=400)
        with transaction.atomic():
            instance = Vendor.all_objects.select_for_update().get(pk=instance.pk)
            if not instance.is_deleted:
                return Response({"detail": "Vendor is not deleted."}, status=400)
            try:
                instance.restore()
            except IntegrityError:
                from rest_framework.exceptions import ValidationError
                raise ValidationError(
                    {"detail": "Cannot restore: a vendor with that name or code already exists."})
            from common.audit import log_action
            log_action(actor=request.user, action="restore", instance=instance,
                       reason="vendor restored")
        return Response(VendorSerializer(instance).data)


