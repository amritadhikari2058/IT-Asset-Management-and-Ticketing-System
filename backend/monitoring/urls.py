"""Monitoring API URL patterns."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views
from .dashboard_views import MonitoringDashboardView
from .policy_views import MonitoringAutomationPolicyViewSet
from .alert_subresource_views import AlertEventsViewSet, AlertHistoryViewSet, AlertTicketViewSet

router = DefaultRouter()
router.register(
    "automation-policies",
    MonitoringAutomationPolicyViewSet,
    basename="monitoring-automation-policy",
)

urlpatterns = [
    # Source management
    path("sources/", views.MonitoringSourceViewSet.as_view({"get": "list", "post": "create"})),
    path("sources/<int:pk>/", views.MonitoringSourceViewSet.as_view({"get": "retrieve", "patch": "partial_update"})),
    path("sources/<int:pk>/rotate-secret/", views.MonitoringSourceViewSet.as_view({"post": "rotate_secret"})),
    path("sources/<int:pk>/disable/", views.MonitoringSourceViewSet.as_view({"post": "disable"})),
    path("sources/<int:pk>/enable/", views.MonitoringSourceViewSet.as_view({"post": "enable"})),
    path("sources/<int:pk>/test/", views.MonitoringSourceViewSet.as_view({"post": "test"})),
    # Alert list (collection endpoint - required by frontend)
    path("alerts/", views.MonitoringAlertViewSet.as_view({"get": "list"})),
    path("alerts/<int:pk>/", views.MonitoringAlertViewSet.as_view({"get": "retrieve"})),
    # Alert actions
    path("alerts/<int:pk>/acknowledge/", views.MonitoringAlertViewSet.as_view({"post": "acknowledge"})),
    path("alerts/<int:pk>/assign/", views.MonitoringAlertViewSet.as_view({"post": "assign"})),
    path("alerts/<int:pk>/suppress/", views.MonitoringAlertViewSet.as_view({"post": "suppress"})),
    path("alerts/<int:pk>/unsuppress/", views.MonitoringAlertViewSet.as_view({"post": "unsuppress"})),
    path("alerts/<int:pk>/resolve/", views.MonitoringAlertViewSet.as_view({"post": "resolve"})),
    path("alerts/<int:pk>/close/", views.MonitoringAlertViewSet.as_view({"post": "close"})),
    path("alerts/<int:pk>/reopen/", views.MonitoringAlertViewSet.as_view({"post": "reopen"})),
    # Alert subresources
    path("alerts/<int:pk>/events/", AlertEventsViewSet.as_view({"get": "list"})),
    path("alerts/<int:pk>/history/", AlertHistoryViewSet.as_view({"get": "list"})),
    path("alerts/<int:pk>/ticket/", AlertTicketViewSet.as_view({"get": "retrieve"})),
    
    # Dashboard and reports
    path("dashboard/", MonitoringDashboardView.as_view()),
    path("reports/alert-volume/", views.ReportViewSet.as_view({"get": "alert_volume"})),
    path("reports/acknowledgement-time/", views.ReportViewSet.as_view({"get": "acknowledgement_time"})),
    path("reports/recovery-time/", views.ReportViewSet.as_view({"get": "recovery_time"})),
    path("reports/ticket-creation/", views.ReportViewSet.as_view({"get": "ticket_creation"})),
    path("reports/noise/", views.ReportViewSet.as_view({"get": "noise"})),
    path("reports/flapping/", views.ReportViewSet.as_view({"get": "flapping"})),
    path("reports/suppression/", views.ReportViewSet.as_view({"get": "suppression"})),
    path("reports/source-health/", views.ReportViewSet.as_view({"get": "source_health"})),
    path("reports/target-coverage/", views.ReportViewSet.as_view({"get": "target_coverage"})),
    path("reports/unmapped-targets/", views.ReportViewSet.as_view({"get": "target_coverage"})),
    
    # Ingestion endpoints
    path("ingest/<str:source_code>/", views.MonitoringIngestionView.as_view()),
    path("ingest/<str:source_code>/batch/", views.MonitoringIngestionView.as_view()),
    path("manual-events/", views.manual_event),
]

urlpatterns += router.urls
