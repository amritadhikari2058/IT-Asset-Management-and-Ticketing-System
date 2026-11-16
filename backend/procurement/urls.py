from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    ProcurementSettingViewSet, PurchaseRequestViewSet, PurchaseRequestItemViewSet,
    PurchaseQuotationViewSet, PurchaseOrderViewSet, PurchaseOrderItemViewSet,
    GoodsReceiptViewSet, GoodsReceiptItemViewSet,
    ProcurementAttachmentViewSet, ProcurementAssetReceiptItemViewSet,
    procurement_dashboard,
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
router.register(
    "asset-receipt-items", ProcurementAssetReceiptItemViewSet,
    basename="procurement-asset-receipt-item",
)

urlpatterns = [
    path("dashboard/", procurement_dashboard, name="procurement-dashboard"),
    path("", include(router.urls)),
]
