from django.urls import include, path

from common.privacy_views import PrivacyErasureViewSet
from common.views import (AuditLogViewSet, NotificationViewSet,  # noqa: F401
                          data_integrity, export_dataset)

from rest_framework import routers

router = routers.DefaultRouter()
router.register("audit-logs", AuditLogViewSet, basename="auditlog")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("privacy-erasures", PrivacyErasureViewSet,
                basename="privacyerasure")

urlpatterns = [
    path("data-integrity/", data_integrity, name="data-integrity"),
    path("exports/<str:dataset>/", export_dataset, name="export"),
    path("", include(router.urls)),
]
