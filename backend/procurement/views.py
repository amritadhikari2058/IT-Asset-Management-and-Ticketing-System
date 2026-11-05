from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

from accounts.models import User
from common.audit import log_action
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, ProcurementHistory
)
from .serializers import (
    ProcurementSettingSerializer, PurchaseRequestSerializer, PurchaseRequestItemSerializer,
    PurchaseQuotationSerializer, PurchaseOrderSerializer, PurchaseOrderItemSerializer,
    GoodsReceiptSerializer, GoodsReceiptItemSerializer, ProcurementHistorySerializer
)


def is_staff(user):
    return user.is_authenticated and user.role in ("system_admin", "it_manager", "it_support")


def is_manager_or_admin(user):
    return user.is_authenticated and user.role in ("system_admin", "it_manager")


class ProcurementSettingViewSet(viewsets.ModelViewSet):
    queryset = ProcurementSetting.objects.all()
    serializer_class = ProcurementSettingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "current"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]


class PurchaseRequestViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequest.objects.all()
    serializer_class = PurchaseRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseRequest.objects.all()
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(requester=user)
        return qs

    def perform_create(self, serializer):
        pr = serializer.save(requester=self.request.user, department=self.request.user.home_department)
        ProcurementHistory.objects.create(
            purchase_request=pr, actor=self.request.user, action="created", detail="Purchase request created"
        )
        log_action(actor=self.request.user, action="create", instance=pr, reason="purchase request created")

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        pr = self.get_object()
        if pr.requester != request.user and not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status not in ("draft", "returned_for_correction"):
            return Response({"detail": "Cannot submit in current status"}, status=status.HTTP_400_BAD_REQUEST)

        settings = ProcurementSetting.get_settings()
        pr.requires_system_admin_approval = pr.estimated_total >= settings.approval_threshold
        pr.status = "pending_approval"
        pr.save()
        ProcurementHistory.objects.create(purchase_request=pr, actor=request.user, action="submitted", detail="Submitted for approval")
        log_action(actor=request.user, action="update", instance=pr, reason="purchase request submitted")
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        pr = self.get_object()
        role = getattr(request.user, "role", "")
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.requester == request.user:
            return Response({"detail": "Cannot approve own request"}, status=status.HTTP_400_BAD_REQUEST)
        if pr.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=status.HTTP_400_BAD_REQUEST)
        if pr.requires_system_admin_approval and role != "system_admin":
            return Response({"detail": "System Admin approval required"}, status=status.HTTP_403_FORBIDDEN)

        pr.status = "approved"
        pr.approver = request.user
        pr.approval_decision = "approved"
        pr.approval_reason = request.data.get("reason", "")
        pr.approved_at = timezone.now()
        pr.save()
        ProcurementHistory.objects.create(purchase_request=pr, actor=request.user, action="approved", detail=pr.approval_reason or "Approved")
        log_action(actor=request.user, action="approve", instance=pr, reason="purchase request approved")
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        pr = self.get_object()
        role = getattr(request.user, "role", "")
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.requester == request.user:
            return Response({"detail": "Cannot reject own request"}, status=status.HTTP_400_BAD_REQUEST)
        if pr.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=status.HTTP_400_BAD_REQUEST)
        if pr.requires_system_admin_approval and role != "system_admin":
            return Response({"detail": "System Admin approval required"}, status=status.HTTP_403_FORBIDDEN)

        pr.status = "rejected"
        pr.approver = request.user
        pr.approval_decision = "rejected"
        pr.approval_reason = request.data.get("reason", "")
        pr.approved_at = timezone.now()
        pr.save()
        ProcurementHistory.objects.create(purchase_request=pr, actor=request.user, action="rejected", detail=pr.approval_reason or "Rejected")
        log_action(actor=request.user, action="reject", instance=pr, reason="purchase request rejected")
        return Response(self.get_serializer(pr).data)

    @action(detail=True, methods=["post"])
    def return_for_correction(self, request, pk=None):
        pr = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=status.HTTP_400_BAD_REQUEST)

        pr.status = "returned_for_correction"
        pr.approver = request.user
        pr.approval_decision = "returned"
        pr.approval_reason = request.data.get("reason", "")
        pr.save()
        ProcurementHistory.objects.create(purchase_request=pr, actor=request.user, action="returned", detail=pr.approval_reason or "Returned for correction")
        log_action(actor=request.user, action="update", instance=pr, reason="purchase request returned for correction")
        return Response(self.get_serializer(pr).data)


class PurchaseRequestItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequestItem.objects.all()
    serializer_class = PurchaseRequestItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseRequestItem.objects.all()
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(purchase_request__requester=user)
        return qs


