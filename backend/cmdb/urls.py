from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    ConfigurationItemTypeViewSet, ConfigurationItemViewSet,
    ConfigurationItemRelationshipViewSet, ConfigurationItemHistoryViewSet,
    ConfigurationBaselineViewSet, ConfigurationDriftFindingViewSet,
    CMDBServiceProfileViewSet, ServiceConfigurationItemLinkViewSet,
    ConfigurationItemTicketLinkViewSet, ConfigurationItemChangeLinkViewSet,
    DashboardView, ReportsView,
)

router = DefaultRouter()
router.register("types", ConfigurationItemTypeViewSet, basename="cmdb-type")
router.register("items", ConfigurationItemViewSet, basename="cmdb-item")
router.register("relationships", ConfigurationItemRelationshipViewSet, basename="cmdb-relationship")
router.register("history", ConfigurationItemHistoryViewSet, basename="cmdb-history")
router.register("baselines", ConfigurationBaselineViewSet, basename="cmdb-baseline")
router.register("drift", ConfigurationDriftFindingViewSet, basename="cmdb-drift")
router.register("service-profiles", CMDBServiceProfileViewSet, basename="cmdb-service-profile")
router.register("service-links", ServiceConfigurationItemLinkViewSet, basename="cmdb-service-link")
router.register("ticket-links", ConfigurationItemTicketLinkViewSet, basename="cmdb-ticket-link")
router.register("change-links", ConfigurationItemChangeLinkViewSet, basename="cmdb-change-link")

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="cmdb-dashboard"),
    path("reports/", ReportsView.as_view(), name="cmdb-reports"),
    path("", include(router.urls)),
]
