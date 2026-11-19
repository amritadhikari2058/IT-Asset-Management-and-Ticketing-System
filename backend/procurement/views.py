import hashlib
import os
from datetime import date, datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Max, Q, Sum
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
    SupplierInvoice, SupplierInvoiceLine, InvoiceMatchResult, InvoiceException,
    VendorReturn, VendorReturnLine, VendorCreditNote, VendorCreditNoteLine,
    ProcurementFinancialHistory, derive_discrepancy_status,
)
from .serializers import (
    ProcurementSettingSerializer, PurchaseRequestSerializer,
    PurchaseRequestItemSerializer, PurchaseQuotationSerializer,
    PurchaseOrderSerializer, PurchaseOrderItemSerializer,
    GoodsReceiptSerializer, GoodsReceiptItemSerializer,
    ProcurementAttachmentSerializer, ProcurementAssetReceiptItemSerializer,
    RegisterProcurementAssetSerializer,
    SupplierInvoiceListSerializer, SupplierInvoiceDetailSerializer,
    SupplierInvoiceCreateSerializer, SupplierInvoiceUpdateSerializer,
    SupplierInvoiceActionSerializer, SupplierInvoiceSubmitSerializer,
    SupplierInvoiceMatchSerializer, SupplierInvoiceApproveSerializer,
    SupplierInvoiceRejectSerializer, SupplierInvoiceReturnSerializer,
    SupplierInvoiceHoldSerializer, SupplierInvoicePaymentReadySerializer,
    SupplierInvoiceMarkPaidSerializer, SupplierInvoiceCancelSerializer,
    SupplierInvoiceCloseSerializer,
    SupplierInvoiceLineSerializer, SupplierInvoiceLineCreateSerializer,
    InvoiceMatchResultSerializer, InvoiceMatchDetailSerializer, InvoiceReadinessSerializer,
    InvoiceExceptionSerializer, InvoiceExceptionActionSerializer,
    InvoiceExceptionAcceptSerializer, InvoiceExceptionResolveSerializer,
    VendorReturnListSerializer, VendorReturnDetailSerializer, VendorReturnCreateSerializer,
    VendorReturnActionSerializer, VendorReturnShipSerializer,
    VendorReturnReplacementSerializer, VendorReturnCompleteSerializer,
    VendorReturnLineSerializer,
    VendorCreditNoteListSerializer, VendorCreditNoteDetailSerializer,
    VendorCreditNoteCreateSerializer, VendorCreditNoteActionSerializer,
    VendorCreditNoteApplySerializer, VendorCreditNoteLineSerializer,
    ProcurementFinancialHistorySerializer,
)
from .permissions import CanViewProcurement, CanManageProcurementFinance, is_system_admin as p3_is_system_admin
from . import invoice_services, matching_services, return_services



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
    permission_classes = [CanManageProcurementFinance]

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
    permission_classes = [CanViewProcurement]
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

    def update(self, request, *args, **kwargs):
        pr = self.get_object()
        if pr.status not in ("draft", "returned_for_correction"):
            return Response({"detail": "Only draft or returned requests can be edited."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not (is_manager_or_admin(request.user)
                or pr.requester_id == request.user.pk):
            raise PermissionDenied("Forbidden")
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        pr = self.get_object()
        if pr.requester != request.user and not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status not in ("draft", "returned_for_correction"):
            return Response({"detail": "Cannot submit in current status"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not pr.items.exists():
            return Response({"detail": "A purchase request needs at least one line item before submission."},
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
        reason = str(request.data.get("reason", "") or "").strip()
        if not reason:
            return Response({"reason": "A rejection reason is required."},
                            status=status.HTTP_400_BAD_REQUEST)

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
        reason = str(request.data.get("reason", "") or "").strip()
        if not reason:
            return Response({"reason": "A reason is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        pr.status = "returned_for_correction"
        pr.approver = request.user
        pr.approval_decision = "returned"
        pr.approval_reason = reason
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
    permission_classes = [CanViewProcurement]
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

    def _parent_editable(self, pr):
        return pr.status in ("draft", "returned_for_correction")

    def perform_create(self, serializer):
        pr = serializer.validated_data.get("purchase_request")
        if pr is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"purchase_request": "Purchase request is required."})
        if not self._parent_editable(pr):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"purchase_request": "Items can only be added to draft or returned requests."})
        if not (is_manager_or_admin(self.request.user) or pr.requester_id == self.request.user.pk):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Forbidden")
        with transaction.atomic():
            item = serializer.save()
            self._recalculate_request_total(item.purchase_request)

    def perform_update(self, serializer):
        item = self.get_object()
        if not self._parent_editable(item.purchase_request):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": "Items can only be edited on draft or returned requests."})
        if not (is_manager_or_admin(self.request.user) or item.purchase_request.requester_id == self.request.user.pk):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Forbidden")
        with transaction.atomic():
            updated = serializer.save()
            self._recalculate_request_total(updated.purchase_request)

    def perform_destroy(self, instance):
        if not self._parent_editable(instance.purchase_request):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": "Items can only be removed from draft or returned requests."})
        if not (is_manager_or_admin(self.request.user) or instance.purchase_request.requester_id == self.request.user.pk):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Forbidden")
        with transaction.atomic():
            pr = instance.purchase_request
            instance.delete()
            self._recalculate_request_total(pr)

    @staticmethod
    def _recalculate_request_total(pr):
        from decimal import Decimal
        total = Decimal("0")
        for it in pr.items.all():
            line_total = it.estimated_total
            if line_total is None:
                line_total = (it.quantity or 0) * (it.estimated_unit_price or 0)
            total += Decimal(str(line_total or 0))
        pr.estimated_total = total
        pr.save(update_fields=["estimated_total", "updated_at"])


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------

class PurchaseQuotationViewSet(viewsets.ModelViewSet):
    queryset = PurchaseQuotation.objects.all()
    serializer_class = PurchaseQuotationSerializer
    permission_classes = [CanViewProcurement]
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
        pr = serializer.validated_data.get("purchase_request")
        if pr is not None and pr.status != "approved":
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"purchase_request": "Quotations can only be added to approved requests."})
        if not is_manager_or_admin(self.request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Forbidden")
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
    permission_classes = [CanViewProcurement]
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

    def update(self, request, *args, **kwargs):
        po = self.get_object()
        if po.status not in ("draft", "pending_approval", "rejected"):
            return Response({"detail": "This purchase order can no longer be edited."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

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
    permission_classes = [CanViewProcurement]
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
    permission_classes = [CanViewProcurement]
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
        with transaction.atomic():
            if po is not None:
                locked_po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
                if locked_po.status in ("closed", "cancelled"):
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError(
                        {"purchase_order": "This purchase order can no longer accept "
                                           "receipts."})
                if locked_po.status not in ("approved", "sent_to_vendor", "partially_received"):
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError(
                        {"purchase_order": "Receipts can only be recorded against approved or issued orders."})
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
    permission_classes = [CanViewProcurement]
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
            if gr.purchase_order.status not in ("approved", "sent_to_vendor", "partially_received"):
                from rest_framework.exceptions import ValidationError
                raise ValidationError(
                    {"goods_receipt": "Receipts can only be recorded against approved or issued orders."})
            line = PurchaseOrderItem.objects.select_for_update().get(
                pk=serializer.validated_data["purchase_order_item"].pk)
            received = serializer.validated_data.get(
                "quantity_received", 0) or 0
            booked = (line.received_qty or 0) + (line.rejected_qty or 0) + (line.damaged_qty or 0)
            remaining = max(0, (line.quantity or 0) - booked)
            if received > remaining:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    "quantity_received": (
                        f"Only {remaining} unit(s) remain to be received on this "
                        "purchase order line.")})
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
    permission_classes = [CanViewProcurement]
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
    permission_classes = [CanViewProcurement]
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
        # Enforce shared upload policy (extension/size/executable blocking).
        try:
            from tickets.serializers import validate_attachment_file
            validate_attachment_file(upload)
        except Exception as exc:
            from rest_framework.exceptions import ValidationError
            detail = getattr(exc, "detail", None)
            if detail is None:
                detail = str(exc)
            raise ValidationError({"file": detail})
        upload.seek(0)
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
            file=upload,
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
@permission_classes([CanViewProcurement])
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


# ---------------------------------------------------------------------------
# P3: Supplier invoicing, matching, returns, credit notes, financial control
# ---------------------------------------------------------------------------

def _stale_response():
    return Response({"detail": "The record was modified by another user. Refresh and retry."},
                    status=status.HTTP_409_CONFLICT)


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [CanViewProcurement]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = SupplierInvoice.objects.select_related(
            "vendor", "purchase_order", "created_by").prefetch_related("lines", "match_results")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(created_by=user)
        r = self.request
        if _param(r, "status"): qs = qs.filter(status=_param(r, "status"))
        if _param(r, "payment_status"): qs = qs.filter(payment_status=_param(r, "payment_status"))
        if _as_int(_param(r, "vendor")): qs = qs.filter(vendor_id=_as_int(_param(r, "vendor")))
        if _as_int(_param(r, "purchase_order")): qs = qs.filter(purchase_order_id=_as_int(_param(r, "purchase_order")))
        if _param(r, "currency"): qs = qs.filter(currency__iexact=_param(r, "currency"))
        if _param(r, "created_by"): qs = qs.filter(created_by_id=_as_int(_param(r, "created_by")))
        if _param(r, "payment_hold") is not None:
            b = _as_bool(_param(r, "payment_hold"))
            if b is not None: qs = qs.filter(payment_hold=b)
        qs = _apply_date_range(qs, r, "invoice_date", "invoice_date_from", "invoice_date_to")
        qs = _apply_date_range(qs, r, "due_date", "due_date_from", "due_date_to")
        if _as_bool(_param(r, "overdue")):
            qs = qs.filter(due_date__lt=timezone.now().date()).exclude(payment_status__in=["paid", "cancelled"])
        match_status = _param(r, "match_status")
        if match_status:
            latest = InvoiceMatchResult.objects.filter(invoice_id=F("invoice_id")).order_by("-match_version")
            # approximate: filter invoices whose latest match overall_status matches
            qs = qs.filter(match_results__overall_status=match_status).distinct()
        qs = _apply_search(qs, r, ["invoice_number", "normalized_invoice_number", "vendor__name", "purchase_order__po_number"])
        return _apply_ordering(qs, r, {"created_at", "invoice_date", "due_date", "grand_total", "status", "payment_status", "updated_at"}, ["-created_at"])

    def get_serializer_class(self):
        if self.action == "list": return SupplierInvoiceListSerializer
        if self.action == "create": return SupplierInvoiceCreateSerializer
        if self.action in ("update", "partial_update"): return SupplierInvoiceUpdateSerializer
        return SupplierInvoiceDetailSerializer

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        invoice_services.recalculate_invoice_totals(obj)
        matching_services.record_financial_event(invoice=obj, actor=self.request.user, event_type="invoice_created", new_status=obj.status)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        instance = getattr(serializer, "instance", None)
        if instance is None:
            # fallback: latest created by user
            instance = SupplierInvoice.objects.filter(created_by=request.user).order_by("-id").first()
        headers = self.get_success_headers(serializer.data)
        return Response(SupplierInvoiceDetailSerializer(instance, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        obj = self.get_object()
        if obj.status not in ("draft",):
            raise PermissionDenied("Only Draft invoices can be edited.")
        serializer.save()
        invoice_services.recalculate_invoice_totals(obj)

    def destroy(self, request, *args, **kwargs):
        return Response({"detail": "Supplier invoices cannot be hard-deleted."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def _lock(self, pk):
        return SupplierInvoice.objects.select_for_update().get(pk=pk)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        ser = SupplierInvoiceSubmitSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status != "draft":
                return Response({"detail": "Only Draft invoices can be submitted."}, status=status.HTTP_409_CONFLICT)
            invoice_services.recalculate_invoice_totals(inv)
            errors = invoice_services.validate_invoice_for_submit(inv, actor=request.user)
            if errors:
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)
            prev = inv.status
            inv.status = "submitted"
            inv.submitted_by = request.user
            inv.submitted_at = timezone.now()
            inv.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_submitted", previous_status=prev, new_status=inv.status)
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        ser = SupplierInvoiceMatchSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status in ("cancelled", "closed", "paid", "rejected"):
                return Response({"detail": "Invoice cannot be matched in its current state."}, status=status.HTTP_409_CONFLICT)
            invoice_services.recalculate_invoice_totals(inv)
            prev = inv.status
            result = matching_services.run_three_way_match(inv, actor=request.user)
            inv.refresh_from_db()
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_matched", previous_status=prev, new_status=inv.status, detail={"match_version": result.match_version, "overall_status": result.overall_status})
        return Response({"match": InvoiceMatchResultSerializer(result).data, "invoice": SupplierInvoiceDetailSerializer(inv).data})

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceApproveSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status not in ("matched", "exception"):
                return Response({"detail": "Invoice must be matched or have accepted exceptions before approval."}, status=status.HTTP_409_CONFLICT)
            if inv.created_by_id == request.user.id:
                return Response({"detail": "Creator cannot approve their own invoice."}, status=status.HTTP_403_FORBIDDEN)
            readiness = matching_services.compute_payment_readiness(inv)
            # allow approval when exceptions accepted? require no open blocking exceptions
            open_blocking = InvoiceException.objects.filter(invoice=inv, status="open").exists()
            if open_blocking:
                return Response({"detail": "Unresolved exceptions block approval.", "readiness": readiness}, status=status.HTTP_409_CONFLICT)
            if invoice_services.requires_system_admin_approval(inv) and not p3_is_system_admin(request.user):
                return Response({"detail": "System Admin approval is required for this invoice."}, status=status.HTTP_403_FORBIDDEN)
            prev = inv.status
            inv.status = "approved"
            inv.approved_by = request.user
            inv.approved_at = timezone.now()
            inv.reviewed_by = request.user
            inv.reviewed_at = timezone.now()
            inv.save(update_fields=["status", "approved_by", "approved_at", "reviewed_by", "reviewed_at", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_approved", previous_status=prev, new_status=inv.status)
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject_invoice(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceRejectSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status in ("paid", "closed", "cancelled"):
                return Response({"detail": "Invoice cannot be rejected in its current state."}, status=status.HTTP_409_CONFLICT)
            prev = inv.status
            inv.status = "rejected"
            inv.payment_status = "cancelled"
            inv.save(update_fields=["status", "payment_status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_rejected", previous_status=prev, new_status=inv.status, detail={"reason": ser.validated_data["reason"]})
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="return-for-correction")
    def return_for_correction(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceReturnSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status in ("paid", "closed", "cancelled"):
                return Response({"detail": "Invoice cannot be returned in its current state."}, status=status.HTTP_409_CONFLICT)
            prev = inv.status
            inv.status = "draft"
            inv.payment_status = "not_ready"
            inv.save(update_fields=["status", "payment_status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_returned", previous_status=prev, new_status=inv.status, detail={"reason": ser.validated_data["reason"]})
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="place-hold")
    def place_hold(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceHoldSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            inv.payment_hold = True
            inv.payment_hold_reason = ser.validated_data["reason"]
            inv.payment_status = "on_hold"
            inv.save(update_fields=["payment_hold", "payment_hold_reason", "payment_status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="payment_hold_added", detail={"reason": ser.validated_data["reason"]})
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="release-hold")
    def release_hold(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            inv.payment_hold = False
            inv.payment_hold_reason = ""
            if inv.payment_status == "on_hold":
                inv.payment_status = "not_ready" if inv.status != "payment_ready" else "ready"
            inv.save(update_fields=["payment_hold", "payment_hold_reason", "payment_status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="payment_hold_released")
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="mark-payment-ready")
    def mark_payment_ready(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoicePaymentReadySerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            readiness = matching_services.compute_payment_readiness(inv)
            if not readiness["ready"]:
                return Response({"detail": "Invoice is not ready for payment.", "readiness": readiness}, status=status.HTTP_409_CONFLICT)
            if inv.status != "approved":
                # require approved state per spec flow
                return Response({"detail": "Invoice must be approved before marking payment ready."}, status=status.HTTP_409_CONFLICT)
            prev = inv.status
            inv.status = "payment_ready"
            inv.payment_status = "ready"
            inv.payment_ready_at = timezone.now()
            inv.save(update_fields=["status", "payment_status", "payment_ready_at", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="payment_ready", previous_status=prev, new_status=inv.status)
        return Response({"invoice": SupplierInvoiceDetailSerializer(inv).data, "readiness": readiness})

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceMarkPaidSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status != "payment_ready" or inv.payment_status != "ready":
                return Response({"detail": "Invoice must be payment-ready before recording payment."}, status=status.HTTP_409_CONFLICT)
            prev = inv.status
            inv.status = "paid"
            inv.payment_status = "paid"
            inv.external_accounting_reference = ser.validated_data["payment_reference"][:120]
            inv.save(update_fields=["status", "payment_status", "external_accounting_reference", "updated_at"])
            matching_services.record_financial_event(
                invoice=inv, actor=request.user, event_type="payment_recorded",
                previous_status=prev, new_status=inv.status,
                detail={"payment_reference": ser.validated_data["payment_reference"], "payment_date": str(ser.validated_data["payment_date"])}
            )
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_invoice(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceCancelSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status in ("paid", "closed"):
                return Response({"detail": "Paid or closed invoices cannot be cancelled."}, status=status.HTTP_409_CONFLICT)
            prev = inv.status
            inv.status = "cancelled"
            inv.payment_status = "cancelled"
            inv.save(update_fields=["status", "payment_status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_cancelled", previous_status=prev, new_status=inv.status, detail={"reason": ser.validated_data["reason"]})
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["post"], url_path="close")
    def close_invoice(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = SupplierInvoiceCloseSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = self._lock(pk)
            if _check_version(inv, ser.validated_data): return _stale_response()
            if inv.status != "paid":
                return Response({"detail": "Only paid invoices can be closed."}, status=status.HTTP_409_CONFLICT)
            prev = inv.status
            inv.status = "closed"
            inv.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="invoice_closed", previous_status=prev, new_status=inv.status)
        return Response(SupplierInvoiceDetailSerializer(inv).data)

    @action(detail=True, methods=["get"], url_path="readiness")
    def readiness(self, request, pk=None):
        inv = self.get_object()
        data = matching_services.compute_payment_readiness(inv)
        data["invoice_status"] = inv.status
        data["payment_status"] = inv.payment_status
        return Response(data)

    @action(detail=True, methods=["get"], url_path="match-history")
    def match_history(self, request, pk=None):
        inv = self.get_object()
        qs = inv.match_results.all().order_by("-match_version", "-created_at")
        return Response(InvoiceMatchResultSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="exceptions")
    def invoice_exceptions(self, request, pk=None):
        inv = self.get_object()
        qs = inv.exceptions.all().order_by("-created_at")
        return Response(InvoiceExceptionSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="history")
    def financial_history(self, request, pk=None):
        inv = self.get_object()
        qs = inv.financial_history.all().order_by("created_at")
        return Response(ProcurementFinancialHistorySerializer(qs, many=True).data)



class SupplierInvoiceLineViewSet(viewsets.ModelViewSet):
    permission_classes = [CanViewProcurement]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        qs = SupplierInvoiceLine.objects.select_related("invoice", "purchase_order_item", "goods_receipt_item")
        inv = _as_int(_param(self.request, "invoice"))
        if inv: qs = qs.filter(invoice_id=inv)
        return qs.order_by("id")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"): return SupplierInvoiceLineCreateSerializer
        return SupplierInvoiceLineSerializer

    def perform_create(self, serializer):
        inv = serializer.validated_data["invoice"]
        if inv.status != "draft":
            raise PermissionDenied("Invoice lines can only be added while invoice is Draft.")
        line = serializer.save()
        invoice_services.recalculate_invoice_totals(inv)

    def perform_update(self, serializer):
        inv = self.get_object().invoice
        if inv.status != "draft":
            raise PermissionDenied("Invoice lines can only be edited while invoice is Draft.")
        serializer.save()
        invoice_services.recalculate_invoice_totals(inv)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.invoice.status != "draft":
            return Response({"detail": "Invoice lines can only be deleted while invoice is Draft."}, status=status.HTTP_409_CONFLICT)
        inv = obj.invoice
        resp = super().destroy(request, *args, **kwargs)
        invoice_services.recalculate_invoice_totals(inv)
        return resp


class InvoiceMatchResultViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanViewProcurement]
    serializer_class = InvoiceMatchResultSerializer
    pagination_class = ProcurementPagination

    def get_queryset(self):
        qs = InvoiceMatchResult.objects.select_related("invoice", "matched_by")
        inv = _as_int(_param(self.request, "invoice"))
        if inv: qs = qs.filter(invoice_id=inv)
        return qs.order_by("-match_version", "-created_at")


class InvoiceExceptionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanViewProcurement]
    serializer_class = InvoiceExceptionSerializer
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = InvoiceException.objects.select_related("invoice", "invoice_line", "assigned_to")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(invoice__created_by=user)
        r = self.request
        if _param(r, "status"): qs = qs.filter(status=_param(r, "status"))
        if _param(r, "severity"): qs = qs.filter(severity=_param(r, "severity"))
        if _param(r, "exception_type"): qs = qs.filter(exception_type=_param(r, "exception_type"))
        if _as_int(_param(r, "invoice")): qs = qs.filter(invoice_id=_as_int(_param(r, "invoice")))
        qs = _apply_search(qs, r, ["invoice__invoice_number", "reason", "exception_type"])
        return _apply_ordering(qs, r, {"created_at", "detected_at", "severity", "status"}, ["-created_at"])

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = InvoiceExceptionActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            exc = InvoiceException.objects.select_for_update().select_related("invoice").get(pk=pk)
            if exc.status != "open":
                return Response({"detail": "Only open exceptions can be acknowledged."}, status=status.HTTP_409_CONFLICT)
            exc.status = "acknowledged"
            exc.acknowledged_at = timezone.now()
            exc.acknowledged_by = request.user
            exc.save(update_fields=["status", "acknowledged_at", "acknowledged_by", "updated_at"])
        return Response(InvoiceExceptionSerializer(exc).data)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept_exception(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = InvoiceExceptionAcceptSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            exc = InvoiceException.objects.select_for_update().select_related("invoice").get(pk=pk)
            inv = exc.invoice
            if inv.created_by_id == request.user.id:
                return Response({"detail": "Creator cannot accept exceptions on their own invoice."}, status=status.HTTP_403_FORBIDDEN)
            if exc.status in ("resolved", "rejected", "superseded"):
                return Response({"detail": "Exception cannot be accepted in its current state."}, status=status.HTTP_409_CONFLICT)
            if exc.severity in ("high", "critical") and not p3_is_system_admin(request.user):
                return Response({"detail": "High/critical exceptions require System Admin acceptance."}, status=status.HTTP_403_FORBIDDEN)
            exc.status = "accepted"
            exc.resolution = "authorized_variance"
            exc.resolution_note = ser.validated_data.get("reason", "")
            exc.resolved_at = timezone.now()
            exc.resolved_by = request.user
            exc.save(update_fields=["status", "resolution", "resolution_note", "resolved_at", "resolved_by", "updated_at"])
            # reflect on line/invoice match status if applicable
            if exc.invoice_line_id:
                line = exc.invoice_line
                line.match_status = "exception_accepted"
                line.save(update_fields=["match_status", "updated_at"])
            inv.refresh_from_db()
            if inv.status == "exception" and not inv.exceptions.filter(status="open").exists():
                inv.status = "matched"
                inv.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(invoice=inv, actor=request.user, event_type="match_exception_accepted", detail={"exception_id": exc.pk, "reason": ser.validated_data.get("reason", "")})
        return Response(InvoiceExceptionSerializer(exc).data)

    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve_exception(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = InvoiceExceptionResolveSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            exc = InvoiceException.objects.select_for_update().select_related("invoice").get(pk=pk)
            if exc.status in ("resolved", "rejected", "superseded"):
                return Response({"detail": "Exception already closed."}, status=status.HTTP_409_CONFLICT)
            exc.status = "resolved"
            exc.resolution = ser.validated_data.get("resolution") or "other"
            exc.resolution_note = ser.validated_data.get("reason", "")
            exc.resolved_at = timezone.now()
            exc.resolved_by = request.user
            exc.save(update_fields=["status", "resolution", "resolution_note", "resolved_at", "resolved_by", "updated_at"])
        return Response(InvoiceExceptionSerializer(exc).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject_exception(self, request, pk=None):
        if not is_manager_or_admin(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = InvoiceExceptionActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            exc = InvoiceException.objects.select_for_update().get(pk=pk)
            if exc.status in ("resolved", "rejected", "superseded"):
                return Response({"detail": "Exception already closed."}, status=status.HTTP_409_CONFLICT)
            exc.status = "rejected"
            exc.resolution = "rejected"
            exc.resolution_note = ser.validated_data.get("reason", "")
            exc.resolved_at = timezone.now()
            exc.resolved_by = request.user
            exc.save(update_fields=["status", "resolution", "resolution_note", "resolved_at", "resolved_by", "updated_at"])
        return Response(InvoiceExceptionSerializer(exc).data)



class VendorReturnViewSet(viewsets.ModelViewSet):
    permission_classes = [CanViewProcurement]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = VendorReturn.objects.select_related(
            "vendor", "purchase_order", "goods_receipt", "supplier_invoice", "created_by"
        ).prefetch_related("lines")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(created_by=user)
        r = self.request
        if _param(r, "status"): qs = qs.filter(status=_param(r, "status"))
        if _as_int(_param(r, "vendor")): qs = qs.filter(vendor_id=_as_int(_param(r, "vendor")))
        if _as_int(_param(r, "purchase_order")): qs = qs.filter(purchase_order_id=_as_int(_param(r, "purchase_order")))
        if _as_int(_param(r, "goods_receipt")): qs = qs.filter(goods_receipt_id=_as_int(_param(r, "goods_receipt")))
        if _as_int(_param(r, "supplier_invoice")): qs = qs.filter(supplier_invoice_id=_as_int(_param(r, "supplier_invoice")))
        if _param(r, "reason"): qs = qs.filter(reason=_param(r, "reason"))
        if _param(r, "return_method"): qs = qs.filter(return_method=_param(r, "return_method"))
        rep = _as_bool(_param(r, "replacement_expected"))
        if rep is not None: qs = qs.filter(replacement_expected=rep)
        qs = _apply_date_range(qs, r, "return_date", "return_date_from", "return_date_to")
        qs = _apply_search(qs, r, ["return_number", "vendor__name", "purchase_order__po_number", "goods_receipt__gr_number", "supplier_invoice__invoice_number", "authorization_reference", "shipping_reference"])
        return _apply_ordering(qs, r, {"created_at", "return_date", "status", "updated_at"}, ["-created_at"])

    def get_serializer_class(self):
        if self.action == "list": return VendorReturnListSerializer
        if self.action == "create": return VendorReturnCreateSerializer
        return VendorReturnDetailSerializer

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        matching_services.record_financial_event(vendor_return=obj, actor=self.request.user, event_type="return_created", new_status=obj.status)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        instance = serializer.instance
        headers = self.get_success_headers(serializer.data)
        return Response(VendorReturnDetailSerializer(instance, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.status != "draft":
            return Response({"detail": "Only draft returns can be edited."}, status=status.HTTP_409_CONFLICT)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.status != "draft":
            return Response({"detail": "Returns cannot be deleted after submission."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
        return Response({"detail": "Hard delete is not allowed."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def _lock(self, pk): return VendorReturn.objects.select_for_update().get(pk=pk)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        ser = VendorReturnActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status != "draft": return Response({"detail": "Only draft returns can be submitted."}, status=status.HTTP_409_CONFLICT)
            if not vr.lines.exists(): return Response({"detail": "At least one return line is required."}, status=status.HTTP_400_BAD_REQUEST)
            prev = vr.status
            vr.status = "pending_approval"
            vr.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="return_created", previous_status=prev, new_status=vr.status, detail={"action":"submitted"})
        return Response(VendorReturnDetailSerializer(vr).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorReturnActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status != "pending_approval": return Response({"detail": "Return is not pending approval."}, status=status.HTTP_409_CONFLICT)
            if vr.created_by_id == request.user.id and not p3_is_system_admin(request.user):
                return Response({"detail": "Creator cannot approve their own return."}, status=status.HTTP_403_FORBIDDEN)
            prev = vr.status
            vr.status = "approved"
            vr.approved_by = request.user
            vr.approved_at = timezone.now()
            if ser.validated_data.get("authorization_reference"):
                vr.authorization_reference = ser.validated_data["authorization_reference"]
            vr.save(update_fields=["status", "approved_by", "approved_at", "authorization_reference", "updated_at"])
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="return_approved", previous_status=prev, new_status=vr.status)
        return Response(VendorReturnDetailSerializer(vr).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorReturnActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status not in ("pending_approval", "approved"):
                return Response({"detail": "Return cannot be rejected in current state."}, status=status.HTTP_409_CONFLICT)
            prev = vr.status
            vr.status = "rejected"
            vr.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="return_approved", previous_status=prev, new_status=vr.status, detail={"rejected": True, "reason": ser.validated_data.get("reason", "")})
        return Response(VendorReturnDetailSerializer(vr).data)

    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorReturnShipSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status != "approved": return Response({"detail": "Only approved returns can be shipped."}, status=status.HTTP_409_CONFLICT)
            prev = vr.status
            vr.status = "shipped"
            vr.shipped_by = request.user
            vr.shipped_at = timezone.now()
            if ser.validated_data.get("shipping_reference"):
                vr.shipping_reference = ser.validated_data["shipping_reference"]
            vr.save(update_fields=["status", "shipped_by", "shipped_at", "shipping_reference", "updated_at"])
            # reverse stock / cancel pending asset receipt items as appropriate (backend-controlled)
            for line in vr.lines.select_related("purchase_order_item__stock_item", "goods_receipt_item").all():
                return_services.reverse_stock_for_return_line(line, request.user)
                return_services.cancel_pending_asset_receipt_items_for_return_line(line)
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="return_shipped", previous_status=prev, new_status=vr.status)
        return Response(VendorReturnDetailSerializer(vr).data)

    @action(detail=True, methods=["post"], url_path="record-replacement")
    def record_replacement(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorReturnReplacementSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status not in ("shipped", "partially_resolved"):
                return Response({"detail": "Return must be shipped before recording replacement."}, status=status.HTTP_409_CONFLICT)
            prev = vr.status
            vr.status = "partially_resolved"
            vr.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="replacement_received", previous_status=prev, new_status=vr.status)
        return Response(VendorReturnDetailSerializer(vr).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorReturnCompleteSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status not in ("shipped", "partially_resolved", "approved"):
                return Response({"detail": "Return cannot be completed in current state."}, status=status.HTTP_409_CONFLICT)
            prev = vr.status
            vr.status = "resolved"
            vr.completed_by = request.user
            vr.completed_at = timezone.now()
            vr.save(update_fields=["status", "completed_by", "completed_at", "updated_at"])
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="return_completed", previous_status=prev, new_status=vr.status)
        return Response(VendorReturnDetailSerializer(vr).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorReturnActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            vr = self._lock(pk)
            if _check_version(vr, ser.validated_data): return _stale_response()
            if vr.status in ("resolved", "shipped"):
                return Response({"detail": "Shipped/resolved returns cannot be cancelled."}, status=status.HTTP_409_CONFLICT)
            prev = vr.status
            vr.status = "cancelled"
            vr.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(vendor_return=vr, actor=request.user, event_type="return_completed", previous_status=prev, new_status=vr.status, detail={"cancelled": True, "reason": ser.validated_data.get("reason", "")})
        return Response(VendorReturnDetailSerializer(vr).data)


class VendorReturnLineViewSet(viewsets.ModelViewSet):
    permission_classes = [CanViewProcurement]
    serializer_class = VendorReturnLineSerializer
    pagination_class = ProcurementPagination

    def get_queryset(self):
        qs = VendorReturnLine.objects.select_related("vendor_return", "goods_receipt_item", "purchase_order_item", "asset")
        vr = _as_int(_param(self.request, "vendor_return"))
        if vr: qs = qs.filter(vendor_return_id=vr)
        return qs.order_by("id")

    def perform_create(self, serializer):
        vr = serializer.validated_data["vendor_return"]
        if vr.status != "draft":
            raise PermissionDenied("Return lines can only be added while return is Draft.")
        line = serializer.save()
        # basic eligibility check
        eligible = return_services.eligible_return_quantity(line.goods_receipt_item)
        if int(line.quantity) > eligible and not p3_is_system_admin(self.request.user):
            # rollback by raising - in perform_create transaction managed by viewset? DRF saves outside explicit tx in default flow, so delete
            line.delete()
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"quantity": "Return quantity exceeds eligible quantity."})


class VendorCreditNoteViewSet(viewsets.ModelViewSet):
    permission_classes = [CanViewProcurement]
    pagination_class = ProcurementPagination

    def get_queryset(self):
        user = self.request.user
        qs = VendorCreditNote.objects.select_related(
            "vendor", "supplier_invoice", "vendor_return", "created_by"
        ).prefetch_related("lines")
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(created_by=user)
        r = self.request
        if _param(r, "status"): qs = qs.filter(status=_param(r, "status"))
        if _as_int(_param(r, "vendor")): qs = qs.filter(vendor_id=_as_int(_param(r, "vendor")))
        if _as_int(_param(r, "supplier_invoice")): qs = qs.filter(supplier_invoice_id=_as_int(_param(r, "supplier_invoice")))
        if _as_int(_param(r, "vendor_return")): qs = qs.filter(vendor_return_id=_as_int(_param(r, "vendor_return")))
        if _param(r, "currency"): qs = qs.filter(currency__iexact=_param(r, "currency"))
        qs = _apply_date_range(qs, r, "credit_date", "credit_date_from", "credit_date_to")
        qs = _apply_search(qs, r, ["credit_note_number", "vendor__name", "supplier_invoice__invoice_number", "vendor_return__return_number", "external_reference"])
        return _apply_ordering(qs, r, {"created_at", "credit_date", "total", "status", "updated_at"}, ["-created_at"])

    def get_serializer_class(self):
        if self.action == "list": return VendorCreditNoteListSerializer
        if self.action == "create": return VendorCreditNoteCreateSerializer
        return VendorCreditNoteDetailSerializer

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        matching_services.record_financial_event(credit_note=obj, invoice=obj.supplier_invoice, actor=self.request.user, event_type="credit_created", new_status=obj.status)

    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.status != "draft":
            return Response({"detail": "Only draft credit notes can be edited."}, status=status.HTTP_409_CONFLICT)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response({"detail": "Credit notes cannot be hard-deleted after submission."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def _lock(self, pk): return VendorCreditNote.objects.select_for_update().get(pk=pk)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        ser = VendorCreditNoteActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            cn = self._lock(pk)
            if _check_version(cn, ser.validated_data): return _stale_response()
            if cn.status != "draft": return Response({"detail": "Only draft credit notes can be submitted."}, status=status.HTTP_409_CONFLICT)
            inv = cn.supplier_invoice
            if cn.vendor_id != inv.vendor_id: return Response({"vendor": "Vendor must match invoice."}, status=status.HTTP_400_BAD_REQUEST)
            if cn.currency != inv.currency: return Response({"currency": "Currency must match invoice."}, status=status.HTTP_400_BAD_REQUEST)
            if (cn.total or 0) < 0: return Response({"total": "Total cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
            prev = cn.status
            cn.status = "submitted"
            cn.save(update_fields=["status", "updated_at"])
            matching_services.record_financial_event(credit_note=cn, invoice=inv, actor=request.user, event_type="credit_created", previous_status=prev, new_status=cn.status, detail={"submitted": True})
        return Response(VendorCreditNoteDetailSerializer(cn).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorCreditNoteActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            cn = self._lock(pk)
            if _check_version(cn, ser.validated_data): return _stale_response()
            if cn.status != "submitted": return Response({"detail": "Only submitted credit notes can be approved."}, status=status.HTTP_409_CONFLICT)
            if cn.created_by_id == request.user.id and not p3_is_system_admin(request.user):
                return Response({"detail": "Creator cannot approve their own credit note."}, status=status.HTTP_403_FORBIDDEN)
            prev = cn.status
            cn.status = "approved"
            cn.approved_by = request.user
            cn.approved_at = timezone.now()
            cn.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
            matching_services.record_financial_event(credit_note=cn, invoice=cn.supplier_invoice, actor=request.user, event_type="credit_approved", previous_status=prev, new_status=cn.status)
        return Response(VendorCreditNoteDetailSerializer(cn).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorCreditNoteActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            cn = self._lock(pk)
            if _check_version(cn, ser.validated_data): return _stale_response()
            if cn.status in ("applied", "cancelled"): return Response({"detail": "Credit note cannot be rejected."}, status=status.HTTP_409_CONFLICT)
            prev = cn.status
            cn.status = "rejected"
            cn.save(update_fields=["status", "updated_at"])
        return Response(VendorCreditNoteDetailSerializer(cn).data)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorCreditNoteApplySerializer(data=request.data); ser.is_valid(raise_exception=True)
        from decimal import Decimal
        with transaction.atomic():
            cn = self._lock(pk)
            if _check_version(cn, ser.validated_data): return _stale_response()
            if cn.status != "approved": return Response({"detail": "Only approved credit notes can be applied."}, status=status.HTTP_409_CONFLICT)
            inv = SupplierInvoice.objects.select_for_update().get(pk=cn.supplier_invoice_id)
            # over-credit check: total applied credits cannot exceed invoice grand total
            applied = VendorCreditNote.objects.filter(
                supplier_invoice=inv, status="applied"
            ).exclude(pk=cn.pk).aggregate(s=Sum("applied_amount")).get("s") or Decimal("0")
            remaining = (inv.grand_total or Decimal("0")) - Decimal(str(applied))
            if (cn.total or Decimal("0")) > remaining:
                return Response({"detail": "Credit amount exceeds remaining invoice balance."}, status=status.HTTP_400_BAD_REQUEST)
            prev = cn.status
            cn.status = "applied"
            cn.applied_amount = cn.total
            cn.applied_at = timezone.now()
            cn.save(update_fields=["status", "applied_amount", "applied_at", "updated_at"])
            matching_services.record_financial_event(credit_note=cn, invoice=inv, actor=request.user, event_type="credit_applied", previous_status=prev, new_status=cn.status, detail={"applied_amount": str(cn.applied_amount)})
        return Response(VendorCreditNoteDetailSerializer(cn).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        if not is_manager_or_admin(request.user): return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ser = VendorCreditNoteActionSerializer(data=request.data); ser.is_valid(raise_exception=True)
        with transaction.atomic():
            cn = self._lock(pk)
            if _check_version(cn, ser.validated_data): return _stale_response()
            if cn.status == "applied": return Response({"detail": "Applied credit notes cannot be cancelled."}, status=status.HTTP_409_CONFLICT)
            prev = cn.status
            cn.status = "cancelled"
            cn.save(update_fields=["status", "updated_at"])
        return Response(VendorCreditNoteDetailSerializer(cn).data)


class VendorCreditNoteLineViewSet(viewsets.ModelViewSet):
    permission_classes = [CanViewProcurement]
    serializer_class = VendorCreditNoteLineSerializer
    pagination_class = ProcurementPagination

    def get_queryset(self):
        qs = VendorCreditNoteLine.objects.select_related("credit_note", "supplier_invoice_line")
        cn = _as_int(_param(self.request, "credit_note"))
        if cn: qs = qs.filter(credit_note_id=cn)
        return qs.order_by("id")


class ProcurementFinancialHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanViewProcurement]
    serializer_class = ProcurementFinancialHistorySerializer
    pagination_class = ProcurementPagination

    def get_queryset(self):
        if not is_manager_or_admin(self.request.user):
            return ProcurementFinancialHistory.objects.none()
        qs = ProcurementFinancialHistory.objects.select_related("actor", "invoice", "vendor_return", "credit_note")
        r = self.request
        if _as_int(_param(r, "invoice")): qs = qs.filter(invoice_id=_as_int(_param(r, "invoice")))
        if _as_int(_param(r, "vendor_return")): qs = qs.filter(vendor_return_id=_as_int(_param(r, "vendor_return")))
        if _as_int(_param(r, "credit_note")): qs = qs.filter(credit_note_id=_as_int(_param(r, "credit_note")))
        if _param(r, "event_type"): qs = qs.filter(event_type=_param(r, "event_type"))
        if _as_int(_param(r, "actor")): qs = qs.filter(actor_id=_as_int(_param(r, "actor")))
        qs = _apply_date_range(qs, r, "created_at", "date_from", "date_to")
        return _apply_ordering(qs, r, {"created_at"}, ["created_at"])


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def procurement_financial_dashboard(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    today = timezone.now().date()
    invoices = SupplierInvoice.objects.all()
    cards = {
        "draft": invoices.filter(status="draft").count(),
        "submitted": invoices.filter(status="submitted").count(),
        "awaiting_match": invoices.filter(status__in=["submitted", "matching"]).count(),
        "matched": invoices.filter(status__in=["matched", "approved", "payment_ready"]).count(),
        "match_exceptions": invoices.filter(status="exception").count(),
        "approval_pending": invoices.filter(status__in=["matched", "exception"]).count(),
        "payment_holds": invoices.filter(payment_hold=True).count(),
        "payment_ready": invoices.filter(status="payment_ready", payment_status="ready").count(),
        "paid_in_period": invoices.filter(status__in=["paid", "closed"], payment_status="paid", updated_at__date__gte=today.replace(day=1)).count(),
        "overdue": invoices.filter(due_date__lt=today).exclude(status__in=["paid", "closed", "cancelled"]).count(),
        "open_returns": VendorReturn.objects.filter(status__in=["draft", "pending_approval", "approved", "shipped", "partially_resolved"]).count(),
        "pending_credits": VendorCreditNote.objects.filter(status__in=["draft", "submitted", "approved"]).count(),
        "unresolved_high_critical": InvoiceException.objects.filter(status__in=["open", "acknowledged"], severity__in=["high", "critical"]).count(),
        "match_rate": 0,
        "exception_rate": 0,
        "average_match_time": None,
    }
    totals = list(invoices.values("currency").annotate(
        invoiced=Sum("grand_total"),
        approved=Sum("grand_total", filter=Q(status__in=["approved", "payment_ready", "paid", "closed"])),
        payment_ready=Sum("grand_total", filter=Q(status="payment_ready")),
        paid=Sum("grand_total", filter=Q(status__in=["paid", "closed"])),
        exception_value=Sum("variance_total"),
    ).order_by("currency"))
    credit_totals = {r["currency"]: r for r in VendorCreditNote.objects.exclude(status__in=["rejected", "cancelled"]).values("currency").annotate(credit_note_total=Sum("total"))}
    for row in totals:
        cur = row.get("currency")
        row["credit_note_total"] = (credit_totals.get(cur, {}) or {}).get("credit_note_total") or 0
        row["outstanding"] = (row.get("invoiced") or 0) - (row.get("paid") or 0) - (row.get("credit_note_total") or 0)
    recent = list(invoices.select_related("vendor").order_by("-created_at")[:10].values("id", "invoice_number", "vendor__name", "status", "grand_total", "currency"))
    for r in recent: r["vendor_name"] = r.pop("vendor__name", None)
    crit = list(InvoiceException.objects.filter(status__in=["open", "acknowledged"], severity__in=["high", "critical"]).select_related("invoice").order_by("-created_at")[:10].values("id", "invoice_id", "invoice__invoice_number", "exception_type", "severity", "status"))
    for r in crit: r["invoice_number"] = r.pop("invoice__invoice_number", None)
    pay_ready = list(invoices.filter(status="payment_ready").select_related("vendor").order_by("due_date")[:10].values("id", "invoice_number", "vendor__name", "grand_total", "currency"))
    for r in pay_ready: r["vendor_name"] = r.pop("vendor__name", None)
    overdue = list(invoices.filter(due_date__lt=today).exclude(status__in=["paid", "closed", "cancelled"]).select_related("vendor").order_by("due_date")[:10].values("id", "invoice_number", "vendor__name", "due_date", "grand_total", "currency"))
    for r in overdue: r["vendor_name"] = r.pop("vendor__name", None)
    open_returns = list(VendorReturn.objects.filter(status__in=["draft", "pending_approval", "approved", "shipped", "partially_resolved"]).select_related("vendor").order_by("-created_at")[:10].values("id", "return_number", "vendor__name", "status"))
    for r in open_returns: r["vendor_name"] = r.pop("vendor__name", None)
    credits_wait = list(VendorCreditNote.objects.filter(status__in=["draft", "submitted", "approved"]).select_related("vendor").order_by("-created_at")[:10].values("id", "credit_note_number", "vendor__name", "status", "total", "currency"))
    for r in credits_wait: r["vendor_name"] = r.pop("vendor__name", None)
    return Response({
        "cards": cards,
        "totals_by_currency": totals,
        "recent_invoices": recent,
        "critical_exceptions": crit,
        "payment_ready_invoices": pay_ready,
        "overdue_invoices": overdue,
        "open_vendor_returns": open_returns,
        "credits_awaiting_application": credits_wait,
    })



@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_invoice_aging(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    today = timezone.now().date()
    qs = SupplierInvoice.objects.exclude(status__in=["paid", "closed", "cancelled"]).select_related("vendor")
    buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "over_90": []}
    for inv in qs:
        if not inv.due_date or inv.due_date >= today:
            buckets["current"].append(inv)
            continue
        days = (today - inv.due_date).days
        if days <= 30: buckets["1_30"].append(inv)
        elif days <= 60: buckets["31_60"].append(inv)
        elif days <= 90: buckets["61_90"].append(inv)
        else: buckets["over_90"].append(inv)
    def ser(lst):
        return [{"id": i.id, "invoice_number": i.invoice_number, "vendor_name": getattr(i.vendor, 'name', None), "due_date": i.due_date, "grand_total": str(i.grand_total), "currency": i.currency, "status": i.status} for i in lst]
    return Response({k: ser(v) for k, v in buckets.items()})


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_match_rate(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    qs = InvoiceMatchResult.objects.order_by("invoice_id", "-match_version")
    latest_ids = []
    seen = set()
    for r in qs.values("id", "invoice_id"):
        if r["invoice_id"] in seen: continue
        seen.add(r["invoice_id"]); latest_ids.append(r["id"])
    latest = InvoiceMatchResult.objects.filter(id__in=latest_ids)
    total = latest.count() or 0
    def cnt(s): return latest.filter(overall_status=s).count()
    return Response({
        "total": total,
        "exact_match": cnt("matched"),
        "within_tolerance": cnt("matched_within_tolerance"),
        "exception": cnt("exception"),
        "receipt_incomplete": cnt("receipt_incomplete"),
        "over_invoiced": cnt("over_invoiced"),
        "invalid": cnt("invalid"),
        "unmatched": cnt("unmatched"),
    })


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_exceptions(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    qs = InvoiceException.objects.all()
    return Response({
        "total": qs.count(),
        "by_status": list(qs.values("status").annotate(count=Count("id")).order_by("status")),
        "by_severity": list(qs.values("severity").annotate(count=Count("id")).order_by("severity")),
        "by_type": list(qs.values("exception_type").annotate(count=Count("id")).order_by("exception_type")),
    })


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_vendor_returns(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    qs = VendorReturn.objects.all()
    return Response({
        "total": qs.count(),
        "by_status": list(qs.values("status").annotate(count=Count("id")).order_by("status")),
        "by_reason": list(qs.values("reason").annotate(count=Count("id")).order_by("reason")),
        "open": qs.filter(status__in=["draft", "pending_approval", "approved", "shipped", "partially_resolved"]).count(),
    })


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_credits(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    qs = VendorCreditNote.objects.all()
    totals = list(qs.values("currency").annotate(total=Sum("total"), applied=Sum("applied_amount")).order_by("currency"))
    return Response({
        "total": qs.count(),
        "by_status": list(qs.values("status").annotate(count=Count("id")).order_by("status")),
        "totals_by_currency": totals,
    })


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_payment_readiness(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    qs = SupplierInvoice.objects.exclude(status__in=["cancelled", "closed"])
    rows = []
    for inv in qs.select_related("vendor")[:200]:
        r = matching_services.compute_payment_readiness(inv)
        rows.append({
            "id": inv.id, "invoice_number": inv.invoice_number, "vendor_name": getattr(inv.vendor, 'name', None),
            "status": inv.status, "payment_status": inv.payment_status,
            "ready": r["ready"], "blocker_count": len(r.get("blockers", [])),
        })
    return Response({"count": len(rows), "invoices": rows})


@api_view(["GET"])
@permission_classes([CanViewProcurement])
def report_vendor_performance(request):
    if not is_manager_or_admin(request.user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    vendors = {}
    for po in PurchaseOrder.objects.select_related("vendor").all():
        vid = po.vendor_id
        v = vendors.setdefault(vid, {"vendor_id": vid, "vendor_name": getattr(po.vendor, "name", str(vid)), "purchase_orders": 0, "delivered_on_time": 0, "with_eta": 0, "complete": 0, "received_lines": 0, "rejected_qty": 0, "damaged_qty": 0, "total_received_qty": 0, "invoices": 0, "matched_invoices": 0, "price_variance_sum": 0.0, "open_returns": 0})
        v["purchase_orders"] += 1
        if po.expected_delivery_date:
            v["with_eta"] += 1
            # approximate on-time: has completed/received and completed_at or received receipts before eta? simplified
            if po.status in ("received", "closed") and po.completed_at and po.completed_at.date() <= po.expected_delivery_date:
                v["delivered_on_time"] += 1
        if po.status in ("received", "closed"): v["complete"] += 1
    # receipt quantities
    for item in GoodsReceiptItem.objects.select_related("goods_receipt__purchase_order").all():
        vid = item.goods_receipt.purchase_order.vendor_id
        if vid not in vendors: continue
        v = vendors[vid]
        v["total_received_qty"] += int(item.quantity_received or 0)
        v["rejected_qty"] += int(item.quantity_rejected or 0)
        v["damaged_qty"] += int(item.quantity_damaged or 0)
    # invoices/match
    for inv in SupplierInvoice.objects.select_related("vendor").prefetch_related("match_results").all():
        vid = inv.vendor_id
        if vid not in vendors: vendors.setdefault(vid, {"vendor_id": vid, "vendor_name": getattr(inv.vendor, "name", str(vid)), "purchase_orders": 0, "delivered_on_time": 0, "with_eta": 0, "complete": 0, "received_lines": 0, "rejected_qty": 0, "damaged_qty": 0, "total_received_qty": 0, "invoices": 0, "matched_invoices": 0, "price_variance_sum": 0.0, "open_returns": 0})
        v = vendors[vid]
        v["invoices"] += 1
        latest = inv.match_results.order_by("-match_version").first()
        if latest and latest.overall_status in ("matched", "matched_within_tolerance"):
            v["matched_invoices"] += 1
        if latest:
            v["price_variance_sum"] += float(latest.price_variance_total or 0)
    # open returns
    for vr in VendorReturn.objects.filter(status__in=["draft", "pending_approval", "approved", "shipped", "partially_resolved"]):
        if vr.vendor_id in vendors: vendors[vr.vendor_id]["open_returns"] += 1
    rows = []
    for v in vendors.values():
        tr = v["total_received_qty"] or 0
        pos = v["purchase_orders"] or 0
        invs = v["invoices"] or 0
        rows.append({
            "vendor_id": v["vendor_id"], "vendor_name": v["vendor_name"],
            "purchase_orders": pos,
            "on_time_delivery_rate": round((v["delivered_on_time"] / v["with_eta"] * 100), 2) if v["with_eta"] else None,
            "complete_delivery_rate": round((v["complete"] / pos * 100), 2) if pos else None,
            "rejected_quantity_rate": round((v["rejected_qty"] / tr * 100), 2) if tr else None,
            "damaged_quantity_rate": round((v["damaged_qty"] / tr * 100), 2) if tr else None,
            "invoice_match_rate": round((v["matched_invoices"] / invs * 100), 2) if invs else None,
            "average_price_variance": round((v["price_variance_sum"] / invs), 2) if invs else None,
            "open_returns": v["open_returns"],
            "sample_note": "Small sample" if (pos < 3 and invs < 3) else "",
        })
    return Response(rows)
