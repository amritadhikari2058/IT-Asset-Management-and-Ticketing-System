from rest_framework import serializers
from .models import StockItem, StockMovement, StockReservation, PurchaseReceipt, PurchaseReceiptLine


class StockItemSerializer(serializers.ModelSerializer):
    available = serializers.IntegerField(read_only=True)
    preferred_vendor_name = serializers.CharField(source="preferred_vendor.name", read_only=True)

    class Meta:
        model = StockItem
        fields = ["id", "name", "description", "sku", "category", "unit", "quantity",
                  "reserved", "available", "reorder_threshold", "preferred_vendor",
                  "preferred_vendor_name", "unit_cost", "is_active", "is_deleted",
                  "created_at", "updated_at"]


class StockMovementSerializer(serializers.ModelSerializer):
    stock_item_name = serializers.CharField(source="stock_item.name", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.username", read_only=True)

    class Meta:
        model = StockMovement
        fields = ["id", "stock_item", "stock_item_name", "movement_type", "quantity",
                  "previous_balance", "new_balance", "employee", "department", "reference",
                  "source_request", "recorded_by", "recorded_by_name", "reason", "created_at"]
        read_only_fields = ["previous_balance", "new_balance", "recorded_by", "created_at"]


class StockReservationSerializer(serializers.ModelSerializer):
    stock_item_name = serializers.CharField(source="stock_item.name", read_only=True)

    class Meta:
        model = StockReservation
        fields = ["id", "stock_item", "stock_item_name", "quantity", "service_request",
                  "status", "created_by", "created_at", "updated_at"]
        read_only_fields = ["status", "created_by", "created_at", "updated_at"]


class PurchaseReceiptLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseReceiptLine
        fields = ["id", "stock_item", "quantity", "unit_cost"]


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    lines = PurchaseReceiptLineSerializer(many=True)

    class Meta:
        model = PurchaseReceipt
        fields = ["id", "vendor", "purchase_reference", "invoice_number", "purchase_date",
                  "received_date", "received_by", "notes", "total_cost", "lines", "created_at"]
        read_only_fields = ["received_by", "created_at", "total_cost"]

    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        receipt = PurchaseReceipt.objects.create(**validated_data)
        total = 0
        for l in lines:
            PurchaseReceiptLine.objects.create(receipt=receipt, **l)
            if l.get("unit_cost") is not None:
                total += l["quantity"] * l["unit_cost"]
        receipt.total_cost = total
        receipt.save(update_fields=["total_cost"])
        return receipt
