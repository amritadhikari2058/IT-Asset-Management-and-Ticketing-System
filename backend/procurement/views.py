import hashlib
import os
from datetime import date, datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.models import User
from assets.models import Asset, AssetCategory
from common.attachment_security import (
    add_download_security_headers, safe_content_disposition_filename,
)
from common.audit import log_action
from common.models import Notification
from inventory.models import StockMovement
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem,
    ProcurementHistory, ProcurementAttachment, ProcurementAssetReceiptItem,
    derive_discrepancy_status,
)
from .serializers import (
    ProcurementSettingSerializer, PurchaseRequestSerializer,
    PurchaseRequestItemSerializer, PurchaseQuotationSerializer,
    PurchaseOrderSerializer, PurchaseOrderItemSerializer,
    GoodsReceiptSerializer, GoodsReceiptItemSerializer,
    ProcurementAttachmentSerializer, ProcurementAssetReceiptItemSerializer,
    RegisterProcurementAssetSerializer,
)


def is_staff(user):
    return user.is_authenticated and user.role in (
        "system_admin", "it_manager", "it_support")


def is_manager_or_admin(user):
    return user.is_authenticated and user.role in ("system_admin", "it_manager")


def can_view_procurement(user):
    return is_staff(user) or bool(getattr(user, "is_superuser", False))


