from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ServiceCatalogueItemViewSet, ServiceRequestViewSet

router = DefaultRouter()
router.register("catalogue", ServiceCatalogueItemViewSet, basename="service-catalogue")
router.register("requests", ServiceRequestViewSet, basename="service-request")

urlpatterns = [
    path("", include(router.urls)),
]
