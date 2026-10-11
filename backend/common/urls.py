from common.privacy_views import PrivacyErasureViewSet
from common.views import AuditLogViewSet, NotificationViewSet  # noqa
from rest_framework import routers

router = routers.DefaultRouter()
router.register("audit-logs", AuditLogViewSet, basename="auditlog")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("privacy-erasures", PrivacyErasureViewSet,
                basename="privacyerasure")

urlpatterns = router.urls