class ProcurementPagination(PageNumberPagination):
    """Bounded pagination shared by every procurement list endpoint."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# Query-string helpers
# ---------------------------------------------------------------------------

def _param(request, *names):
    for name in names:
        value = request.query_params.get(name)
        if value not in (None, ""):
            return value
    return None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_bool(value):
    if value is None:
        return None
    return str(value).lower() in ("1", "true", "yes", "on")


def _apply_date_range(qs, request, field, start_param, end_param):
    start = _as_date(_param(request, start_param))
    end = _as_date(_param(request, end_param))
    if start:
        qs = qs.filter(**{f"{field}__gte": start})
    if end:
        # Inclusive end date for datetime fields.
        qs = qs.filter(**{f"{field}__date__lte" if field.endswith("_at") else f"{field}__lte": end})
    return qs


def _apply_search(qs, request, fields):
    term = _param(request, "search", "q")
    if not term:
        return qs
    query = Q()
    for field in fields:
        query |= Q(**{f"{field}__icontains": term})
    return qs.filter(query).distinct()


def _apply_ordering(qs, request, allowed, default):
    """Allowlisted ordering only: an unknown or injected value is ignored."""
    raw = _param(request, "ordering")
    if raw:
        requested = raw.split(",")
        keys = []
        for key in requested:
            normalized = key[1:] if key.startswith("-") else key
            if normalized in allowed:
                keys.append(key)
        if keys:
            return qs.order_by(*keys)
    return qs.order_by(*default)


# ---------------------------------------------------------------------------
# Shared business helpers
# ---------------------------------------------------------------------------

def recalculate_po_status(po):
    """Derive the PO receipt status from its line quantities."""
    lines = list(po.items.all())
    if not lines:
        return po
    covered = 0
    arrived = 0
    for line in lines:
        booked = (line.received_qty or 0) + (line.rejected_qty or 0) + (line.damaged_qty or 0)
        arrived += booked
        if booked >= (line.quantity or 0):
            covered += 1
    if covered == len(lines):
        new_status = "received"
    elif arrived > 0:
        new_status = "partially_received"
    else:
        new_status = None
    if new_status and po.status not in ("closed", "cancelled") and po.status != new_status:
        po.status = new_status
        po.save(update_fields=["status", "total", "updated_at"])
    return po


def _notify(user, title, body, instance):
    if user is None:
        return
    Notification.objects.create(
        recipient=user,
        title=title[:255],
        body=body,
        entity_type=f"{instance._meta.app_label}.{instance._meta.model_name}",
        object_id=str(instance.pk),
    )


def _check_version(instance, payload):
    """Return True when an expected version was supplied and is stale."""
    expected = payload.get("version")
    if expected in (None, ""):
        return False
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        return True
    return expected != instance.version


def _receipt_lines_for(po):
    return GoodsReceiptItem.objects.filter(
        goods_receipt__purchase_order=po, goods_receipt__is_deleted=False)


class ProcurementSettingViewSet(viewsets.ModelViewSet):
    queryset = ProcurementSetting.objects.all()
    serializer_class = ProcurementSettingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "current"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]


# ---------------------------------------------------------------------------
# Purchase requests
# ---------------------------------------------------------------------------

class PurchaseRequestViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequest.objects.all()
    serializer_class = PurchaseRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseRequest.objects.select_related(
            "requester", "department", "approver").prefetch_related("items", "quotations")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(requester=user)

        status_value = _param(self.request, "status")
        if status_value:
            qs = qs.filter(status=status_value)
        requester = _as_int(_param(self.request, "requester"))
        if requester:
            qs = qs.filter(requester_id=requester)
        department = _as_int(_param(self.request, "department"))
        if department:
            qs = qs.filter(department_id=department)
        approval = _param(self.request, "approval", "approval_decision")
        if approval is not None:
            qs = qs.filter(approval_decision=approval)
        selected_vendor = _as_int(_param(self.request, "selected_vendor"))
        if selected_vendor:
            qs = qs.filter(
                quotations__is_selected=True, quotations__vendor_id=selected_vendor)
        has_po = _as_bool(_param(self.request, "has_po"))
        if has_po is True:
            qs = qs.filter(purchase_orders__is_deleted=False)
        elif has_po is False:
            qs = qs.filter(purchase_orders__isnull=True)
        qs = _apply_date_range(qs, self.request, "created_at",
                               "created_from", "created_to")
        qs = _apply_search(qs, self.request, [
            "pr_number", "reason", "notes", "requester__email",
        ])
        return _apply_ordering(
            qs, self.request,
            {"created_at", "updated_at", "estimated_total", "pr_number", "status"},
            ["-created_at"],
        ).distinct()

    def perform_create(self, serializer):
        pr = serializer.save(requester=self.request.user,
                             department=self.request.user.home_department)
        ProcurementHistory.objects.create(
            purchase_request=pr, actor=self.request.user, action="created",
            detail="Purchase request created")
        log_action(actor=self.request.user, action="create", instance=pr,
                   reason="purchase request created")

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        pr = self.get_object()
        if pr.requester != request.user and not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status not in ("draft", "returned_for_correction"):
            return Response({"detail": "Cannot submit in current status"},
                            status=status.HTTP_400_BAD_REQUEST)

        settings = ProcurementSetting.get_settings()
        pr.requires_system_admin_approval = pr.estimated_total >= settings.approval_threshold
        pr.status = "pending_approval"
        pr.version = (pr.version or 1) + 1
        pr.save()
        ProcurementHistory.objects.create(
            purchase_request=pr, actor=request.user, action="submitted",
            detail="Submitted for approval")
        log_action(actor=request.user, action="update", instance=pr,
                   reason="purchase request submitted")
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        pr = self.get_object()
        role = getattr(request.user, "role", "")
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.requester == request.user:
            return Response({"detail": "Cannot approve own request"},
                            status=status.HTTP_400_BAD_REQUEST)
        if pr.status != "pending_approval":
            return Response({"detail": "Not pending approval"},
                            status=status.HTTP_400_BAD_REQUEST)
        if pr.requires_system_admin_approval and role != "system_admin":
            return Response({"detail": "System Admin approval required"},
                            status=status.HTTP_403_FORBIDDEN)

        pr.status = "approved"
        pr.approver = request.user
        pr.approval_decision = "approved"
        pr.approval_reason = request.data.get("reason", "")
        pr.approved_at = timezone.now()
        pr.version = (pr.version or 1) + 1
        pr.save()
        ProcurementHistory.objects.create(
            purchase_request=pr, actor=request.user, action="approved",
            detail=pr.approval_reason or "Approved")
        log_action(actor=request.user, action="approve", instance=pr,
                   reason="purchase request approved")
        _notify(pr.requester, f"{pr.pr_number} approved",
                pr.approval_reason or "Your purchase request was approved.", pr)
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        pr = self.get_object()
        role = getattr(request.user, "role", "")
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.requester == request.user:
            return Response({"detail": "Cannot reject own request"},
                            status=status.HTTP_400_BAD_REQUEST)
        if pr.status != "pending_approval":
            return Response({"detail": "Not pending approval"},
                            status=status.HTTP_400_BAD_REQUEST)
        if pr.requires_system_admin_approval and role != "system_admin":
            return Response({"detail": "System Admin approval required"},
                            status=status.HTTP_403_FORBIDDEN)

        pr.status = "rejected"
        pr.approver = request.user
        pr.approval_decision = "rejected"
        pr.approval_reason = request.data.get("reason", "")
        pr.approved_at = timezone.now()
        pr.version = (pr.version or 1) + 1
        pr.save()
        ProcurementHistory.objects.create(
            purchase_request=pr, actor=request.user, action="rejected",
            detail=pr.approval_reason or "Rejected")
        log_action(actor=request.user, action="reject", instance=pr,
                   reason="purchase request rejected")
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def return_for_correction(self, request, pk=None):
        pr = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status != "pending_approval":
            return Response({"detail": "Not pending approval"},
                            status=status.HTTP_400_BAD_REQUEST)

        pr.status = "returned_for_correction"
        pr.approver = request.user
        pr.approval_decision = "returned"
        pr.approval_reason = request.data.get("reason", "")
        pr.version = (pr.version or 1) + 1
        pr.save()
        ProcurementHistory.objects.create(
            purchase_request=pr, actor=request.user, action="returned",
            detail=pr.approval_reason or "Returned for correction")
        log_action(actor=request.user, action="update", instance=pr,
                   reason="purchase request returned for correction")
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a request that has not progressed to an order or receipt."""
        reason = str(request.data.get("reason", "") or "").strip()
        with transaction.atomic():
            pr = get_object_or_404(
                PurchaseRequest.objects.select_for_update(), pk=pk)
            if not (is_manager_or_admin(request.user)
                    or pr.requester_id == request.user.pk
                    or getattr(request.user, "is_superuser", False)):
                raise PermissionDenied("Forbidden")
            if pr.status == "cancelled":
                return Response({"detail": "This request is already cancelled."},
                                status=status.HTTP_400_BAD_REQUEST)
            if _check_version(pr, request.data):
                return Response(
                    {"detail": "This request changed since you loaded it. "
                               "Reload and retry."},
                    status=status.HTTP_409_CONFLICT)
            if pr.status in ("po_generated", "closed") or pr.purchase_orders.filter(
                    is_deleted=False).exists():
                return Response(
                    {"detail": "A purchase request cannot be cancelled after a "
                               "purchase order has been generated."},
                    status=status.HTTP_400_BAD_REQUEST)
            if _receipt_lines_for_order_pr(pr):
                return Response(
                    {"detail": "Receipt activity exists for this request."},
                    status=status.HTTP_400_BAD_REQUEST)
            if not reason:
                return Response({"reason": "A cancellation reason is required."},
                                status=status.HTTP_400_BAD_REQUEST)

            pr.status = "cancelled"
            pr.cancellation_reason = reason
            pr.cancelled_at = timezone.now()
            pr.version = (pr.version or 1) + 1
            pr.save()
            ProcurementHistory.objects.create(
                purchase_request=pr, actor=request.user, action="cancelled",
                detail=reason)
            log_action(actor=request.user, action="update", instance=pr,
                       reason=f"purchase request cancelled: {reason}")
            _notify(pr.requester, f"{pr.pr_number} cancelled", reason, pr)
        return Response(self.get_serializer(pr).data)


def _receipt_lines_for_order_pr(pr):
    return GoodsReceiptItem.objects.filter(
        purchase_order_item__purchase_order__purchase_request=pr,
        goods_receipt__is_deleted=False).exists()


class PurchaseRequestItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequestItem.objects.all()
    serializer_class = PurchaseRequestItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseRequestItem.objects.all()
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(purchase_request__requester=user)
        request_id = _as_int(_param(self.request, "purchase_request"))
        if request_id:
            qs = qs.filter(purchase_request_id=request_id)
        return qs


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------

