from rest_framework import serializers
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem,
    ProcurementHistory, ProcurementAttachment, ProcurementAssetReceiptItem,
    derive_discrepancy_status,
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
    purchase_order_ref = serializers.SerializerMethodField()

    def get_purchase_order_ref(self, obj):
        po = obj.purchase_orders.filter(is_deleted=False).first()
        if po is None:
            return None
        return {"id": po.pk, "po_number": po.po_number, "status": po.status}

    class Meta:
        model = PurchaseRequest
        fields = "__all__"
        read_only_fields = ["pr_number", "requester", "approver", "approval_decision",
                           "approval_reason", "approved_at", "cancelled_at",
                           "cancellation_reason", "version", "created_at", "updated_at"]


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

    def validate(self, attrs):
        """Reject nonsensical or over-delivered receipt lines.

        `quantity_received` is the total that arrived; rejected and damaged
        units must be part of that total. The line can never exceed what is
        still outstanding on the purchase order line, so a double-posted
        receipt is refused instead of silently inflating stock quantities.
        """
        line = attrs.get("purchase_order_item") or getattr(
            self.instance, "purchase_order_item", None)
        if line is None:
            return attrs
        received = attrs.get(
            "quantity_received", getattr(self.instance, "quantity_received", 0) or 0)
        rejected = attrs.get(
            "quantity_rejected", getattr(self.instance, "quantity_rejected", 0) or 0)
        damaged = attrs.get(
            "quantity_damaged", getattr(self.instance, "quantity_damaged", 0) or 0)
        receipt = attrs.get("goods_receipt") or getattr(self.instance, "goods_receipt", None)
        if receipt is not None and receipt.purchase_order_id != line.purchase_order_id:
            raise serializers.ValidationError({
                "purchase_order_item":
                    "This line does not belong to the receipt's purchase order.",
            })
        if rejected + damaged > received:
            raise serializers.ValidationError({
                "quantity_rejected":
                    "Rejected plus damaged quantity cannot exceed the quantity received.",
            })
        booked = (line.received_qty or 0) + (line.rejected_qty or 0) + (line.damaged_qty or 0)
        remaining = max(0, (line.quantity or 0) - booked)
        if self.instance is not None:
            # Editing an existing line: give its previous arrival back first.
            remaining += (self.instance.quantity_received or 0)
        if received > remaining:
            raise serializers.ValidationError({
                "quantity_received": (
                    f"Only {remaining} unit(s) remain to be received on this "
                    "purchase order line."
                ),
            })
        # Structured discrepancy fields are complete for every line. The
        # frontend requires operator-entered reasons; the API keeps accepting
        # the pre-existing payload shape (a verified workflow posts rejected
        # and damaged units with notes only) and records a neutral placeholder
        # rather than silently losing the discrepancy.
        if rejected > 0 and not str(attrs.get(
                "rejection_reason", "") or "").strip():
            attrs["rejection_reason"] = "Reason not supplied"
        if damaged > 0 and not str(attrs.get(
                "damage_notes", "") or "").strip():
            attrs["damage_notes"] = "Damage not described"
        return attrs

    def create(self, validated_data):
        received = validated_data.get("quantity_received", 0) or 0
        rejected = validated_data.get("quantity_rejected", 0) or 0
        damaged = validated_data.get("quantity_damaged", 0) or 0
        validated_data["accepted_quantity"] = max(
            0, received - rejected - damaged)
        validated_data["discrepancy_status"] = derive_discrepancy_status(
            rejected, damaged)
        validated_data["inspection_status"] = (
            "failed" if rejected or damaged else "passed")
        return super().create(validated_data)


class GoodsReceiptSerializer(serializers.ModelSerializer):
    items = GoodsReceiptItemSerializer(many=True, read_only=True)
    received_by_name = serializers.CharField(source="received_by.email", read_only=True)
    purchase_order_number = serializers.CharField(
        source="purchase_order.po_number", read_only=True)
    vendor_name = serializers.CharField(
        source="purchase_order.vendor.name", read_only=True)

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
    purchase_request_number = serializers.CharField(
        source="purchase_request.pr_number", read_only=True, allow_null=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ["po_number", "created_by", "approver", "approval_decision",
                           "approval_reason", "approved_at", "sent_at", "completed_at",
                           "cancelled_at", "cancellation_reason", "closed_at",
                           "closure_reason", "version", "created_at", "updated_at"]


class ProcurementAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(
        source="uploaded_by.email", read_only=True)
    parent_type = serializers.SerializerMethodField()

    class Meta:
        model = ProcurementAttachment
        fields = [
            "id", "purchase_request", "quotation", "purchase_order",
            "goods_receipt", "document_type", "uploaded_by",
            "uploaded_by_name", "original_filename", "file", "content_type",
            "size", "description", "checksum", "status", "parent_type",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "uploaded_by", "original_filename", "content_type", "size",
            "checksum", "created_at", "updated_at",
        ]

    def get_parent_type(self, obj):
        if obj.purchase_request_id:
            return "purchase_request"
        if obj.quotation_id:
            return "quotation"
        if obj.purchase_order_id:
            return "purchase_order"
        if obj.goods_receipt_id:
            return "goods_receipt"
        return None

    def validate_file(self, f):
        from tickets.serializers import validate_attachment_file
        return validate_attachment_file(f)

    def validate(self, attrs):
        parents = [
            attrs.get("purchase_request"),
            attrs.get("quotation"),
            attrs.get("purchase_order"),
            attrs.get("goods_receipt"),
        ]
        if sum(1 for p in parents if p is not None) != 1:
            raise serializers.ValidationError({
                "parent": "Attach the file to exactly one procurement record.",
            })
        return attrs


class ProcurementAssetReceiptItemSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    po_number = serializers.CharField(
        source="purchase_order.po_number", read_only=True)
    gr_number = serializers.CharField(
        source="goods_receipt.gr_number", read_only=True)
    item_name = serializers.CharField(
        source="purchase_order_item.item_name", read_only=True)
    vendor_name = serializers.CharField(
        source="vendor.name", read_only=True, allow_null=True)

    class Meta:
        model = ProcurementAssetReceiptItem
        fields = "__all__"
        read_only_fields = [
            "goods_receipt", "goods_receipt_item", "purchase_order",
            "purchase_order_item", "vendor", "sequence", "status", "asset",
            "expected_purchase_date", "purchase_cost", "registered_at",
            "registered_by", "created_at",
        ]


class RegisterProcurementAssetSerializer(serializers.Serializer):
    """Only values the backend cannot safely infer are accepted here."""

    asset_tag = serializers.CharField(max_length=50)
    serial_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=200)
    model = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="")
    manufacturer = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="")
    location = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="")
    department = serializers.IntegerField(required=False, allow_null=True)
    category = serializers.IntegerField(required=False, allow_null=True)
    warranty_expiry = serializers.DateField(required=False, allow_null=True)
    purchase_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True)
    notes = serializers.CharField(
        required=False, allow_blank=True, default="")
