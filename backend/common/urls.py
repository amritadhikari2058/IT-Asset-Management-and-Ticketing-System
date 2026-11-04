from django.urls import include, path

from common.privacy_views import PrivacyErasureViewSet
from common.views import (AuditLogViewSet, NotificationViewSet,  # noqa: F401
                          SavedReportViewSet, ScheduledReportViewSet,
                          ScheduledReportRunViewSet,
                          UserNotificationPreferenceViewSet,
                          dashboard, data_integrity, department_report,
                          export_dataset, knowledge_base_search,
                          operations_status)

from rest_framework import routers

router = routers.DefaultRouter()
router.register("audit-logs", AuditLogViewSet, basename="auditlog")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("privacy-erasures", PrivacyErasureViewSet,
                basename="privacyerasure")
router.register("saved-reports", SavedReportViewSet, basename="savedreport")
router.register("scheduled-reports", ScheduledReportViewSet,
                basename="scheduledreport")
router.register("scheduled-report-runs", ScheduledReportRunViewSet,
                basename="scheduledreportrun")
router.register("notification-preferences", UserNotificationPreferenceViewSet,
                basename="usernotificationpreference")

urlpatterns = [
    path("data-integrity/", data_integrity, name="data-integrity"),
    path("dashboard/", dashboard, name="dashboard"),
    path("reports/departments/", department_report, name="department-report"),
    path("exports/<str:dataset>/", export_dataset, name="export"),
    path("knowledge-base/", knowledge_base_search,
         name="knowledge-base-search"),
    path("operations/status/", operations_status,
         name="operations-status"),
    path("", include(router.urls)),
]
