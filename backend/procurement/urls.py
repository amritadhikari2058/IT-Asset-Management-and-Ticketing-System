from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    ProcurementSettingViewSet, PurchaseRequestViewSet, PurchaseRequestItemViewSet,
    PurchaseQuotationViewSet, PurchaseOrderViewSet, PurchaseOrderItemViewSet,
    GoodsReceiptViewSet, GoodsReceiptItemViewSet,
    ProcurementAttachmentViewSet, ProcurementAssetReceiptItemViewSet,
    SupplierInvoiceViewSet, SupplierInvoiceLineViewSet,
    InvoiceMatchResultViewSet, InvoiceExceptionViewSet,
    VendorReturnViewSet, VendorReturnLineViewSet,
    VendorCreditNoteViewSet, VendorCreditNoteLineViewSet,
    ProcurementFinancialHistoryViewSet,
    procurement_dashboard, procurement_financial_dashboard,
    report_invoice_aging, report_match_rate, report_exceptions,
    report_vendor_returns, report_credits, report_payment_readiness,
    report_vendor_performance,
)

router = DefaultRouter()
router.register("settings", ProcurementSettingViewSet, basename="procurement-settings")
router.register("purchase-requests", PurchaseRequestViewSet, basename="purchase-request")
router.register("purchase-request-items", PurchaseRequestItemViewSet, basename="purchase-request-item")
router.register("quotations", PurchaseQuotationViewSet, basename="purchase-quotation")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("purchase-order-items", PurchaseOrderItemViewSet, basename="purchase-order-item")
router.register("goods-receipts", GoodsReceiptViewSet, basename="goods-receipt")
router.register("goods-receipt-items", GoodsReceiptItemViewSet, basename="goods-receipt-item")
router.register("attachments", ProcurementAttachmentViewSet, basename="procurement-attachment")
router.register("asset-receipt-items", ProcurementAssetReceiptItemViewSet, basename="procurement-asset-receipt-item")
# P3
router.register("supplier-invoices", SupplierInvoiceViewSet, basename="supplier-invoice")
router.register("supplier-invoice-lines", SupplierInvoiceLineViewSet, basename="supplier-invoice-line")
router.register("invoice-match-results", InvoiceMatchResultViewSet, basename="invoice-match-result")
router.register("invoice-exceptions", InvoiceExceptionViewSet, basename="invoice-exception")
router.register("vendor-returns", VendorReturnViewSet, basename="vendor-return")
router.register("vendor-return-lines", VendorReturnLineViewSet, basename="vendor-return-line")
router.register("credit-notes", VendorCreditNoteViewSet, basename="credit-note")
router.register("credit-note-lines", VendorCreditNoteLineViewSet, basename="credit-note-line")
router.register("financial-history", ProcurementFinancialHistoryViewSet, basename="procurement-financial-history")

urlpatterns = [
    path("dashboard/", procurement_dashboard, name="procurement-dashboard"),
    path("financial-dashboard/", procurement_financial_dashboard, name="procurement-financial-dashboard"),
    path("reports/invoice-aging/", report_invoice_aging, name="procurement-report-invoice-aging"),
    path("reports/match-rate/", report_match_rate, name="procurement-report-match-rate"),
    path("reports/exceptions/", report_exceptions, name="procurement-report-exceptions"),
    path("reports/vendor-returns/", report_vendor_returns, name="procurement-report-vendor-returns"),
    path("reports/credits/", report_credits, name="procurement-report-credits"),
    path("reports/payment-readiness/", report_payment_readiness, name="procurement-report-payment-readiness"),
    path("reports/vendor-performance/", report_vendor_performance, name="procurement-report-vendor-performance"),
    path("", include(router.urls)),
]
