"""URLs for the Change Management application.

Mounted at /api/changes/ by the project URL configuration (integration
pending - see backend/config/urls.py).
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"changes", views.ChangeRequestViewSet, basename="change")
router.register(r"templates", views.ChangeTemplateViewSet, basename="changetemplate")
router.register(r"tasks", views.ChangeTaskViewSet, basename="changetask")
router.register(r"assets", views.ChangeAssetImpactViewSet, basename="changeassetimpact")
router.register(r"services", views.ChangeServiceImpactViewSet, basename="changeserviceimpact")
router.register(r"dependencies", views.ChangeDependencyViewSet, basename="changedependency")
router.register(r"risk-assessments", views.ChangeRiskAssessmentViewSet, basename="changeriskassessment")
router.register(r"approvals", views.ChangeApprovalViewSet, basename="changeapproval")
router.register(r"review-meetings", views.ChangeReviewMeetingViewSet, basename="changereviewmeeting")
router.register(r"review-items", views.ChangeReviewItemViewSet, basename="changereviewitem")
router.register(r"maintenance-windows", views.MaintenanceWindowViewSet, basename="maintenancewindow")
router.register(r"conflicts", views.ChangeConflictViewSet, basename="changeconflict")
router.register(r"attachments", views.ChangeAttachmentViewSet, basename="changeattachment")
router.register(r"stakeholders", views.ChangeStakeholderViewSet, basename="changestakeholder")
router.register(r"communications", views.ChangeCommunicationViewSet, basename="changecommunication")
router.register(r"implementations", views.ChangeImplementationViewSet, basename="changeimplementation")
router.register(
    r"post-implementation-reviews",
    views.PostImplementationReviewViewSet,
    basename="postimplementationreview",
)
router.register(r"ticket-links", views.ChangeTicketLinkViewSet, basename="changeticketlink")
router.register(r"knowledge-links", views.ChangeKnowledgeLinkViewSet, basename="changeknowledgelink")
router.register(r"calendar", views.ChangeCalendarViewSet, basename="changecalendar")
router.register(r"outages", views.ChangeOutageViewSet, basename="changeoutage")
router.register(r"dashboard", views.ChangeDashboardViewSet, basename="changedashboard")
router.register(r"reports", views.ChangeReportsViewSet, basename="changereports")

urlpatterns = [
    path("", include(router.urls)),
]