class PurchaseQuotationViewSet(viewsets.ModelViewSet):
    queryset = PurchaseQuotation.objects.all()
    serializer_class = PurchaseQuotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseQuotation.objects.select_related(
            "vendor", "purchase_request", "selected_by")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(purchase_request__requester=user)

        pr_id = _as_int(_param(self.request, "purchase_request"))
        if pr_id:
            qs = qs.filter(purchase_request_id=pr_id)
        vendor = _as_int(_param(self.request, "vendor"))
        if vendor:
            qs = qs.filter(vendor_id=vendor)
        selected = _as_bool(_param(self.request, "selected", "is_selected"))
        if selected is not None:
            qs = qs.filter(is_selected=selected)
        qs = _apply_search(qs, self.request, [
            "vendor__name", "purchase_request__pr_number", "selection_reason",
        ])
        return _apply_ordering(
            qs, self.request,
            {"quoted_amount", "created_at", "vendor", "is_selected"},
            ["-quoted_amount"],
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def select(self, request, pk=None):
        quote = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")

        PurchaseQuotation.objects.filter(
            purchase_request=quote.purchase_request).update(is_selected=False)
        quote.is_selected = True
        quote.selected_by = request.user
        quote.selected_at = timezone.now()
        quote.selection_reason = request.data.get("reason", "")
        quote.save()
        log_action(actor=request.user, action="update", instance=quote,
                   reason="quotation selected")
        return Response(self.get_serializer(quote).data)


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseOrder.objects.select_related(
            "vendor", "purchase_request", "created_by", "approver"
        ).prefetch_related("items", "goods_receipts")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(created_by=user)

        status_value = _param(self.request, "status")
        if status_value:
            qs = qs.filter(status=status_value)
        vendor = _as_int(_param(self.request, "vendor"))
        if vendor:
            qs = qs.filter(vendor_id=vendor)
        department = _as_int(_param(self.request, "department"))
        if department:
            qs = qs.filter(purchase_request__department_id=department)
        pr_id = _as_int(_param(self.request, "purchase_request"))
        if pr_id:
            qs = qs.filter(purchase_request_id=pr_id)
        qs = _apply_date_range(qs, self.request, "created_at",
                               "created_from", "created_to")
        qs = _apply_date_range(qs, self.request, "expected_delivery_date",
                               "expected_from", "expected_to")
        receipt_status = _param(self.request, "receipt_status")
        if receipt_status == "received":
            qs = qs.filter(status="received")
        elif receipt_status == "partially_received":
            qs = qs.filter(status="partially_received")
        elif receipt_status == "unreceived":
            qs = qs.filter(status__in=[
                "draft", "pending_approval", "approved", "sent_to_vendor"])
        qs = _apply_search(qs, self.request, [
            "po_number", "purchase_request__pr_number", "vendor__name",
        ])
        return _apply_ordering(
            qs, self.request,
            {"created_at", "expected_delivery_date", "total", "po_number", "status"},
            ["-created_at"],
        ).distinct()

    def create(self, request, *args, **kwargs):
        """Purchase orders are generated, never created directly.

        Returning an explicit, readable 405 avoids the raw NOT NULL error a
        direct POST would otherwise raise because `created_by` is read-only.
        """
        return Response(
            {"detail": "Purchase orders are generated from an approved purchase "
                       "request and a selected quotation using the "
                       "generate_from_pr action."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def generate_from_pr(self, request, pk=None):
        pr = get_object_or_404(PurchaseRequest, pk=pk)
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status != "approved":
            return Response({"detail": "Purchase request must be approved"},
                            status=status.HTTP_400_BAD_REQUEST)

        selected_quote = pr.quotations.filter(is_selected=True).first()
        if not selected_quote:
            return Response({"detail": "No quotation selected"},
                            status=status.HTTP_400_BAD_REQUEST)

        settings = ProcurementSetting.get_settings()

        with transaction.atomic():
            po = PurchaseOrder.objects.create(
                purchase_request=pr,
                vendor=selected_quote.vendor,
                created_by=request.user,
                status="pending_approval",
                delivery_address=settings.delivery_address,
                terms=settings.po_terms,
                currency=settings.currency,
                requires_system_admin_approval=(
                    (selected_quote.quoted_amount or 0) >= settings.approval_threshold),
            )
            for item in pr.items.all():
                PurchaseOrderItem.objects.create(
                    purchase_order=po,
                    item_name=item.item_name,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.estimated_unit_price or 0,
                    is_serialized=False,
                )

            lines = list(po.items.all())
            po.subtotal = sum((line.quantity or 0) * (line.unit_price or 0) for line in lines)
            po.tax = sum(line.tax or 0 for line in lines)
            po.discount = sum(line.discount or 0 for line in lines)
            po.save()

            pr.status = "po_generated"
            pr.version = (pr.version or 1) + 1
            pr.save()

            ProcurementHistory.objects.create(
                purchase_order=po, actor=request.user, action="po_generated",
                detail=f"PO generated from {pr.pr_number}")
            ProcurementHistory.objects.create(
                purchase_request=pr, actor=request.user, action="po_generated",
                detail=f"PO {po.po_number} generated")
            log_action(actor=request.user, action="create", instance=po,
                       reason="purchase order generated")

        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        po = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if po.created_by == request.user:
            return Response({"detail": "Cannot approve own PO"},
                            status=status.HTTP_400_BAD_REQUEST)
        if po.status != "pending_approval":
            return Response({"detail": "Not pending approval"},
                            status=status.HTTP_400_BAD_REQUEST)
        if po.requires_system_admin_approval and getattr(
                request.user, "role", "") != "system_admin":
            return Response({"detail": "System Admin approval required"},
                            status=status.HTTP_403_FORBIDDEN)

        po.status = "approved"
        po.approver = request.user
        po.approval_decision = "approved"
        po.approval_reason = request.data.get("reason", "")
        po.approved_at = timezone.now()
        po.version = (po.version or 1) + 1
        po.save()
        ProcurementHistory.objects.create(
            purchase_order=po, actor=request.user, action="approved",
            detail=po.approval_reason or "Approved")
        log_action(actor=request.user, action="approve", instance=po,
                   reason="purchase order approved")
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        po = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if po.status != "pending_approval":
            return Response({"detail": "Not pending approval"},
                            status=status.HTTP_400_BAD_REQUEST)
        if po.requires_system_admin_approval and getattr(
                request.user, "role", "") != "system_admin":
            return Response({"detail": "System Admin approval required"},
                            status=status.HTTP_403_FORBIDDEN)

        po.status = "rejected"
        po.approver = request.user
        po.approval_decision = "rejected"
        po.approval_reason = request.data.get("reason", "")
        po.version = (po.version or 1) + 1
        po.save()
        ProcurementHistory.objects.create(
            purchase_order=po, actor=request.user, action="rejected",
            detail=po.approval_reason or "Rejected")
        log_action(actor=request.user, action="reject", instance=po,
                   reason="purchase order rejected")
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def send_to_vendor(self, request, pk=None):
        po = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if po.status != "approved":
            return Response({"detail": "PO must be approved first"},
                            status=status.HTTP_400_BAD_REQUEST)

        po.status = "sent_to_vendor"
        po.sent_at = timezone.now()
        po.version = (po.version or 1) + 1
        po.save()
        ProcurementHistory.objects.create(
            purchase_order=po, actor=request.user, action="sent",
            detail="Sent to vendor")
        log_action(actor=request.user, action="update", instance=po,
                   reason="purchase order sent to vendor")
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        reason = str(request.data.get("reason", "") or "").strip()
        with transaction.atomic():
            po = get_object_or_404(
                PurchaseOrder.objects.select_for_update(), pk=pk)
            # Scope the locked row to what this actor may see.
            if not (is_manager_or_admin(request.user)
                    or getattr(request.user, "is_superuser", False)):
                raise PermissionDenied("Forbidden")
            if po.status == "cancelled":
                return Response({"detail": "This order is already cancelled."},
                                status=status.HTTP_400_BAD_REQUEST)
            if po.status in ("closed", "received"):
                return Response(
                    {"detail": "A received or closed order cannot be cancelled."},
                    status=status.HTTP_400_BAD_REQUEST)
            if _check_version(po, request.data):
                return Response(
                    {"detail": "This order changed since you loaded it. "
                               "Reload and retry."},
                    status=status.HTTP_409_CONFLICT)
            received = _receipt_lines_for(po).exists()
            if received:
                return Response(
                    {"detail": "This order already has receipt activity. "
                               "Close the remaining balance instead of cancelling."},
                    status=status.HTTP_400_BAD_REQUEST)
            if not reason:
                return Response({"reason": "A cancellation reason is required."},
                                status=status.HTTP_400_BAD_REQUEST)

            po.status = "cancelled"
            po.cancellation_reason = reason
            po.cancelled_at = timezone.now()
            po.version = (po.version or 1) + 1
            po.save()
            ProcurementHistory.objects.create(
                purchase_order=po, actor=request.user, action="cancelled",
                detail=reason)
            log_action(actor=request.user, action="update", instance=po,
                       reason=f"purchase order cancelled: {reason}")
            _notify(po.created_by, f"{po.po_number} cancelled", reason, po)
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        reason = str(request.data.get("reason", "") or "").strip()
        with transaction.atomic():
            po = get_object_or_404(
                PurchaseOrder.objects.select_for_update(), pk=pk)
            if not (is_manager_or_admin(request.user)
                    or getattr(request.user, "is_superuser", False)):
                raise PermissionDenied("Forbidden")
            if po.status == "closed":
                return Response({"detail": "This order is already closed."},
                                status=status.HTTP_400_BAD_REQUEST)
            if po.status in ("draft", "pending_approval", "rejected", "cancelled"):
                return Response(
                    {"detail": "Only an issued or partially received order can "
                               "be closed."},
                    status=status.HTTP_400_BAD_REQUEST)
            if _check_version(po, request.data):
                return Response(
                    {"detail": "This order changed since you loaded it. "
                               "Reload and retry."},
                    status=status.HTTP_409_CONFLICT)

            outstanding = 0
            for line in po.items.all():
                booked = ((line.received_qty or 0) + (line.rejected_qty or 0)
                          + (line.damaged_qty or 0))
                outstanding += max(0, (line.quantity or 0) - booked)
            if outstanding and not reason:
                return Response(
                    {"reason": "A closure reason is required when an "
                               "outstanding quantity remains."},
                    status=status.HTTP_400_BAD_REQUEST)

            po.status = "closed"
            po.closed_at = timezone.now()
            po.closure_reason = reason
            po.version = (po.version or 1) + 1
            po.save()
            ProcurementHistory.objects.create(
                purchase_order=po, actor=request.user, action="closed",
                detail=reason or "Fully received")
            log_action(actor=request.user, action="update", instance=po,
                       reason=f"purchase order closed: {reason or 'fully received'}")
            _notify(po.created_by, f"{po.po_number} closed",
                    reason or "Fully received.", po)
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        """Protected, server-rendered Purchase Order PDF."""
        po = self.get_object()
        if not can_view_procurement(request.user):
            raise PermissionDenied("Forbidden")

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
        from io import BytesIO

        settings = ProcurementSetting.get_settings()
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=18 * mm, bottomMargin=18 * mm,
            title=f"Purchase Order {po.po_number}",
            author=settings.organization_name,
            # Uncompressed content keeps the generated text greppable/testable;
            # the document is small and carries no secrets.
            pageCompression=0,
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph(settings.organization_name or "Purchase Order",
                      styles["Title"]),
            Paragraph(f"Purchase Order {po.po_number}", styles["Heading2"]),
            Spacer(1, 6 * mm),
        ]
        header_rows = [
            ["Order date", po.created_at.strftime("%Y-%m-%d")],
            ["Vendor", po.vendor.name],
        ]
        if po.vendor.address:
            header_rows.append(["Vendor address", po.vendor.address])
        if po.vendor.contact_person:
            header_rows.append(["Vendor contact", po.vendor.contact_person])
        if po.vendor.email:
            header_rows.append(["Vendor email", po.vendor.email])
        if po.vendor.phone:
            header_rows.append(["Vendor phone", po.vendor.phone])
        header_rows += [
            ["Delivery address", po.delivery_address or "—"],
            ["Request number",
             po.purchase_request.pr_number if po.purchase_request_id else "—"],
            ["Currency", po.currency],
        ]
        if po.expected_delivery_date:
            header_rows.append(["Expected delivery",
                                po.expected_delivery_date.isoformat()])
        header = Table(header_rows, colWidths=[45 * mm, 110 * mm])
        header.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story += [header, Spacer(1, 6 * mm)]

        line_rows = [["Item", "Qty", "Unit price", "Tax", "Discount", "Line total"]]
        for line in po.items.all():
            line_rows.append([
                Paragraph(line.item_name, styles["BodyText"]),
                str(line.quantity),
                f"{line.unit_price:.2f}",
                f"{line.tax:.2f}",
                f"{line.discount:.2f}",
                f"{line.total:.2f}",
            ])
        table = Table(
            line_rows, colWidths=[70 * mm, 15 * mm, 25 * mm, 18 * mm, 22 * mm, 25 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story += [table, Spacer(1, 4 * mm)]

        totals = [
            ["Subtotal", f"{po.currency} {po.subtotal:.2f}"],
            ["Discount", f"{po.currency} {po.discount:.2f}"],
            ["Tax", f"{po.currency} {po.tax:.2f}"],
            ["Grand total", f"{po.currency} {po.total:.2f}"],
        ]
        totals_table = Table(totals, colWidths=[55 * mm, 45 * mm], hAlign="RIGHT")
        totals_table.setStyle(TableStyle([
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
        ]))
        story += [totals_table, Spacer(1, 6 * mm)]

        footer_rows = []
        if po.terms:
            footer_rows.append(["Payment terms", po.terms])
        footer_rows.append(["Status", po.get_status_display()])
        if settings.authorized_signatory_name:
            footer_rows.append([
                "Authorized approver",
                f"{settings.authorized_signatory_name}"
                + (f", {settings.authorized_signatory_title}"
                   if settings.authorized_signatory_title else ""),
            ])
        footer = Table(footer_rows, colWidths=[45 * mm, 110 * mm])
        footer.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(footer)
        document.build(story)

        safe_name = safe_content_disposition_filename(f"{po.po_number}.pdf")
        response = FileResponse(
            BytesIO(buffer.getvalue()), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        log_action(actor=request.user, action="export", instance=po,
                   reason="purchase order PDF downloaded")
        return response


class PurchaseOrderItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrderItem.objects.all()
    serializer_class = PurchaseOrderItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        qs = PurchaseOrderItem.objects.all()
        if not can_view_procurement(self.request.user) \
                and not getattr(self.request.user, "is_superuser", False):
            raise PermissionDenied("Forbidden")
        po_id = _as_int(_param(self.request, "purchase_order"))
        if po_id:
            qs = qs.filter(purchase_order_id=po_id)
        return qs


# ---------------------------------------------------------------------------
# Goods receipts
# ---------------------------------------------------------------------------

class GoodsReceiptViewSet(viewsets.ModelViewSet):
    queryset = GoodsReceipt.objects.all()
    serializer_class = GoodsReceiptSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = GoodsReceipt.objects.select_related(
            "purchase_order", "purchase_order__vendor", "received_by"
        ).prefetch_related("items")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(received_by=user)

        po_id = _as_int(_param(self.request, "purchase_order"))
        if po_id:
            qs = qs.filter(purchase_order_id=po_id)
        pr_id = _as_int(_param(self.request, "purchase_request"))
        if pr_id:
            qs = qs.filter(purchase_order__purchase_request_id=pr_id)
        vendor = _as_int(_param(self.request, "vendor"))
        if vendor:
            qs = qs.filter(purchase_order__vendor_id=vendor)
        received_by = _as_int(_param(self.request, "received_by"))
        if received_by:
            qs = qs.filter(received_by_id=received_by)
        qs = _apply_date_range(qs, self.request, "received_at",
                               "received_from", "received_to")
        discrepancy = _as_bool(_param(self.request, "discrepancy"))
        if discrepancy is True:
            qs = qs.filter(
                Q(items__quantity_rejected__gt=0)
                | Q(items__quantity_damaged__gt=0)).distinct()
        elif discrepancy is False:
            qs = qs.exclude(
                Q(items__quantity_rejected__gt=0)
                | Q(items__quantity_damaged__gt=0)).distinct()
        qs = _apply_search(qs, self.request, [
            "gr_number", "purchase_order__po_number", "delivery_note_number",
            "invoice_number",
        ])
        return _apply_ordering(
            qs, self.request,
            {"received_at", "gr_number", "created_at"},
            ["-received_at"],
        ).distinct()

    def perform_create(self, serializer):
        po = serializer.validated_data.get("purchase_order")
        if po and po.status in ("closed", "cancelled"):
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"purchase_order": "This purchase order can no longer accept "
                                   "receipts."})
        with transaction.atomic():
            gr = serializer.save(received_by=self.request.user)
            ProcurementHistory.objects.create(
                purchase_order=gr.purchase_order, actor=self.request.user,
                action="received", detail=f"Goods received: {gr.gr_number}")
            log_action(actor=self.request.user, action="create", instance=gr,
                       reason="goods receipt created")
            recalculate_po_status(gr.purchase_order)


class GoodsReceiptItemViewSet(viewsets.ModelViewSet):
    queryset = GoodsReceiptItem.objects.all()
    serializer_class = GoodsReceiptItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        qs = GoodsReceiptItem.objects.all()
        if not can_view_procurement(self.request.user) \
                and not getattr(self.request.user, "is_superuser", False):
            raise PermissionDenied("Forbidden")
        gr_id = _as_int(_param(self.request, "goods_receipt"))
        if gr_id:
            qs = qs.filter(goods_receipt_id=gr_id)
        return qs

    def perform_create(self, serializer):
        """Book an arrival against its PO line.

        `quantity_received` is the total that physically arrived; rejected
        and damaged units are part of that total but never count as
        accepted. Only accepted units roll into `received_qty` and normal
        inventory. Serialized accepted units create pending asset records.
        """
        with transaction.atomic():
            gr = serializer.validated_data.get("goods_receipt")
            if gr is None:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"goods_receipt": "Receipt is required."})
            if gr.purchase_order.status in ("closed", "cancelled"):
                from rest_framework.exceptions import ValidationError
                raise ValidationError(
                    {"goods_receipt": "This purchase order can no longer accept "
                                      "receipts."})
            line = PurchaseOrderItem.objects.select_for_update().get(
                pk=serializer.validated_data["purchase_order_item"].pk)
            arrival = serializer.save()
            accepted = max(
                0,
                (arrival.quantity_received or 0)
                - (arrival.quantity_rejected or 0)
                - (arrival.quantity_damaged or 0),
            )
            line.received_qty = (line.received_qty or 0) + accepted
            line.rejected_qty = (line.rejected_qty or 0) + (arrival.quantity_rejected or 0)
            line.damaged_qty = (line.damaged_qty or 0) + (arrival.quantity_damaged or 0)
            line.save(update_fields=["received_qty", "rejected_qty", "damaged_qty"])

            # Only accepted units enter normal stock, with a real movement row.
            if line.stock_item_id and accepted:
                stock = line.stock_item
                previous = stock.quantity or 0
                stock.quantity = previous + accepted
                stock.save(update_fields=["quantity", "updated_at"])
                StockMovement.objects.create(
                    stock_item=stock,
                    movement_type="receive",
                    quantity=accepted,
                    previous_balance=previous,
                    new_balance=stock.quantity,
                    department=gr.purchase_order.purchase_request.department
                    if gr.purchase_order.purchase_request_id else None,
                    reference=gr.gr_number,
                    recorded_by=self.request.user,
                    reason=f"Goods receipt {gr.gr_number} accepted quantity",
                )

            if line.is_serialized and accepted:
                self._create_pending_assets(arrival, line, accepted)

            recalculate_po_status(arrival.goods_receipt.purchase_order)

    def _create_pending_assets(self, arrival, line, accepted):
        gr = arrival.goods_receipt
        po = gr.purchase_order
        category = line.asset_category
        for sequence in range(1, accepted + 1):
            ProcurementAssetReceiptItem.objects.get_or_create(
                goods_receipt_item=arrival,
                sequence=sequence,
                defaults={
                    "goods_receipt": gr,
                    "purchase_order": po,
                    "purchase_order_item": line,
                    "vendor": po.vendor,
                    "asset_category": category,
                    "status": "pending_registration",
                    "expected_purchase_date": gr.received_at.date(),
                    "purchase_cost": line.unit_price,
                    "warranty_expiry": None,
                },
            )


class ProcurementAssetReceiptItemViewSet(viewsets.ModelViewSet):
    """Pending / registered asset units created from accepted receipts."""

    queryset = ProcurementAssetReceiptItem.objects.all()
    serializer_class = ProcurementAssetReceiptItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination
    http_method_names = ["get", "head", "options", "post"]

    def get_queryset(self):
        user = self.request.user
        qs = ProcurementAssetReceiptItem.objects.select_related(
            "goods_receipt", "purchase_order", "purchase_order_item",
            "vendor", "asset", "asset_category")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(
                Q(purchase_order__created_by=user)
                | Q(goods_receipt__received_by=user))
        status_value = _param(self.request, "status")
        if status_value:
            qs = qs.filter(status=status_value)
        po_id = _as_int(_param(self.request, "purchase_order"))
        if po_id:
            qs = qs.filter(purchase_order_id=po_id)
        gr_id = _as_int(_param(self.request, "goods_receipt"))
        if gr_id:
            qs = qs.filter(goods_receipt_id=gr_id)
        return _apply_ordering(
            qs, self.request, {"created_at", "status"}, ["created_at"])

    @action(detail=True, methods=["post"], url_path="register-asset")
    def register_asset(self, request, pk=None):
        if not can_view_procurement(request.user):
            raise PermissionDenied("Forbidden")
        payload = RegisterProcurementAssetSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        with transaction.atomic():
            item = get_object_or_404(
                ProcurementAssetReceiptItem.objects.select_for_update(), pk=pk)
            # Re-check the scoped permission inside the lock.
            if not (is_manager_or_admin(request.user) or user_is_owner(request.user, item)):
                raise PermissionDenied("Forbidden")
            if item.status == "registered" or item.asset_id:
                return Response(
                    {"detail": "This receipt unit is already registered."},
                    status=status.HTTP_409_CONFLICT)
            if item.status != "pending_registration":
                return Response(
                    {"detail": "Only pending receipt units can be registered."},
                    status=status.HTTP_400_BAD_REQUEST)

            category_id = data.get("category") or (
                item.asset_category_id if item.asset_category_id else None)
            if not category_id:
                return Response(
                    {"category": "Select an asset category for this unit."},
                    status=status.HTTP_400_BAD_REQUEST)
            category = get_object_or_404(AssetCategory, pk=category_id)

            po = item.purchase_order
            purchase_request = po.purchase_request
            department_id = data.get("department")
            if department_id is None and purchase_request is not None:
                department_id = purchase_request.department_id

            if data.get("serial_number"):
                if Asset.objects.filter(
                        serial_number=data["serial_number"]).exists():
                    return Response(
                        {"serial_number": "This serial number is already "
                                          "assigned to an asset."},
                        status=status.HTTP_400_BAD_REQUEST)

            description_parts = [
                po.purchase_request.pr_number if po.purchase_request_id else "",
                f"{item.goods_receipt.gr_number} / {po.po_number}",
            ]
            if data.get("manufacturer"):
                description_parts.append(f"Manufacturer: {data['manufacturer']}")
            if data.get("model"):
                description_parts.append(f"Model: {data['model']}")
            if data.get("notes"):
                description_parts.append(data["notes"])

            try:
                asset = Asset.objects.create(
                    asset_tag=data["asset_tag"],
                    name=data["name"],
                    serial_number=data.get("serial_number", ""),
                    category=category,
                    department_id=department_id,
                    vendor=item.vendor,
                    status="available",
                    location=data.get("location", ""),
                    purchase_date=item.expected_purchase_date or timezone.localdate(),
                    purchase_cost=data.get("purchase_cost")
                    if data.get("purchase_cost") is not None else item.purchase_cost,
                    warranty_expiry=data.get("warranty_expiry"),
                    description="\n".join(p for p in description_parts if p),
                )
            except (DjangoValidationError, IntegrityError) as exc:
                message = "; ".join(
                    exc.messages) if isinstance(exc, DjangoValidationError) else str(exc)
                return Response({"detail": message},
                                status=status.HTTP_400_BAD_REQUEST)

            item.asset = asset
            item.status = "registered"
            item.registered_at = timezone.now()
            item.registered_by = request.user
            item.save(update_fields=[
                "asset", "status", "registered_at", "registered_by"])
            ProcurementHistory.objects.create(
                purchase_order=po, actor=request.user, action="asset_registered",
                detail=f"Asset {asset.asset_tag} registered from "
                       f"{item.goods_receipt.gr_number}")
            log_action(actor=request.user, action="create", instance=asset,
                       reason="procurement receipt asset registered")

        return Response(self.get_serializer(item).data)


def user_is_owner(user, item):
    return (item.purchase_order.created_by_id == user.pk
            or item.goods_receipt.received_by_id == user.pk)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def _can_access_parent(user, attachment):
    if is_manager_or_admin(user) or getattr(user, "is_superuser", False):
        return True
    if attachment.purchase_request_id:
        return attachment.purchase_request.requester_id == user.pk
    if attachment.purchase_order_id:
        return attachment.purchase_order.created_by_id == user.pk
    if attachment.goods_receipt_id:
        return attachment.goods_receipt.received_by_id == user.pk
    if attachment.quotation_id:
        return attachment.quotation.purchase_request.requester_id == user.pk
    return False


class ProcurementAttachmentViewSet(viewsets.ModelViewSet):
    queryset = ProcurementAttachment.objects.all()
    serializer_class = ProcurementAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProcurementPagination
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = ProcurementAttachment.objects.select_related(
            "purchase_request", "purchase_order", "goods_receipt",
            "quotation", "uploaded_by")
        if not (is_manager_or_admin(user) or getattr(user, "is_superuser", False)):
            qs = qs.filter(
                Q(purchase_request__requester=user)
                | Q(purchase_order__created_by=user)
                | Q(goods_receipt__received_by=user)
                | Q(quotation__purchase_request__requester=user)
            )
        for param in ("purchase_request", "purchase_order",
                      "goods_receipt", "quotation"):
            value = _as_int(_param(self.request, param))
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        status_value = _param(self.request, "status")
        if status_value:
            qs = qs.filter(status=status_value)
        return qs.distinct()

    def perform_create(self, serializer):
        if not can_view_procurement(self.request.user):
            raise PermissionDenied("Forbidden")
        upload = self.request.FILES.get("file")
        if not upload:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"file": "No attachment file was provided."})
        parent = (
            serializer.validated_data.get("purchase_request")
            or serializer.validated_data.get("purchase_order")
            or serializer.validated_data.get("goods_receipt")
            or serializer.validated_data.get("quotation")
        )
        provisional = ProcurementAttachment(
            purchase_request=serializer.validated_data.get("purchase_request"),
            purchase_order=serializer.validated_data.get("purchase_order"),
            goods_receipt=serializer.validated_data.get("goods_receipt"),
            quotation=serializer.validated_data.get("quotation"),
        )
        if not _can_access_parent(self.request.user, provisional):
            raise PermissionDenied("Forbidden")

        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)

        serializer.save(
            uploaded_by=self.request.user,
            original_filename=upload.name,
            content_type=upload.content_type or "application/octet-stream",
            size=upload.size,
            checksum=digest.hexdigest(),
        )
        if parent is not None:
            log_action(actor=self.request.user, action="create",
                       instance=parent, reason="procurement attachment uploaded")

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        attachment = self.get_object()
        if not _can_access_parent(request.user, attachment):
            raise PermissionDenied("Forbidden")
        if attachment.status == "archived":
            raise Http404("Attachment is archived.")
        if not attachment.file:
            raise Http404("Attachment file is unavailable.")
        try:
            handle = attachment.file.open("rb")
        except (FileNotFoundError, OSError, ValueError):
            raise Http404("Attachment file is unavailable.")
        safe_name = safe_content_disposition_filename(attachment.original_filename)
        response = FileResponse(
            handle, content_type=attachment.content_type or "application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        response["Cache-Control"] = "private, no-store"
        add_download_security_headers(response)
        return response

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        attachment = self.get_object()
        if not _can_access_parent(request.user, attachment):
            raise PermissionDenied("Forbidden")
        attachment.status = "archived"
        attachment.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(attachment).data)


