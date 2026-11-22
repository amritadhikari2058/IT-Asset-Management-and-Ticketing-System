from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework.renderers import JSONRenderer
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.tests import make_users
from services.models import ServiceCatalogueItem, ServiceRequest
from tickets.models import Ticket, TicketCategory
from tickets.serializers import TicketSerializer
from tickets.views import TicketViewSet


class TicketServiceRequestQueryTests(TestCase):
    def setUp(self):
        self.department, _, _, self.requester = make_users()
        category = TicketCategory.objects.create(name="Service request query")
        self.expected = []

        for index in range(3):
            ticket = Ticket.objects.create(
                title=f"Linked ticket {index}",
                description="Query-count fixture",
                category=category,
                requester=self.requester,
                department=self.department,
            )
            item = ServiceCatalogueItem.objects.create(
                name=f"Service item {index}")
            service_request = ServiceRequest.objects.create(
                request_number=f"SR-PERF-{index}",
                requester=self.requester,
                department=self.department,
                catalogue_item=item,
                fulfilment_ticket=ticket,
            )
            self.expected.append((ticket.title, service_request, item.name))

    def test_ticket_list_serialization_preserves_linked_request_data(self):
        view = TicketViewSet()
        view.request = SimpleNamespace(
            user=self.requester, query_params={})

        # Ticket rows plus one bounded prefetch for their linked requests.
        with self.assertNumQueries(2):
            data = TicketSerializer(view.get_queryset(), many=True).data

        self.assertEqual(len(data), 3)
        by_title = {item["title"]: item for item in data}
        for title, service_request, item_name in self.expected:
            linked = by_title[title]["source_service_request"]
            self.assertEqual(linked["id"], service_request.pk)
            self.assertEqual(linked["request_number"],
                             service_request.request_number)
            self.assertEqual(linked["catalogue_item_name"], item_name)
            self.assertEqual(linked["status"], service_request.status)
            self.assertEqual(
                linked["url"],
                f"/api/services/requests/{service_request.pk}/")

    def test_ticket_list_api_has_flat_query_count(self):
        request = APIRequestFactory().get("/api/tickets/")
        force_authenticate(request, user=self.requester)
        endpoint = TicketViewSet.as_view({"get": "list"})

        with self.assertNumQueries(3):
            response = endpoint(request)

        self.assertEqual(response.status_code, 200)
        body = JSONRenderer().render(response.data)
        self.assertGreater(len(body), 0)
        self.assertEqual(len(response.data["results"]), 3)
        linked = response.data["results"][0]["source_service_request"]
        self.assertTrue(linked["url"].endswith(
            f"/api/services/requests/{linked['id']}/"))

    def test_prefetch_selects_newest_active_request_only(self):
        title, original, _ = self.expected[0]
        ServiceRequest.objects.filter(pk=original.pk).update(
            submitted_at=timezone.now() - timedelta(days=1))
        newer = ServiceRequest.objects.create(
            request_number="SR-PERF-NEW",
            requester=self.requester,
            department=self.department,
            catalogue_item=original.catalogue_item,
            fulfilment_ticket=original.fulfilment_ticket,
        )
        ServiceRequest.objects.create(
            request_number="SR-PERF-DELETED",
            requester=self.requester,
            department=self.department,
            catalogue_item=original.catalogue_item,
            fulfilment_ticket=original.fulfilment_ticket,
            is_deleted=True,
        )

        view = TicketViewSet()
        view.request = SimpleNamespace(
            user=self.requester, query_params={})
        queryset = view.get_queryset().filter(title=title)
        with self.assertNumQueries(2):
            data = TicketSerializer(queryset, many=True).data

        self.assertEqual(data[0]["source_service_request"]["id"], newer.pk)
        self.assertEqual(
            data[0]["source_service_request"]["request_number"],
            newer.request_number)
