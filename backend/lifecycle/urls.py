from django.urls import include, path
from rest_framework import routers

from lifecycle.views import (
    LifecycleAssetResolutionViewSet, LifecycleCaseViewSet,
    LifecycleDashboardView, LifecycleHistoryViewSet,
    LifecycleTaskEvidenceViewSet, LifecycleTaskViewSet,
    LifecycleTemplateItemViewSet, LifecycleTemplateViewSet,
)

router = routers.DefaultRouter()
router.register("templates", LifecycleTemplateViewSet, basename="lifecycle-template")
router.register("template-items", LifecycleTemplateItemViewSet, basename="lifecycle-template-item")
router.register("cases", LifecycleCaseViewSet, basename="lifecycle-case")
router.register("tasks", LifecycleTaskViewSet, basename="lifecycle-task")
router.register("asset-resolutions", LifecycleAssetResolutionViewSet, basename="lifecycle-asset-resolution")
router.register("attachments", LifecycleTaskEvidenceViewSet, basename="lifecycle-task-evidence")
router.register("history", LifecycleHistoryViewSet, basename="lifecycle-history")

urlpatterns = [
    path("", include(router.urls)),
    path("dashboard/", LifecycleDashboardView.as_view({"get": "list"}), name="lifecycle-dashboard"),
]
