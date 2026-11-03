from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User, Department
from services.models import ServiceRequest
from .models import StockItem, StockMovement, StockReservation, PurchaseReceipt
from .serializers import (StockItemSerializer, StockMovementSerializer,
                          StockReservationSerializer, PurchaseReceiptSerializer)


def is_staff(user):
    return user.is_authenticated and getattr(user, "role", "") in ("it_support", "it_manager", "system_admin")


def is_manager(user):
    return user.is_authenticated and getattr(user, "role", "") in ("it_manager", "system_admin")


class StockItemViewSet(viewsets.ModelViewSet):
    queryset = StockItem.objects.all()
    serializer_class = StockItemSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        if not is_staff(self.request.user):
            qs = qs.filter(is_active=True, is_deleted=False)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(sku__icontains=q)
        cat = self.request.query_params.get("category")
        if cat:
            qs = qs.filter(category=cat)
        low = self.request.query_params.get("low_stock")
        if low:
            from django.db.models import F
            qs = qs.filter(quantity__lte=F("reorder_threshold"))
        return qs

    def perform_create(self, serializer):
        if not is_staff(self.request.user):
            raise PermissionDenied()
        serializer.save()

    def perform_update(self, serializer):
        if not is_staff(self.request.user):
            raise PermissionDenied()
        serializer.save()

    def perform_destroy(self, instance):
        if not is_manager(self.request.user):
            raise PermissionDenied()
        instance.soft_delete(self.request.user)

    @action(detail=True, methods=["post"], url_path="receive")
    def receive(self, request, pk=None):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        item = self.get_object()
        qty = int(request.data.get("quantity", 0))
        if qty <= 0:
            return Response({"detail": "quantity must be positive"}, status=400)
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=item.pk)
            prev = item.quantity
            item.quantity += qty
            item.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="receive", quantity=qty,
                previous_balance=prev, new_balance=item.quantity,
                recorded_by=request.user, reason=request.data.get("reason", ""),
                reference=request.data.get("reference", ""),
            )
        return Response(StockItemSerializer(item).data)

    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, pk=None):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        item = self.get_object()
        qty = int(request.data.get("quantity", 0))
        if qty <= 0:
            return Response({"detail": "quantity must be positive"}, status=400)
        emp_id = request.data.get("employee")
        dept_id = request.data.get("department")
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=item.pk)
            if item.available < qty:
                return Response({"detail": "Insufficient stock"}, status=400)
            prev = item.quantity
            item.quantity -= qty
            item.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="issue", quantity=-qty,
                previous_balance=prev, new_balance=item.quantity,
                employee_id=emp_id, department_id=dept_id,
                recorded_by=request.user, reason=request.data.get("reason", ""),
                reference=request.data.get("reference", ""),
                source_request_id=request.data.get("source_request"),
            )
        return Response(StockItemSerializer(item).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_stock(self, request, pk=None):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        item = self.get_object()
        qty = int(request.data.get("quantity", 0))
        if qty <= 0:
            return Response({"detail": "quantity must be positive"}, status=400)
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=item.pk)
            prev = item.quantity
            item.quantity += qty
            item.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="return", quantity=qty,
                previous_balance=prev, new_balance=item.quantity,
                recorded_by=request.user, reason=request.data.get("reason", ""),
                reference=request.data.get("reference", ""),
            )
        return Response(StockItemSerializer(item).data)

    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        if not is_manager(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        item = self.get_object()
        qty = int(request.data.get("quantity", 0))  # signed
        reason = request.data.get("reason", "")
        if not reason:
            return Response({"detail": "reason required"}, status=400)
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=item.pk)
            prev = item.quantity
            new = item.quantity + qty
            if new < 0:
                return Response({"detail": "Negative stock not allowed"}, status=400)
            item.quantity = new
            item.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="adjustment", quantity=qty,
                previous_balance=prev, new_balance=item.quantity,
                recorded_by=request.user, reason=reason,
            )
        return Response(StockItemSerializer(item).data)

    @action(detail=True, methods=["post"], url_path="damage")
    def damage(self, request, pk=None):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        item = self.get_object()
        qty = int(request.data.get("quantity", 0))
        if qty <= 0:
            return Response({"detail": "quantity must be positive"}, status=400)
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=item.pk)
            if item.quantity < qty:
                return Response({"detail": "Insufficient stock"}, status=400)
            prev = item.quantity
            item.quantity -= qty
            item.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="damage", quantity=-qty,
                previous_balance=prev, new_balance=item.quantity,
                recorded_by=request.user, reason=request.data.get("reason", ""),
            )
        return Response(StockItemSerializer(item).data)

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        from django.db.models import F
        qs = StockItem.objects.filter(is_active=True, is_deleted=False, quantity__lte=F("reorder_threshold"))
        return Response(StockItemSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        from django.db.models import F, Sum
        active = StockItem.objects.filter(is_active=True, is_deleted=False)
        total_items = active.count()
        total_units = active.aggregate(s=Sum("quantity"))["s"] or 0
        low = active.filter(quantity__lte=F("reorder_threshold"), quantity__gt=0).count()
        out = active.filter(quantity__lte=0).count()
        reserved = active.aggregate(s=Sum("reserved"))["s"] or 0
        recent_moves = StockMovement.objects.all()[:10]
        return Response({
            "total_items": total_items,
            "total_units": total_units,
            "low_stock": low,
            "out_of_stock": out,
            "reserved": reserved,
            "recent_movements": StockMovementSerializer(recent_moves, many=True).data,
        })

    @action(detail=False, methods=["get"], url_path="movements")
    def movements(self, request):
        qs = StockMovement.objects.all()
        item = request.query_params.get("stock_item")
        if item:
            qs = qs.filter(stock_item_id=item)
        return Response(StockMovementSerializer(qs[:200], many=True).data)


class PurchaseReceiptViewSet(viewsets.ModelViewSet):
    queryset = PurchaseReceipt.objects.all()
    serializer_class = PurchaseReceiptSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        if not is_staff(self.request.user):
            raise PermissionDenied()
        receipt = serializer.save(received_by=self.request.user)
        # increase stock for each line
        with transaction.atomic():
            for line in receipt.lines.all():
                item = StockItem.objects.select_for_update().get(pk=line.stock_item_id)
                prev = item.quantity
                item.quantity += line.quantity
                item.save(update_fields=["quantity", "updated_at"])
                StockMovement.objects.create(
                    stock_item=item, movement_type="receive", quantity=line.quantity,
                    previous_balance=prev, new_balance=item.quantity,
                    recorded_by=self.request.user, reference=receipt.purchase_reference or str(receipt.id),
                    reason="Purchase receipt",
                )

    def create(self, request, *args, **kwargs):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        return super().create(request, *args, **kwargs)


class StockReservationViewSet(viewsets.ModelViewSet):
    queryset = StockReservation.objects.all()
    serializer_class = StockReservationSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        if not is_staff(self.request.user):
            raise PermissionDenied()
        res = serializer.save(created_by=self.request.user, status="active")
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=res.stock_item_id)
            if item.available < res.quantity:
                res.delete()
                raise ValueError("Insufficient stock to reserve")
            item.reserved += res.quantity
            item.save(update_fields=["reserved", "updated_at"])

    def create(self, request, *args, **kwargs):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        try:
            return super().create(request, *args, **kwargs)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        res = self.get_object()
        if res.status != "active":
            return Response({"detail": "Not active"}, status=400)
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=res.stock_item_id)
            item.reserved = max(0, item.reserved - res.quantity)
            item.save(update_fields=["reserved", "updated_at"])
            res.status = "released"
            res.save(update_fields=["status", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="release", quantity=res.quantity,
                previous_balance=item.quantity, new_balance=item.quantity,
                recorded_by=request.user, reason="Reservation released",
                source_request=res.service_request,
            )
        return Response(StockReservationSerializer(res).data)

    @action(detail=True, methods=["post"], url_path="fulfil")
    def fulfil(self, request, pk=None):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        res = self.get_object()
        if res.status != "active":
            return Response({"detail": "Not active"}, status=400)
        with transaction.atomic():
            item = StockItem.objects.select_for_update().get(pk=res.stock_item_id)
            if item.quantity < res.quantity:
                return Response({"detail": "Insufficient stock"}, status=400)
            prev = item.quantity
            item.quantity -= res.quantity
            item.reserved = max(0, item.reserved - res.quantity)
            item.save(update_fields=["quantity", "reserved", "updated_at"])
            res.status = "fulfilled"
            res.save(update_fields=["status", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, movement_type="issue", quantity=-res.quantity,
                previous_balance=prev, new_balance=item.quantity,
                recorded_by=request.user, reason="Reservation fulfilled",
                source_request=res.service_request,
            )
        return Response(StockReservationSerializer(res).data)


class ServiceRequestFulfilView(viewsets.ViewSet):
    def create(self, request):
        if not is_staff(request.user):
            return Response({"detail": "Forbidden"}, status=403)
        sr_id = request.data.get("service_request")
        try:
            sr = ServiceRequest.objects.get(pk=sr_id)
        except ServiceRequest.DoesNotExist:
            return Response({"detail": "Not found"}, status=404)
        # prevent duplicate
        if StockMovement.objects.filter(source_request=sr).exists():
            return Response({"detail": "Already fulfilled"}, status=400)
        stock_item_id = request.data.get("stock_item")
        qty = int(request.data.get("quantity", 1))
        if stock_item_id:
            with transaction.atomic():
                item = StockItem.objects.select_for_update().get(pk=stock_item_id)
                if item.available < qty:
                    return Response({"detail": "Insufficient stock"}, status=400)
                prev = item.quantity
                item.quantity -= qty
                item.save(update_fields=["quantity", "updated_at"])
                StockMovement.objects.create(
                    stock_item=item, movement_type="issue", quantity=-qty,
                    previous_balance=prev, new_balance=item.quantity,
                    recorded_by=request.user, reason="Service request fulfilment",
                    source_request=sr,
                )
            sr.fulfilment_details = f"Issued {qty} x {item.name}"
            sr.status = "fulfilled"
            sr.resolved_at = timezone.now()
            sr.save(update_fields=["fulfilment_details", "status", "resolved_at"])
        return Response({"detail": "Fulfilled"})
