"""CMDB URL routing.

Both `/route/` and `/route` variants are registered because the frontend
calls action URLs without trailing slashes (and POST redirects would break).

Spec aliases (configuration-items/, configuration-item-types/,
drift-findings/, service-ci-links/) are registered alongside the original
router prefixes.
"""

from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from .views import (
    CMDBServiceProfileViewSet,
    ConfigurationBaselineViewSet,
    ConfigurationDriftFindingViewSet,
    ConfigurationItemHistoryViewSet,
    ConfigurationItemRelationshipViewSet,
    ConfigurationItemTicketLinkViewSet,
    ConfigurationItemChangeLinkViewSet,
    ConfigurationItemViewSet,
    ConfigurationItemTypeViewSet,
    DashboardView,
    ReportsView,
    ServiceConfigurationItemLinkViewSet,
    ServiceGraphView,
    ServiceImpactView,
    ServiceSPOFView,
    VerificationQueueView,
    VerificationVerifyView,
)

router = DefaultRouter()
router.register("types", ConfigurationItemTypeViewSet, basename="cmdb-type")
router.register(
    "configuration-item-types", ConfigurationItemTypeViewSet,
    basename="cmdb-type-alias",
)
router.register("items", ConfigurationItemViewSet, basename="cmdb-item")
router.register(
    "configuration-items", ConfigurationItemViewSet,
    basename="cmdb-item-alias",
)
router.register(
    "relationships", ConfigurationItemRelationshipViewSet,
    basename="cmdb-relationship",
)
router.register(
    "history", ConfigurationItemHistoryViewSet, basename="cmdb-history",
)
router.register(
    "baselines", ConfigurationBaselineViewSet, basename="cmdb-baseline",
)
router.register("drift", ConfigurationDriftFindingViewSet,
                basename="cmdb-drift")
router.register(
    "drift-findings", ConfigurationDriftFindingViewSet,
    basename="cmdb-drift-alias",
)
router.register(
    "service-profiles", CMDBServiceProfileViewSet,
    basename="cmdb-service-profile",
)
router.register(
    "service-links", ServiceConfigurationItemLinkViewSet,
    basename="cmdb-service-link",
)
router.register(
    "service-ci-links", ServiceConfigurationItemLinkViewSet,
    basename="cmdb-service-link-alias",
)
router.register(
    "ticket-links", ConfigurationItemTicketLinkViewSet,
    basename="cmdb-ticket-link",
)
router.register(
    "change-links", ConfigurationItemChangeLinkViewSet,
    basename="cmdb-change-link",
)


def _optional_slash_patterns(router_urls):
    """Duplicate router patterns so trailing slashes are optional.

    Registered after the canonical slashed patterns; entries carry no name
    so reverse() keeps resolving to the canonical route.
    """
    from django.urls import URLPattern, re_path

    extra = []
    for entry in router_urls:
        if not isinstance(entry, URLPattern):
            extra.append(entry)
            continue
        pattern = entry.pattern.regex.pattern
        if pattern.endswith("/$"):
            optional = pattern[:-2] + "/?$"
            extra.append(re_path(optional, entry.callback))
    return extra


router_urls = router.urls

urlpatterns = [
    # dashboard / reports
    path("dashboard/", DashboardView.as_view(), name="cmdb-dashboard"),
    path("dashboard", DashboardView.as_view()),
    path("reports/", ReportsView.as_view(), name="cmdb-reports"),
    path("reports", ReportsView.as_view()),
    path("reports/<str:kind>/", ReportsView.as_view(), name="cmdb-reports-kind"),
    path("reports/<str:kind>", ReportsView.as_view()),
    # verification
    path("verification/", VerificationQueueView.as_view(),
         name="cmdb-verification"),
    path("verification", VerificationQueueView.as_view()),
    path("verification/<int:pk>/verify/", VerificationVerifyView.as_view(),
         name="cmdb-verification-verify"),
    path("verification/<int:pk>/verify", VerificationVerifyView.as_view()),
    # service mapping
    path("services/<int:pk>/graph/", ServiceGraphView.as_view(),
         name="cmdb-service-graph"),
    path("services/<int:pk>/graph", ServiceGraphView.as_view()),
    path("services/<int:pk>/impact/", ServiceImpactView.as_view(),
         name="cmdb-service-impact"),
    path("services/<int:pk>/impact", ServiceImpactView.as_view()),
    path("services/<int:pk>/single-points-of-failure/",
         ServiceSPOFView.as_view(), name="cmdb-service-spof"),
    path("services/<int:pk>/single-points-of-failure",
         ServiceSPOFView.as_view()),
    # router (slashed canonical + optional-slash duplicates)
    path("", include(router_urls)),
    path("", include(_optional_slash_patterns(router_urls))),
]
