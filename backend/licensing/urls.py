"""URL configuration for Software Licensing app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from licensing.views import (
    LicenseAgreementViewSet,
    LicenseAllocationViewSet,
    LicenseComplianceFindingViewSet,
    LicenseDocumentViewSet,
    LicenseHistoryViewSet,
    LicenseRenewalViewSet,
    LicenseSecretViewSet,
    SoftwareInstallationViewSet,
    SoftwareProductViewSet,
    compliance_summary,
    entitlement_reconciliation,
    licensing_dashboard,
    renewal_calendar,
    utilization_report,
)

router = DefaultRouter()
router.register("products", SoftwareProductViewSet, basename="product")
router.register("agreements", LicenseAgreementViewSet, basename="agreement")
router.register("secrets", LicenseSecretViewSet, basename="secret")
router.register("allocations", LicenseAllocationViewSet, basename="allocation")
router.register("installations", SoftwareInstallationViewSet, basename="installation")
router.register("renewals", LicenseRenewalViewSet, basename="renewal")
router.register("documents", LicenseDocumentViewSet, basename="document")
router.register("findings", LicenseComplianceFindingViewSet, basename="finding")
router.register("history", LicenseHistoryViewSet, basename="history")

urlpatterns = [
    path("dashboard/", licensing_dashboard, name="licensing-dashboard"),
    path("renewal-calendar/", renewal_calendar, name="licensing-renewal-calendar"),
    path("utilization-report/", utilization_report, name="licensing-utilization-report"),
    path("entitlement-reconciliation/", entitlement_reconciliation, name="licensing-entitlement-reconciliation"),
    path("compliance-summary/", compliance_summary, name="licensing-compliance-summary"),
    path("", include(router.urls)),
]
