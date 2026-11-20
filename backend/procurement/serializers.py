from decimal import Decimal
from rest_framework import serializers
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem,
    ProcurementHistory, ProcurementAttachment, ProcurementAssetReceiptItem,
    SupplierInvoice, SupplierInvoiceLine, InvoiceMatchResult, InvoiceException,
    VendorReturn, VendorReturnLine, VendorCreditNote, VendorCreditNoteLine,
    ProcurementFinancialHistory, derive_discrepancy_status,
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

    def validate(self, attrs):
        item_name = attrs.get("item_name", getattr(self.instance, "item_name", ""))
        if not str(item_name or "").strip():
            raise serializers.ValidationError({"item_name": "Item name is required."})
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", 1))
        if quantity is None or int(quantity) <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        unit_price = attrs.get("estimated_unit_price", getattr(self.instance, "estimated_unit_price", None))
        estimated_total = attrs.get("estimated_total", getattr(self.instance, "estimated_total", None))
        if estimated_total is not None and unit_price is not None:
            expected = Decimal(str(quantity or 0)) * Decimal(str(unit_price))
            if Decimal(str(estimated_total)) != expected:
                raise serializers.ValidationError({
                    "estimated_total": f"Estimated total must equal quantity x unit price ({expected}).",
                })
        for field in ("estimated_unit_price", "estimated_total"):
            value = attrs.get(field, getattr(self.instance, field, None))
            if value is not None and value < 0:
                raise serializers.ValidationError({field: "Value cannot be negative."})
        return attrs


class PurchaseQuotationSerializer(serializers.ModelSerializer):
    vendor_detail = VendorSerializer(source="vendor", read_only=True)
    selected_by_name = serializers.CharField(source="selected_by.email", read_only=True)

    class Meta:
        model = PurchaseQuotation
        fields = "__all__"
        read_only_fields = ["created_at", "selected_by", "selected_at"]

    def validate(self, attrs):
        amount = attrs.get("quoted_amount", getattr(self.instance, "quoted_amount", None))
        if amount is None or amount <= 0:
            raise serializers.ValidationError({"quoted_amount": "Quoted amount must be greater than zero."})
        delivery_days = attrs.get("delivery_days", getattr(self.instance, "delivery_days", None))
        if delivery_days is not None and delivery_days < 0:
            raise serializers.ValidationError({"delivery_days": "Delivery days cannot be negative."})
        return attrs


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

    def validate(self, attrs):
        reason = attrs.get("reason", getattr(self.instance, "reason", ""))
        if not str(reason or "").strip():
            raise serializers.ValidationError({"reason": "Business justification is required."})
        total = attrs.get("estimated_total", getattr(self.instance, "estimated_total", 0))
        if total is not None and total < 0:
            raise serializers.ValidationError({"estimated_total": "Estimated total cannot be negative."})
        return attrs

    class Meta:
        model = PurchaseRequest
        fields = "__all__"
        read_only_fields = ["pr_number", "requester", "approver", "approval_decision",
                           "approval_reason", "approved_at", "cancelled_at",
                           "cancellation_reason", "estimated_total", "version",
                           "created_at", "updated_at"]


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderItem
        fields = "__all__"
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", 1))
        if quantity is None or int(quantity) <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        for field in ("unit_price", "tax", "discount", "total"):
            value = attrs.get(field, getattr(self.instance, field, None))
            if value is not None and value < 0:
                raise serializers.ValidationError({field: "Value cannot be negative."})
        return attrs


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
        if received == 0 and rejected == 0 and damaged == 0:
            raise serializers.ValidationError({
                "quantity_received": "Receipt quantity must be greater than zero.",
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
        source="uploaded_by.email", read_only=True, allow_null=True)
    download_url = serializers.SerializerMethodField()
    parent_type = serializers.SerializerMethodField()

    def get_download_url(self, obj):
        return f"/api/procurement/attachments/{obj.pk}/download/"

    def get_parent_type(self, obj):
        if obj.purchase_request_id:
            return "purchase_request"
        if obj.quotation_id:
            return "quotation"
        if obj.purchase_order_id:
            return "purchase_order"
        if obj.goods_receipt_id:
            return "goods_receipt"
        if obj.supplier_invoice_id:
            return "supplier_invoice"
        if obj.vendor_return_id:
            return "vendor_return"
        if obj.credit_note_id:
            return "credit_note"
        return None

    class Meta:
        model = ProcurementAttachment
        fields = "__all__"
        read_only_fields = [
            "uploaded_by", "original_filename", "file", "content_type", "size",
            "checksum", "status", "created_at", "updated_at",
        ]

    def validate_file(self, f):
        from tickets.serializers import validate_attachment_file
        return validate_attachment_file(f)

    def validate(self, attrs):
        parents = [
            attrs.get("purchase_request") or getattr(self.instance, "purchase_request_id", None),
            attrs.get("quotation") or getattr(self.instance, "quotation_id", None),
            attrs.get("purchase_order") or getattr(self.instance, "purchase_order_id", None),
            attrs.get("goods_receipt") or getattr(self.instance, "goods_receipt_id", None),
            attrs.get("supplier_invoice") or getattr(self.instance, "supplier_invoice_id", None),
            attrs.get("vendor_return") or getattr(self.instance, "vendor_return_id", None),
            attrs.get("credit_note") or getattr(self.instance, "credit_note_id", None),
        ]
        if sum(1 for p in parents if p) != 1:
            raise serializers.ValidationError({
                "parent": "Attach the file to exactly one procurement record.",
            })
        return attrs


class ProcurementAssetReceiptItemSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)
    gr_number = serializers.CharField(source="goods_receipt.gr_number", read_only=True)
    item_name = serializers.CharField(source="purchase_order_item.item_name", read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, allow_null=True)

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
    serial_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=200)
    model = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    manufacturer = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    location = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    department = serializers.IntegerField(required=False, allow_null=True)
    category = serializers.IntegerField(required=False, allow_null=True)
    warranty_expiry = serializers.DateField(required=False, allow_null=True)
    purchase_cost = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# P3: Supplier invoicing, matching, returns, credit notes, financial control
