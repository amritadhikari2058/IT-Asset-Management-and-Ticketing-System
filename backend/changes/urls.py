"""URLs for the Change Management application.

Mounted at /api/changes/ by the project URL configuration (integration
pending - see backend/config/urls.py).
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
# Register named prefixes first so they are not shadowed by the empty-prefix
# ChangeRequestViewSet detail route (which would otherwise consume any slug).
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
router.register(r"scheduling-exceptions", views.ChangeSchedulingExceptionViewSet, basename="schedulingexception")
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
# Empty-prefix ChangeRequestViewSet registered last to avoid shadowing named routes.
router.register(r"", views.ChangeRequestViewSet, basename="change")

urlpatterns = [
    path("", include(router.urls)),
]
