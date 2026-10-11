from django.urls import path
from rest_framework import routers

from tickets.views import (
    TicketAttachmentViewSet, TicketCategoryViewSet, TicketHistoryViewSet,
    TicketViewSet, category_report,
)

router = routers.DefaultRouter()
router.register("categories", TicketCategoryViewSet,
                basename="ticketcategory")
router.register("attachments", TicketAttachmentViewSet,
                basename="ticketattachment")
router.register("histories", TicketHistoryViewSet, basename="tickethistory")
router.register("", TicketViewSet, basename="ticket")

urlpatterns = router.urls + [
    path("reports/by-category/", category_report,
         name="ticket-category-report"),
]
