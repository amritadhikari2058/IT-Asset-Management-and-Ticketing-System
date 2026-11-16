"""Rewrite urls.py with correct syntax."""
content = '''"""Monitoring API URL patterns."""

from django.urls import path
from . import views

urlpatterns = [
    # Source management
    path("sources/", views.MonitoringSourceViewSet.as_view({"get": "list"})),
    path("sources/<int:pk>/", views.MonitoringSourceViewSet.as_view({"get": "retrieve"})),
    path("sources/<int:pk>/rotate-secret/", views.MonitoringSourceViewSet.as_view({"post": "rotate_secret"})),
    path("sources/<int:pk>/disable/", views.MonitoringSourceViewSet.as_view({"post": "disable"})),
    path("sources/<int:pk>/enable/", views.MonitoringSourceViewSet.as_view({"post": "enable"})),
    path("sources/<int:pk>/test/", views.MonitoringSourceViewSet.as_view({"post": "test"})),
    
    # Alert actions
    path("alerts/<int:pk>/", views.MonitoringAlertViewSet.as_view({"get": "retrieve"})),
    path("alerts/<int:pk>/acknowledge/", views.MonitoringAlertViewSet.as_view({"post": "acknowledge"})),
    path("alerts/<int:pk>/assign/", views.MonitoringAlertViewSet.as_view({"post": "assign"})),
    path("alerts/<int:pk>/suppress/", views.MonitoringAlertViewSet.as_view({"post": "suppress"})),
    path("alerts/<int:pk>/unsuppress/", views.MonitoringAlertViewSet.as_view({"post": "unsuppress"})),
    path("alerts/<int:pk>/resolve/", views.MonitoringAlertViewSet.as_view({"post": "resolve"})),
    path("alerts/<int:pk>/close/", views.MonitoringAlertViewSet.as_view({"post": "close"})),
    path("alerts/<int:pk>/reopen/", views.MonitoringAlertViewSet.as_view({"post": "reopen"})),
    path("alerts/<int:pk>/create-ticket/", views.MonitoringAlertViewSet.as_view({"post": "create_ticket"})),
    path("alerts/<int:pk>/update-ticket/", views.MonitoringAlertViewSet.as_view({"post": "update_ticket"})),
    path("alerts/<int:pk>/events/", views.MonitoringAlertViewSet.as_view({"get": "events"})),
    path("alerts/<int:pk>/history/", views.MonitoringAlertViewSet.as_view({"get": "history"})),
    path("alerts/<int:pk>/impact/", views.MonitoringAlertViewSet.as_view({"get": "impact"})),
    path("alerts/<int:pk>/ticket/", views.MonitoringAlertViewSet.as_view({"get": "ticket"})),
    
    # Dashboard and reports
    path("dashboard/", views.DashboardViewSet.as_view({"get": "list"})),
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
    path("ingest/<str:source_code>/", views.ingest_event),
    path("ingest/<str:source_code>/batch/", views.ingest_batch_events),
    path("manual-events/", views.manual_event),
]
'''

with open('backend/monitoring/urls.py', 'w') as f:
    f.write(content)
print('urls.py rewritten')