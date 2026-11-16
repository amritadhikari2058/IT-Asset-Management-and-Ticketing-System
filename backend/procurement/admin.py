from django.contrib import admin
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, ProcurementHistory,
    ProcurementAttachment, ProcurementAssetReceiptItem,
    SupplierInvoice, SupplierInvoiceLine, InvoiceMatchResult, InvoiceException,
    VendorReturn, VendorReturnLine, VendorCreditNote, VendorCreditNoteLine,
    ProcurementFinancialHistory,
)


@admin.register(ProcurementSetting)
class ProcurementSettingAdmin(admin.ModelAdmin):
    list_display = ("id", "currency", "updated_at")


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ("pr_number", "requester", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("pr_number", "requester__email")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("po_number", "vendor", "status", "total", "created_at")
    list_filter = ("status",)
    search_fields = ("po_number", "vendor__name")


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ("gr_number", "purchase_order", "received_at", "received_by")
    search_fields = ("gr_number", "purchase_order__po_number", "delivery_note_number", "invoice_number")


admin.site.register(PurchaseRequestItem)
admin.site.register(PurchaseQuotation)
admin.site.register(PurchaseOrderItem)
admin.site.register(GoodsReceiptItem)
admin.site.register(ProcurementHistory)
admin.site.register(ProcurementAttachment)
admin.site.register(ProcurementAssetReceiptItem)


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "vendor", "purchase_order", "status", "payment_status", "grand_total", "currency", "invoice_date")
    list_filter = ("status", "payment_status", "currency")
    search_fields = ("invoice_number", "normalized_invoice_number", "vendor__name", "purchase_order__po_number")
    readonly_fields = (
        "normalized_invoice_number", "subtotal", "tax_total", "grand_total",
        "matched_subtotal", "variance_total", "submitted_by", "reviewed_by",
        "approved_by", "submitted_at", "reviewed_at", "approved_at",
        "payment_ready_at", "created_by", "created_at", "updated_at", "version",
    )


@admin.register(SupplierInvoiceLine)
class SupplierInvoiceLineAdmin(admin.ModelAdmin):
    list_display = ("invoice", "purchase_order_item", "invoiced_quantity", "line_total", "match_status")
    list_filter = ("match_status",)
    readonly_fields = (
        "accepted_quantity_snapshot", "line_subtotal", "line_total", "matched_quantity",
        "quantity_variance", "price_variance", "tax_variance", "total_variance", "match_status",
        "exception_reason", "created_at", "updated_at",
    )


@admin.register(InvoiceMatchResult)
class InvoiceMatchResultAdmin(admin.ModelAdmin):
    list_display = ("invoice", "match_version", "overall_status", "total_variance", "matched_at")
    list_filter = ("overall_status",)
    readonly_fields = [f.name for f in InvoiceMatchResult._meta.fields]
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(InvoiceException)
class InvoiceExceptionAdmin(admin.ModelAdmin):
    list_display = ("invoice", "exception_type", "severity", "status", "detected_at")
    list_filter = ("status", "severity", "exception_type")
    search_fields = ("invoice__invoice_number", "reason")
    readonly_fields = ("fingerprint", "detected_at", "created_at", "updated_at")


@admin.register(VendorReturn)
class VendorReturnAdmin(admin.ModelAdmin):
    list_display = ("return_number", "vendor", "purchase_order", "status", "reason", "return_date")
    list_filter = ("status", "reason", "return_method")
    search_fields = ("return_number", "vendor__name", "purchase_order__po_number", "authorization_reference")
    readonly_fields = ("return_number", "created_by", "approved_by", "shipped_by", "completed_by", "approved_at", "shipped_at", "completed_at", "created_at", "updated_at", "version")


@admin.register(VendorReturnLine)
class VendorReturnLineAdmin(admin.ModelAdmin):
    list_display = ("vendor_return", "goods_receipt_item", "quantity", "condition", "disposition", "inventory_reversed")
    list_filter = ("condition", "disposition", "inventory_reversed")
    readonly_fields = ("inventory_reversed", "inventory_reversed_at", "created_at", "updated_at")


@admin.register(VendorCreditNote)
class VendorCreditNoteAdmin(admin.ModelAdmin):
    list_display = ("credit_note_number", "vendor", "supplier_invoice", "status", "total", "applied_amount", "currency")
    list_filter = ("status", "currency")
    search_fields = ("credit_note_number", "vendor__name", "supplier_invoice__invoice_number")
    readonly_fields = ("applied_amount", "created_by", "approved_by", "approved_at", "applied_at", "created_at", "updated_at", "version")


@admin.register(VendorCreditNoteLine)
class VendorCreditNoteLineAdmin(admin.ModelAdmin):
    list_display = ("credit_note", "quantity", "amount")


@admin.register(ProcurementFinancialHistory)
class ProcurementFinancialHistoryAdmin(admin.ModelAdmin):
    list_display = ("event_type", "invoice", "vendor_return", "credit_note", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = [f.name for f in ProcurementFinancialHistory._meta.fields]
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
