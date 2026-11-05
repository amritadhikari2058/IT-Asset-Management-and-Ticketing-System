from django.urls import path
from rest_framework import routers

from tickets.views import (
    TicketAttachmentViewSet, TicketCategoryViewSet, TicketHistoryViewSet,
    TicketKbArticleViewSet, TicketSLAViewSet, TicketViewSet,
    category_report, sla_report,
)
from tickets.advanced_views import (
    TicketQueueViewSet, TicketQueueMembershipViewSet,
    CannedResponseViewSet, TicketTemplateViewSet,
    TicketResolutionCodeViewSet, SavedTicketViewViewSet,
    TicketMergeRecordViewSet,
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
router.register("queues", TicketQueueViewSet, basename="ticketqueue")
router.register("queue-memberships", TicketQueueMembershipViewSet,
                basename="ticketqueuemembership")
router.register("canned-responses", CannedResponseViewSet,
                basename="cannedresponse")
router.register("templates", TicketTemplateViewSet, basename="tickettemplate")
router.register("resolution-codes", TicketResolutionCodeViewSet,
                basename="ticketresolutioncode")
router.register("saved-views", SavedTicketViewViewSet,
                basename="savedticketview")
router.register("merge-records", TicketMergeRecordViewSet,
                basename="ticketmergerecord")
router.register("", TicketViewSet, basename="ticket")

urlpatterns = router.urls + [
    path("reports/by-category/", category_report,
         name="ticket-category-report"),
    path("reports/sla/", sla_report, name="ticket-sla-report"),
]
