"""PM1 URL routing.

Canonical trailing-slash routes plus optional-slash aliases (name=None) so
future frontend clients may call either ``/api/problems/tasks/`` or
``/api/problems/tasks``. Reverse() always resolves to the canonical slash
form. Views are wired to services — no status PATCH routes exist.
"""
from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from . import views

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
    path("", include(router.urls)),
    *_optional_slash_patterns(),
]
