from django.urls import path
from rest_framework import routers

from tickets.views import (
    TicketAttachmentViewSet, TicketCategoryViewSet, TicketHistoryViewSet,
    TicketSLAViewSet, TicketViewSet, category_report, sla_report,
)

router = routers.DefaultRouter()
router.register("categories", TicketCategoryViewSet,
                basename="ticketcategory")
router.register("attachments", TicketAttachmentViewSet,
                basename="ticketattachment")
router.register("histories", TicketHistoryViewSet, basename="tickethistory")
router.register("sla", TicketSLAViewSet, basename="ticketsla")
router.register("", TicketViewSet, basename="ticket")

urlpatterns = router.urls + [
    path("reports/by-category/", category_report,
         name="ticket-category-report"),
    path("reports/sla/", sla_report, name="ticket-sla-report"),
]
