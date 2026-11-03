from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (StockItemViewSet, PurchaseReceiptViewSet,
                    StockReservationViewSet, ServiceRequestFulfilView)

router = DefaultRouter()
router.register(r"stock-items", StockItemViewSet, basename="stockitem")
router.register(r"purchase-receipts", PurchaseReceiptViewSet, basename="purchasereceipt")
router.register(r"reservations", StockReservationViewSet, basename="stockreservation")

urlpatterns = [
    path("", include(router.urls)),
    path("fulfil-service-request/", ServiceRequestFulfilView.as_view({"post": "create"}), name="fulfil-sr"),
]