# ---------------------------------------------------------------------------

class SupplierInvoiceLineSerializer(serializers.ModelSerializer):
    po_item_name = serializers.CharField(source="purchase_order_item.item_name", read_only=True, default=None)
    goods_receipt_number = serializers.CharField(source="goods_receipt_item.goods_receipt.gr_number", read_only=True, default=None)
    class Meta:
        model = SupplierInvoiceLine
        fields = "__all__"
        read_only_fields = [
            "accepted_quantity_snapshot", "line_subtotal", "line_total",
            "matched_quantity", "quantity_variance", "price_variance",
            "tax_variance", "total_variance", "match_status", "exception_reason",
            "created_at", "updated_at",
        ]


class SupplierInvoiceLineCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierInvoiceLine
        fields = [
            "invoice", "purchase_order_item", "goods_receipt_item", "description",
            "invoiced_quantity", "unit_price", "discount_amount", "tax_rate", "tax_amount",
            "freight_allocation", "other_charge_allocation",
        ]


class SupplierInvoiceListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, default=None)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True, default=None)
    created_by_name = serializers.CharField(source="created_by.email", read_only=True, default=None)
    latest_match = serializers.SerializerMethodField()
    def get_latest_match(self, obj):
        m = getattr(obj, '_prefetched_objects_cache', {}).get('match_results')
        if m is not None:
            m = m[0] if m else None
        else:
            m = obj.match_results.order_by('-match_version', '-created_at').first()
        if not m:
            return None
        return {"overall_status": m.overall_status, "match_version": m.match_version, "total_variance": str(m.total_variance)}
    class Meta:
        model = SupplierInvoice
        fields = "__all__"


class SupplierInvoiceDetailSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, default=None)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True, default=None)
    created_by_name = serializers.CharField(source="created_by.email", read_only=True, default=None)
    lines = SupplierInvoiceLineSerializer(many=True, read_only=True)
    latest_match = serializers.SerializerMethodField()
    def get_latest_match(self, obj):
        m = obj.match_results.order_by('-match_version', '-created_at').first()
        if not m:
            return None
        return InvoiceMatchResultSerializer(m).data
    class Meta:
        model = SupplierInvoice
        fields = "__all__"


class SupplierInvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierInvoice
        fields = [
            "invoice_number", "vendor", "purchase_order", "invoice_date", "received_date",
            "due_date", "currency", "discount_total", "freight_total", "other_charge_total",
            "external_accounting_reference", "notes",
        ]

class SupplierInvoiceUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierInvoice
        fields = [
            "invoice_number", "vendor", "purchase_order", "invoice_date", "received_date",
            "due_date", "currency", "discount_total", "freight_total", "other_charge_total",
            "external_accounting_reference", "notes",
        ]


class SupplierInvoiceActionSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)