class PurchaseQuotationViewSet(viewsets.ModelViewSet):
    queryset = PurchaseQuotation.objects.all()
    serializer_class = PurchaseQuotationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseQuotation.objects.all()
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(purchase_request__requester=user)
        return qs

    @action(detail=True, methods=["post"])
    def select(self, request, pk=None):
        quote = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")

        PurchaseQuotation.objects.filter(purchase_request=quote.purchase_request).update(is_selected=False)
        quote.is_selected = True
        quote.selected_by = request.user
        quote.selected_at = timezone.now()
        quote.selection_reason = request.data.get("reason", "")
        quote.save()
        log_action(actor=request.user, action="update", instance=quote, reason="quotation selected")
        return Response(self.get_serializer(quote).data)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = PurchaseOrder.objects.all()
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(created_by=user)
        return qs

    @action(detail=True, methods=["post"])
    def generate_from_pr(self, request, pk=None):
        pr = get_object_or_404(PurchaseRequest, pk=pk)
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if pr.status != "approved":
            return Response({"detail": "Purchase request must be approved"}, status=status.HTTP_400_BAD_REQUEST)

        selected_quote = pr.quotations.filter(is_selected=True).first()
        if not selected_quote:
            return Response({"detail": "No quotation selected"}, status=status.HTTP_400_BAD_REQUEST)

        settings = ProcurementSetting.get_settings()

        with timezone.now() as _:
            po = PurchaseOrder.objects.create(
                purchase_request=pr,
                vendor=selected_quote.vendor,
                created_by=request.user,
                status="pending_approval",
                delivery_address=settings.delivery_address,
                terms=settings.po_terms,
                currency=settings.currency,
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
            po.save()

            pr.status = "po_generated"
            pr.save()

            ProcurementHistory.objects.create(purchase_order=po, actor=request.user, action="po_generated", detail=f"PO generated from {pr.pr_number}")
            ProcurementHistory.objects.create(purchase_request=pr, actor=request.user, action="po_generated", detail=f"PO {po.po_number} generated")
            log_action(actor=request.user, action="create", instance=po, reason="purchase order generated")

        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        po = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if po.created_by == request.user:
            return Response({"detail": "Cannot approve own PO"}, status=status.HTTP_400_BAD_REQUEST)
        if po.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=status.HTTP_400_BAD_REQUEST)
        if po.requires_system_admin_approval and getattr(request.user, "role", "") != "system_admin":
            return Response({"detail": "System Admin approval required"}, status=status.HTTP_403_FORBIDDEN)

        po.status = "approved"
        po.approver = request.user
        po.approval_decision = "approved"
        po.approval_reason = request.data.get("reason", "")
        po.approved_at = timezone.now()
        po.save()
        ProcurementHistory.objects.create(purchase_order=po, actor=request.user, action="approved", detail=po.approval_reason or "Approved")
        log_action(actor=request.user, action="approve", instance=po, reason="purchase order approved")
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        po = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if po.status != "pending_approval":
            return Response({"detail": "Not pending approval"}, status=status.HTTP_400_BAD_REQUEST)
        if po.requires_system_admin_approval and getattr(request.user, "role", "") != "system_admin":
            return Response({"detail": "System Admin approval required"}, status=status.HTTP_403_FORBIDDEN)

        po.status = "rejected"
        po.approver = request.user
        po.approval_decision = "rejected"
        po.approval_reason = request.data.get("reason", "")
        po.save()
        ProcurementHistory.objects.create(purchase_order=po, actor=request.user, action="rejected", detail=po.approval_reason or "Rejected")
        log_action(actor=request.user, action="reject", instance=po, reason="purchase order rejected")
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def send_to_vendor(self, request, pk=None):
        po = self.get_object()
        if not is_manager_or_admin(request.user):
            raise PermissionDenied("Forbidden")
        if po.status != "approved":
            return Response({"detail": "PO must be approved first"}, status=status.HTTP_400_BAD_REQUEST)

        po.status = "sent_to_vendor"
        po.sent_at = timezone.now()
        po.save()
        ProcurementHistory.objects.create(purchase_order=po, actor=request.user, action="sent", detail="Sent to vendor")
        log_action(actor=request.user, action="update", instance=po, reason="purchase order sent to vendor")
        return Response(self.get_serializer(po).data)


class PurchaseOrderItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrderItem.objects.all()
    serializer_class = PurchaseOrderItemSerializer
    permission_classes = [permissions.IsAuthenticated]


class GoodsReceiptViewSet(viewsets.ModelViewSet):
    queryset = GoodsReceipt.objects.all()
    serializer_class = GoodsReceiptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = GoodsReceipt.objects.all()
        if not (is_manager_or_admin(user) or user.is_superuser):
            qs = qs.filter(received_by=user)
        return qs

    def perform_create(self, serializer):
        gr = serializer.save(received_by=self.request.user)
        ProcurementHistory.objects.create(purchase_order=gr.purchase_order, actor=self.request.user, action="received", detail=f"Goods received: {gr.gr_number}")
        log_action(actor=self.request.user, action="create", instance=gr, reason="goods receipt created")

        po = gr.purchase_order
        po.status = "partially_received"
        po.save()


class GoodsReceiptItemViewSet(viewsets.ModelViewSet):
    queryset = GoodsReceiptItem.objects.all()
    serializer_class = GoodsReceiptItemSerializer
    permission_classes = [permissions.IsAuthenticated]
