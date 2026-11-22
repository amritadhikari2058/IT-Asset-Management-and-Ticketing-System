from types import SimpleNamespace

from django.test import TestCase

from accounts.tests import make_users
from services.models import (
    ServiceCatalogueItem, ServiceRequest, ServiceRequestAttachment,
    ServiceRequestComment, ServiceRequestHistory,
)
from services.serializers import ServiceRequestSerializer
from services.views import ServiceRequestViewSet


class ServiceRequestListQueryTests(TestCase):
    def setUp(self):
        self.department, _, self.manager, self.employee = make_users()
        item = ServiceCatalogueItem.objects.create(name="VPN access")
        self.requests = []

        for index in range(3):
            service_request = ServiceRequest.objects.create(
                request_number=f"SR-LIST-PERF-{index}",
                requester=self.employee,
                department=self.department,
                catalogue_item=item,
                assigned_to=self.manager,
            )
            for comment_index in range(2):
                ServiceRequestComment.objects.create(
                    request=service_request,
                    author=self.employee if comment_index == 0 else self.manager,
                    body=f"Comment {comment_index}",
                    is_internal=comment_index == 1,
                )
            for history_index in range(2):
                ServiceRequestHistory.objects.create(
                    request=service_request,
                    actor=self.manager,
                    event=f"event_{history_index}",
                )
            ServiceRequestAttachment.objects.create(
                request=service_request,
                uploaded_by=self.manager,
            )
            self.requests.append(service_request)

    def _serialize(self):
        view = ServiceRequestViewSet()
        view.request = SimpleNamespace(user=self.manager)
        context = {"request": SimpleNamespace(user=self.manager)}
        return ServiceRequestSerializer(
            view.get_queryset(), many=True, context=context).data

    def test_list_response_preserves_nested_data(self):
        # One request query and one prefetch for each nested collection.
        with self.assertNumQueries(4):
            data = self._serialize()

        self.assertEqual(len(data), 3)
        for row in data:
            self.assertEqual(row["catalogue_item_name"], "VPN access")
            self.assertEqual(row["requester_name"], self.employee.email)
            self.assertEqual(row["assigned_to_name"], self.manager.email)
            self.assertEqual(len(row["comments"]), 2)
            self.assertEqual(len(row["history"]), 2)
            self.assertEqual(len(row["attachments"]), 1)

    def test_employee_comment_filter_is_preserved_with_prefetch(self):
        employee_view = ServiceRequestViewSet()
        employee_view.request = SimpleNamespace(user=self.employee)
        context = {"request": SimpleNamespace(user=self.employee)}

        with self.assertNumQueries(4):
            data = ServiceRequestSerializer(
                employee_view.get_queryset(), many=True,
                context=context).data

        self.assertEqual(len(data), 3)
        for row in data:
            self.assertEqual(len(row["comments"]), 1)
            self.assertFalse(row["comments"][0]["is_internal"])

    def test_list_query_count_stays_flat_for_5_25_and_100_requests(self):
        item = self.requests[0].catalogue_item
        extra_requests = ServiceRequest.objects.bulk_create([
            ServiceRequest(
                request_number=f"SR-LIST-LARGE-{index:03d}",
                requester=self.employee,
                department=self.department,
                catalogue_item=item,
                assigned_to=self.manager,
            )
            for index in range(3, 100)
        ])
        ServiceRequestComment.objects.bulk_create([
            ServiceRequestComment(
                request=service_request,
                author=self.employee if comment_index == 0 else self.manager,
                body=f"Large comment {comment_index}",
                is_internal=comment_index == 1,
            )
            for service_request in extra_requests
            for comment_index in range(2)
        ])
        ServiceRequestHistory.objects.bulk_create([
            ServiceRequestHistory(
                request=service_request, actor=self.manager,
                event=f"large_event_{history_index}",
            )
            for service_request in extra_requests
            for history_index in range(2)
        ])
        ServiceRequestAttachment.objects.bulk_create([
            ServiceRequestAttachment(
                request=service_request, uploaded_by=self.manager,
            )
            for service_request in extra_requests
        ])

        view = ServiceRequestViewSet()
        view.request = SimpleNamespace(user=self.manager)
        context = {"request": SimpleNamespace(user=self.manager)}
        for size in (5, 25, 100):
            queryset = view.get_queryset().order_by("id")[:size]
            with self.subTest(size=size):
                with self.assertNumQueries(4):
                    data = ServiceRequestSerializer(
                        queryset, many=True, context=context).data
                self.assertEqual(len(data), size)