class SupplierInvoiceSubmitSerializer(SupplierInvoiceActionSerializer): pass
class SupplierInvoiceMatchSerializer(SupplierInvoiceActionSerializer): pass
class SupplierInvoiceApproveSerializer(SupplierInvoiceActionSerializer): pass
class SupplierInvoiceRejectSerializer(SupplierInvoiceActionSerializer):
    reason = serializers.CharField(required=True)
class SupplierInvoiceReturnSerializer(SupplierInvoiceActionSerializer):
    reason = serializers.CharField(required=True)
class SupplierInvoiceHoldSerializer(SupplierInvoiceActionSerializer):
    reason = serializers.CharField(required=True)
class SupplierInvoicePaymentReadySerializer(SupplierInvoiceActionSerializer): pass
class SupplierInvoiceMarkPaidSerializer(SupplierInvoiceActionSerializer):
    payment_reference = serializers.CharField(required=True)
    payment_date = serializers.DateField(required=True)
class SupplierInvoiceCancelSerializer(SupplierInvoiceActionSerializer):
    reason = serializers.CharField(required=True)
class SupplierInvoiceCloseSerializer(SupplierInvoiceActionSerializer): pass


class InvoiceMatchResultSerializer(serializers.ModelSerializer):
    matched_by_name = serializers.CharField(source="matched_by.email", read_only=True, default=None)

    class Meta:
        model = InvoiceMatchResult
        fields = "__all__"
        read_only_fields = [f.name for f in InvoiceMatchResult._meta.fields]

class InvoiceMatchDetailSerializer(InvoiceMatchResultSerializer): pass

class InvoiceReadinessSerializer(serializers.Serializer):
    ready = serializers.BooleanField()
    blockers = serializers.ListField()
    invoice_status = serializers.CharField(required=False)
    payment_status = serializers.CharField(required=False)


class InvoiceExceptionSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True, default=None)
    class Meta:
        model = InvoiceException
        fields = "__all__"

class InvoiceExceptionActionSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)

class InvoiceExceptionAcceptSerializer(InvoiceExceptionActionSerializer):
    reason = serializers.CharField(required=True)
class InvoiceExceptionResolveSerializer(InvoiceExceptionActionSerializer):
    reason = serializers.CharField(required=True)
    resolution = serializers.CharField(required=False, allow_blank=True)


class VendorReturnLineSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True, default=None)
    class Meta:
        model = VendorReturnLine
        fields = "__all__"

class VendorReturnListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, default=None)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True, default=None)
    gr_number = serializers.CharField(source="goods_receipt.gr_number", read_only=True, default=None)
    invoice_number = serializers.CharField(source="supplier_invoice.invoice_number", read_only=True, default=None)
    class Meta:
        model = VendorReturn
        fields = "__all__"

class VendorReturnDetailSerializer(VendorReturnListSerializer):
    lines = VendorReturnLineSerializer(many=True, read_only=True)

class VendorReturnCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorReturn
        fields = [
            "vendor", "purchase_order", "goods_receipt", "supplier_invoice",
            "return_date", "reason", "return_method", "authorization_reference",
            "shipping_reference", "expected_resolution", "replacement_expected", "replacement_due_date",
        ]

class VendorReturnActionSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)
    authorization_reference = serializers.CharField(required=False, allow_blank=True)
class VendorReturnShipSerializer(VendorReturnActionSerializer):
    shipping_reference = serializers.CharField(required=False, allow_blank=True)
class VendorReturnReplacementSerializer(VendorReturnActionSerializer): pass
class VendorReturnCompleteSerializer(VendorReturnActionSerializer): pass


class VendorCreditNoteLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorCreditNoteLine
        fields = "__all__"

class VendorCreditNoteListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, default=None)
    invoice_number = serializers.CharField(source="supplier_invoice.invoice_number", read_only=True, default=None)
    return_number = serializers.CharField(source="vendor_return.return_number", read_only=True, default=None)
    class Meta:
        model = VendorCreditNote
        fields = "__all__"

class VendorCreditNoteDetailSerializer(VendorCreditNoteListSerializer):
    lines = VendorCreditNoteLineSerializer(many=True, read_only=True)

class VendorCreditNoteCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorCreditNote
        fields = [
            "credit_note_number", "vendor", "supplier_invoice", "vendor_return",
            "credit_date", "currency", "subtotal", "tax_total", "total", "reason", "external_reference",
        ]

class VendorCreditNoteActionSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)
class VendorCreditNoteApplySerializer(VendorCreditNoteActionSerializer): pass


class ProcurementFinancialHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = ProcurementFinancialHistory
        fields = "__all__"
        read_only_fields = [f.name for f in ProcurementFinancialHistory._meta.fields]
