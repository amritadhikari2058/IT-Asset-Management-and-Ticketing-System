from types import SimpleNamespace

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.renderers import JSONRenderer
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import Department, User
from accounts.tests import make_users
from accounts.serializers import UserSerializer
from accounts.views import UserViewSet


class UserListQueryTests(TestCase):
    def setUp(self):
        department, self.admin, self.manager, self.employee = make_users()
        self.department = department
        department_two = Department.objects.create(
            name="Performance Department 2", code="PERF2")
        department_three = Department.objects.create(
            name="Performance Department 3", code="PERF3")
        self.manager.home_department = department_two
        self.manager.save(update_fields=["home_department"])
        self.employee.home_department = department_three
        self.employee.save(update_fields=["home_department"])
        self.expected = {
            self.admin.employee_id: department.name,
            self.manager.employee_id: department_two.name,
            self.employee.employee_id: department_three.name,
        }

    def test_user_list_serialization_preserves_department_names(self):
        view = UserViewSet()
        view.request = SimpleNamespace(
            user=self.admin, query_params={})

        # The user rows include their single-valued department relationship.
        with self.assertNumQueries(1):
            data = UserSerializer(view.get_queryset(), many=True).data

        by_employee_id = {item["employee_id"]: item for item in data}
        self.assertEqual(len(by_employee_id), 3)
        for employee_id, department_name in self.expected.items():
            self.assertEqual(
                by_employee_id[employee_id]["home_department_name"],
                department_name)

    def test_user_list_api_has_flat_query_count(self):
        request = APIRequestFactory().get("/api/accounts/users/")
        force_authenticate(request, user=self.admin)
        endpoint = UserViewSet.as_view({"get": "list"})

        with self.assertNumQueries(2):
            response = endpoint(request)

        self.assertEqual(response.status_code, 200)
        body = JSONRenderer().render(response.data)
        self.assertGreater(len(body), 0)
        by_employee_id = {
            item["employee_id"]: item for item in response.data["results"]}
        for employee_id, department_name in self.expected.items():
            self.assertEqual(
                by_employee_id[employee_id]["home_department_name"],
                department_name)

    def test_paginated_query_count_does_not_grow_with_user_count(self):
        endpoint = UserViewSet.as_view({"get": "list"})

        def fetch_page():
            request = APIRequestFactory().get(
                "/api/accounts/users/?page=1")
            force_authenticate(request, user=self.admin)
            with CaptureQueriesContext(connection) as queries:
                response = endpoint(request)
            self.assertEqual(response.status_code, 200)
            return (len(queries), response.data["count"],
                    len(response.data["results"]))

        small_query_count, small_total, small_page_size = fetch_page()
        for index in range(40):
            User.objects.create_user(
                employee_id=f"PERF-{index:03d}",
                username=f"perf-{index:03d}",
                email=f"perf-{index:03d}@example.test",
                password="test-password",
                role="employee",
                home_department=self.department,
            )
        large_query_count, large_total, large_page_size = fetch_page()

        self.assertEqual(small_total, 3)
        self.assertEqual(large_total, 43)
        self.assertEqual(small_page_size, 3)
        self.assertEqual(large_page_size, 20)
        self.assertEqual(small_query_count, 2)
        self.assertEqual(large_query_count, small_query_count)
