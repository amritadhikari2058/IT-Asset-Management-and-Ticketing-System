from django.urls import include, path

from common.monitoring_views import (ApiPerformanceViewSet,
                                     BackgroundTaskMonitorViewSet,
                                     EmailStorageHealthViewSet,
                                     HealthCheckResultViewSet,
                                     NotificationOutboxViewSet,
                                     OperationalAlertViewSet,
                                     OperationalErrorEventViewSet,
                                     OperationalIncidentViewSet,
                                     record_application_error,
                                     system_health)
from common.permissions import IsSystemAdmin, is_system_admin
from common.privacy_views import (DataRetentionExecutionViewSet,
                                  DataRetentionPolicyViewSet,
                                  PrivacyErasureViewSet)
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
router.register("retention-policies", DataRetentionPolicyViewSet,
                basename="retentionpolicy")
router.register("retention-executions", DataRetentionExecutionViewSet,
                basename="retentionexecution")
router.register("saved-reports", SavedReportViewSet, basename="savedreport")
router.register("scheduled-reports", ScheduledReportViewSet,
                basename="scheduledreport")
router.register("scheduled-report-runs", ScheduledReportRunViewSet,
                basename="scheduledreportrun")
router.register("notification-preferences", UserNotificationPreferenceViewSet,
                basename="usernotificationpreference")
router.register("health/results", HealthCheckResultViewSet,
                basename="healthresult")
router.register("tasks", BackgroundTaskMonitorViewSet, basename="taskmonitor")
router.register("errors", OperationalErrorEventViewSet,
                basename="operationalerror")
router.register("alerts", OperationalAlertViewSet, basename="operationalalert")
router.register("incidents", OperationalIncidentViewSet,
                basename="operationalincident")
router.register("api-performance", ApiPerformanceViewSet,
                basename="apiperformance")
router.register("email-storage", EmailStorageHealthViewSet,
                basename="emailstorage")
router.register("notification-outbox", NotificationOutboxViewSet,
                basename="notificationoutbox")

urlpatterns = [
    path("data-integrity/", data_integrity, name="data-integrity"),
    path("dashboard/", dashboard, name="dashboard"),
    path("health/", system_health, name="system-health"),
    path("record-error/", record_application_error, name="record-error"),
    path("reports/departments/", department_report, name="department-report"),
    path("exports/<str:dataset>/", export_dataset, name="export"),
    path("knowledge-base/", knowledge_base_search,
         name="knowledge-base-search"),
    path("operations/status/", operations_status,
         name="operations-status"),
    path("", include(router.urls)),
]
