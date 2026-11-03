from django.urls import path
from rest_framework import routers

from tickets.views import (
    AutomationRuleViewSet, TicketApprovalViewSet, TicketAttachmentViewSet,
    TicketCategoryViewSet, TicketHistoryViewSet, TicketKbArticleViewSet,
    TicketSLAViewSet, TicketViewSet, WorkflowExecutionViewSet,
    category_report, sla_report,
)

router = routers.DefaultRouter()
router.register("categories", TicketCategoryViewSet,
                basename="ticketcategory")
router.register("attachments", TicketAttachmentViewSet,
                basename="ticketattachment")
router.register("histories", TicketHistoryViewSet, basename="tickethistory")
router.register("sla", TicketSLAViewSet, basename="ticketsla")
router.register("kb-articles", TicketKbArticleViewSet,
                basename="ticketkbarticle")
router.register("automation-rules", AutomationRuleViewSet,
                basename="automationrule")
router.register("approvals", TicketApprovalViewSet, basename="ticketapproval")
router.register("workflow-executions", WorkflowExecutionViewSet,
                basename="workflowexecution")
router.register("", TicketViewSet, basename="ticket")

urlpatterns = router.urls + [
    path("reports/by-category/", category_report,
         name="ticket-category-report"),
    path("reports/sla/", sla_report, name="ticket-sla-report"),
]
