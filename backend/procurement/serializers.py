from rest_framework import serializers
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, ProcurementHistory
)
from assets.serializers import VendorSerializer


class ProcurementSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcurementSetting
        fields = "__all__"
        read_only_fields = ["updated_at", "updated_by"]


class PurchaseRequestItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseRequestItem
        fields = "__all__"
        read_only_fields = ["created_at"]


class PurchaseQuotationSerializer(serializers.ModelSerializer):
    vendor_detail = VendorSerializer(source="vendor", read_only=True)
    selected_by_name = serializers.CharField(source="selected_by.email", read_only=True)

    class Meta:
        model = PurchaseQuotation
        fields = "__all__"
        read_only_fields = ["created_at", "selected_by", "selected_at"]


class ProcurementHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = ProcurementHistory
        fields = "__all__"
        read_only_fields = ["created_at"]


class PurchaseRequestSerializer(serializers.ModelSerializer):
    items = PurchaseRequestItemSerializer(many=True, read_only=True)
    quotations = PurchaseQuotationSerializer(many=True, read_only=True)
    history = ProcurementHistorySerializer(many=True, read_only=True)
    requester_name = serializers.CharField(source="requester.email", read_only=True)
    approver_name = serializers.CharField(source="approver.email", read_only=True)

    class Meta:
        model = PurchaseRequest
        fields = "__all__"
        read_only_fields = ["pr_number", "requester", "approver", "approval_decision", 
                           "approval_reason", "approved_at", "created_at", "updated_at"]


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderItem
        fields = "__all__"
        read_only_fields = ["created_at"]


class GoodsReceiptItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoodsReceiptItem
        fields = "__all__"
        read_only_fields = ["created_at"]


class GoodsReceiptSerializer(serializers.ModelSerializer):
    items = GoodsReceiptItemSerializer(many=True, read_only=True)
    received_by_name = serializers.CharField(source="received_by.email", read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = "__all__"
        read_only_fields = ["gr_number", "received_by", "received_at", "created_at", "updated_at"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    goods_receipts = GoodsReceiptSerializer(many=True, read_only=True)
    history = ProcurementHistorySerializer(many=True, read_only=True)
    vendor_detail = VendorSerializer(source="vendor", read_only=True)
    created_by_name = serializers.CharField(source="created_by.email", read_only=True)
    approver_name = serializers.CharField(source="approver.email", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ["po_number", "created_by", "approver", "approval_decision",
                           "approval_reason", "approved_at", "sent_at", "completed_at",
                           "created_at", "updated_at"]