# ---------------------------------------------------------------------------
# Dashboard aggregate
# ---------------------------------------------------------------------------

def _dashboard_scope(user):
    """Role-scoped base querysets for the aggregate endpoint."""
    manager = is_manager_or_admin(user) or getattr(user, "is_superuser", False)
    requests = PurchaseRequest.objects.all()
    orders = PurchaseOrder.objects.all()
    receipts = GoodsReceipt.objects.all()
    if not manager:
        requests = requests.filter(requester=user)
        orders = orders.filter(created_by=user)
        receipts = receipts.filter(received_by=user)
    return requests, orders, receipts


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def procurement_dashboard(request):
    if not can_view_procurement(request.user):
        raise PermissionDenied("Procurement is not available to your role.")

    requests, orders, receipts = _dashboard_scope(request.user)
    date_from = _as_date(_param(request, "date_from"))
    date_to = _as_date(_param(request, "date_to"))
    department = _as_int(_param(request, "department"))
    vendor = _as_int(_param(request, "vendor"))
    currency = _param(request, "currency")

    if date_from:
        requests = requests.filter(created_at__date__gte=date_from)
        orders = orders.filter(created_at__date__gte=date_from)
        receipts = receipts.filter(received_at__date__gte=date_from)
    if date_to:
        requests = requests.filter(created_at__date__lte=date_to)
        orders = orders.filter(created_at__date__lte=date_to)
        receipts = receipts.filter(received_at__date__lte=date_to)
    if department:
        requests = requests.filter(department_id=department)
        orders = orders.filter(purchase_request__department_id=department)
        receipts = receipts.filter(
            purchase_order__purchase_request__department_id=department)
    if vendor:
        requests = requests.filter(quotations__vendor_id=vendor).distinct()
        orders = orders.filter(vendor_id=vendor)
        receipts = receipts.filter(purchase_order__vendor_id=vendor)
    if currency:
        orders = orders.filter(currency=currency)
        receipts = receipts.filter(purchase_order__currency=currency)

    def status_counts(qs):
        return dict(qs.values_list("status").annotate(count=Count("id")).values_list("status", "count"))

    request_counts = status_counts(requests)
    order_counts = status_counts(orders)

    receipt_rows = list(receipts.values_list("id", flat=True))
    receipt_items = GoodsReceiptItem.objects.filter(goods_receipt__in=receipts)
    pending_assets = ProcurementAssetReceiptItem.objects.filter(
        status="pending_registration", purchase_order__in=orders)
    registered_assets = ProcurementAssetReceiptItem.objects.filter(
        status="registered", purchase_order__in=orders)

    # Currency totals: never combined. Ordered and received values are
    # aggregated in the database per currency, then outstanding is derived.
    orders_for_values = orders.exclude(status__in=["cancelled", "rejected"])
    ordered_by_currency = {
        row["currency"] or "—": row["amount"] or 0
        for row in orders_for_values.values("currency").annotate(amount=Sum("total"))
    }
    received_by_currency = {
        row["purchase_order__currency"] or "—": row["amount"] or 0
        for row in PurchaseOrderItem.objects.filter(
            purchase_order__in=orders_for_values
        ).values("purchase_order__currency").annotate(
            amount=Sum(F("received_qty") * F("unit_price")))
    }
    values_by_currency = []
    for code in sorted(set(ordered_by_currency) | set(received_by_currency)):
        ordered_total = ordered_by_currency.get(code, 0)
        received_total = received_by_currency.get(code, 0)
        values_by_currency.append({
            "currency": code,
            "ordered_total": f"{ordered_total:.2f}",
            "received_total": f"{received_total:.2f}",
            "outstanding_total": f"{max(0, ordered_total - received_total):.2f}",
        })

    today = timezone.localdate()
    delivery_base = orders.filter(
        expected_delivery_date__isnull=False,
        status__in=["approved", "sent_to_vendor", "partially_received"],
    )
    upcoming = delivery_base.filter(
        expected_delivery_date__gte=today).order_by("expected_delivery_date")[:10]
    overdue = delivery_base.filter(
        expected_delivery_date__lt=today).order_by("expected_delivery_date")[:10]

    def recent(qs):
        return qs.order_by("-created_at")[:10]

    context = {"request": request}
    recent_requests = PurchaseRequestSerializer(
        recent(requests.select_related("requester", "approver")), many=True,
        context=context).data
    recent_orders = PurchaseOrderSerializer(
        recent(orders.select_related("vendor", "created_by")
               .prefetch_related("items")), many=True, context=context).data
    recent_receipts = GoodsReceiptSerializer(
        receipts.select_related("purchase_order", "received_by")
        .prefetch_related("items").order_by("-received_at")[:10],
        many=True, context=context).data

    discrepancy_items = receipt_items.filter(
        Q(quantity_rejected__gt=0) | Q(quantity_damaged__gt=0)
    ).select_related("goods_receipt", "purchase_order_item")[:10]
    discrepancies = [{
        "id": line.id,
        "goods_receipt": line.goods_receipt_id,
        "gr_number": line.goods_receipt.gr_number,
        "goods_receipt_item": line.id,
        "item_name": line.purchase_order_item.item_name,
        "quantity_rejected": line.quantity_rejected,
        "quantity_damaged": line.quantity_damaged,
        "rejection_reason": line.rejection_reason,
        "damage_notes": line.damage_notes,
    } for line in discrepancy_items]

    upcoming_rows = PurchaseOrderSerializer(
        upcoming.prefetch_related("items"), many=True, context=context).data
    overdue_rows = PurchaseOrderSerializer(
        overdue.prefetch_related("items"), many=True, context=context).data
    pending_rows = ProcurementAssetReceiptItemSerializer(
        pending_assets.select_related(
            "purchase_order", "purchase_order_item", "goods_receipt",
            "vendor", "asset_category").order_by("created_at")[:10],
        many=True, context=context).data

    return Response({
        "purchase_requests": {
            "draft": request_counts.get("draft", 0),
            "pending_manager_approval": request_counts.get("pending_approval", 0),
            "pending_system_admin_approval": requests.filter(
                status="pending_approval",
                requires_system_admin_approval=True).count(),
            "approved": request_counts.get("approved", 0),
            "rejected": request_counts.get("rejected", 0),
            "returned_for_correction": request_counts.get(
                "returned_for_correction", 0),
            "po_generated": request_counts.get("po_generated", 0),
            "cancelled": request_counts.get("cancelled", 0),
        },
        "quotations": {
            "awaiting_collection": requests.filter(
                status="approved", quotations__isnull=True).distinct().count(),
            "awaiting_selection": requests.filter(
                status="approved", quotations__isnull=False,
                quotations__is_selected=False).distinct().count(),
            "selected": requests.filter(
                status="approved", quotations__is_selected=True).distinct().count(),
        },
        "purchase_orders": {
            "draft": order_counts.get("draft", 0),
            "pending_approval": order_counts.get("pending_approval", 0),
            "approved": order_counts.get("approved", 0),
            "sent_to_vendor": order_counts.get("sent_to_vendor", 0),
            "partially_received": order_counts.get("partially_received", 0),
            "fully_received": order_counts.get("received", 0),
            "overdue_delivery": overdue.count(),
            "closed": order_counts.get("closed", 0),
            "cancelled": order_counts.get("cancelled", 0),
        },
        "goods_receipts": {
            "recent": receipts.count(),
            "with_rejections": receipt_items.filter(
                quantity_rejected__gt=0).values(
                "goods_receipt").distinct().count(),
            "with_damage": receipt_items.filter(
                quantity_damaged__gt=0).values(
                "goods_receipt").distinct().count(),
            "with_short_delivery": receipt_items.filter(
                accepted_quantity=0, quantity_received__gt=0).values(
                "goods_receipt").distinct().count(),
        },
        "asset_registration": {
            "pending": pending_assets.count(),
            "completed": registered_assets.count(),
        },
        "values_by_currency": values_by_currency,
        "recent_purchase_requests": recent_requests,
        "recent_purchase_orders": recent_orders,
        "upcoming_deliveries": upcoming_rows,
        "overdue_deliveries": overdue_rows,
        "recent_receipts": recent_receipts,
        "pending_asset_registration": pending_rows,
        "receipt_discrepancies": discrepancies,
        "receipt_count": len(receipt_rows),
    })
