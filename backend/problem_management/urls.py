"""PM1 + Gate 2 URL routing.

Gate 1 routes are unchanged. Gate 2 adds governed router resources plus nested
Problem collections and explicit transition endpoints. Evidence unarchive has
no route at all (unsupported by design). Canonical trailing-slash routes are
kept, with the existing optional-slash aliases derived from the router.
"""
from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from . import views
from .gate2_collections import (
    ActionCollection, ExceptionCollection, FactorCollection, ValidationCollection,
    WorkaroundCollection, WhyCollection,
)
from .gate2_endpoints import (
    ActionViewSet, EvidenceViewSet, ExceptionViewSet, RootCauseAnalysisViewSet,
    TimelineViewSet, ValidationViewSet, WorkaroundViewSet,
)
from .gate2_transitions import TransitionView
from .gate2_views import (
    EvidenceCollection, LinkedAssetsView, LinkedCIsView, LinkedProductsView,
    LinkedServicesView, LinkedTicketsView, ProblemReadinessView,
    ProblemRootCauseAnalysisView, ProblemTaskCollection, TimelineCollection,
)
from .gate2_whys import FactorViewSet, WhyViewSet

router = DefaultRouter()
router.register(r"problems", views.ProblemViewSet, basename="problem")
router.register(
    r"ticket-links", views.ProblemTicketLinkViewSet,
    basename="problem-ticket-link",
)
router.register(
    r"ci-links", views.ProblemConfigurationItemLinkViewSet,
    basename="problem-ci-link",
)
router.register(
    r"service-links", views.ProblemServiceLinkViewSet,
    basename="problem-service-link",
)
router.register(
    r"asset-links", views.ProblemAssetLinkViewSet,
    basename="problem-asset-link",
)
router.register(
    r"software-links", views.ProblemSoftwareProductLinkViewSet,
    basename="problem-software-link",
)
router.register(r"tasks", views.ProblemTaskViewSet, basename="problem-task")
router.register(r"history", views.ProblemHistoryViewSet, basename="problem-history")

# Gate 2 resources (list/retrieve/create/PATCH; lifecycle via transitions).
router.register(
    r"root-cause-analyses", RootCauseAnalysisViewSet,
    basename="root-cause-analysis",
)
router.register(r"root-cause-whys", WhyViewSet, basename="root-cause-why")
router.register(r"root-cause-factors", FactorViewSet, basename="root-cause-factor")
router.register(r"timeline", TimelineViewSet, basename="problem-timeline-event")
router.register(r"evidence", EvidenceViewSet, basename="problem-evidence")
router.register(r"actions", ActionViewSet, basename="problem-action")
router.register(r"workarounds", WorkaroundViewSet, basename="problem-workaround")
router.register(r"validations", ValidationViewSet, basename="problem-validation")
router.register(r"exceptions", ExceptionViewSet, basename="problem-exception")

nested = [
    ("root-cause-analysis", ProblemRootCauseAnalysisView, "problem-rca"),
    ("five-whys", WhyCollection, "problem-why"),
    ("root-cause-factors", FactorCollection, "problem-factor"),
    ("evidence", EvidenceCollection, "problem-evidence-collection"),
    ("timeline", TimelineCollection, "problem-timeline"),
    ("actions", ActionCollection, "problem-action-collection"),
    ("tasks", ProblemTaskCollection, "problem-task-collection"),
    ("workarounds", WorkaroundCollection, "problem-workaround-collection"),
    ("validations", ValidationCollection, "problem-validation-collection"),
    ("exceptions", ExceptionCollection, "problem-exception-collection"),
    ("readiness", ProblemReadinessView, "problem-readiness"),
    ("linked-tickets", LinkedTicketsView, "problem-linked-tickets"),
    ("linked-cis", LinkedCIsView, "problem-linked-cis"),
    ("linked-assets", LinkedAssetsView, "problem-linked-assets"),
    ("linked-services", LinkedServicesView, "problem-linked-services"),
    ("linked-products", LinkedProductsView, "problem-linked-products"),
]

TRANSITION_RE = (
    r"^(?P<resource>root-cause-analyses|evidence|actions|workarounds|validations|"
    r"exceptions)/(?P<pk>\d+)/(?P<transition>[a-z_-]+)/$"
)

gate2_urlpatterns = [
    re_path(TRANSITION_RE, TransitionView.as_view(), name="problem-transition"),
] + [
    path(f"problems/<int:problem_id>/{slug}/", view.as_view(), name=name)
    for slug, view, name in nested
]


def _optional_slash_patterns():
    """Non-canonical no-trailing-slash aliases (name=None; pk group kept
    mandatory so list/detail never collide)."""
    patterns = []
    for url in router.urls:
        raw = str(getattr(url, "pattern", "") or "")
        if not raw or not raw.endswith("/"):
            continue
        patterns.append(
            re_path(r"^" + raw[:-1] + "/?", url.callback, name=None),
        )
    return patterns


urlpatterns = [
    *gate2_urlpatterns,
    path("", include(router.urls)),
    *_optional_slash_patterns(),
]
