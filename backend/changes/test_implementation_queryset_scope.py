"""Regression tests for ChangeImplementation queryset scoping.

``ChangeImplementation`` has no requester field. Employee visibility must be
inherited from the parent ``ChangeRequest`` (``change__requester``), matching
``ChangeRequestViewSet`` and the explicit child-record scoping already used by
``ChangeSchedulingExceptionViewSet``.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department, User
from changes.models import ChangeImplementation, ChangeRequest

LIST_URL = "/api/changes/implementations/"


class ChangeImplementationQuerysetScopeTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="Engineering", code="ENGIMPL"
        )
        self.employee = self._make_user("impl_emp", "employee")
        self.other_employee = self._make_user("impl_other", "employee")
        self.it_support = self._make_user("impl_sup", "it_support")
        self.it_manager = self._make_user("impl_mgr", "it_manager")
        self.admin = self._make_user("impl_admin", "system_admin")
        self.superuser = self._make_user(
            "impl_root", "employee", is_superuser=True, is_staff=True
        )
        self.inactive_employee = self._make_user(
            "impl_inactive", "employee", is_active=False
        )

        self.own_change = self._make_change(self.employee, "IMP-1")
        self.other_change = self._make_change(self.other_employee, "IMP-2")
        self.inactive_change = self._make_change(self.inactive_employee, "IMP-3")

        self.own_implementation = self._make_implementation(self.own_change)
        self.other_implementation = self._make_implementation(self.other_change)
        self.inactive_implementation = self._make_implementation(
            self.inactive_change
        )

        self.client = APIClient()

    def _make_user(self, prefix, role, **extra):
        defaults = {
            "username": f"{prefix}@example.test",
            "email": f"{prefix}@example.test",
            "employee_id": prefix.upper(),
            "password": "pw12345678",
            "role": role,
            "home_department": self.department,
        }
        defaults.update(extra)
        return User.objects.create_user(**defaults)

    def _make_change(self, requester, number, status="in_progress"):
        return ChangeRequest.objects.create(
            change_number=number,
            title=f"Implementation change {number}",
            change_type="normal",
            category="application",
            priority="normal",
            status=status,
            requester=requester,
            change_owner=requester,
            implementation_plan="Implementation plan",
            rollback_plan="Rollback plan",
            planned_start=timezone.now(),
            planned_end=timezone.now() + timedelta(hours=1),
        )

    def _make_implementation(self, change, **extra):
        defaults = {
            "change": change,
            "status": "in_progress",
            "implementation_notes": "Implementation in progress",
            "validation_result": "Pending",
        }
        defaults.update(extra)
        return ChangeImplementation.objects.create(**defaults)

    def _authenticate(self, user):
        self.client.force_authenticate(user=user)

    def _detail_url(self, implementation):
        return f"{LIST_URL}{implementation.pk}/"

    @staticmethod
    def _results(response):
        data = response.data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data

    def _assert_only_own_implementation_listed(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in self._results(response)]
        self.assertIn(self.own_implementation.pk, ids)
        self.assertNotIn(self.other_implementation.pk, ids)
        self.assertNotIn(self.inactive_implementation.pk, ids)

    def test_employee_can_list_only_own_implementation_records(self):
        self._authenticate(self.employee)

        response = self.client.get(LIST_URL)

        self._assert_only_own_implementation_listed(response)

    def test_employee_can_retrieve_own_implementation_record(self):
        self._authenticate(self.employee)

        response = self.client.get(
            self._detail_url(self.own_implementation)
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["id"], self.own_implementation.pk)
        self.assertEqual(response.data["change"], self.own_change.pk)

    def test_employee_cannot_retrieve_restricted_implementation_record(self):
        self._authenticate(self.employee)

        response = self.client.get(
            self._detail_url(self.other_implementation)
        )

        self.assertEqual(response.status_code, 404, response.data)

    def test_employee_can_update_own_implementation_record(self):
        self._authenticate(self.employee)

        response = self.client.patch(
            self._detail_url(self.own_implementation),
            {
                "status": "succeeded",
                "outcome": "successful",
                "validation_result": "Checks passed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.own_implementation.refresh_from_db()
        self.assertEqual(self.own_implementation.status, "succeeded")
        self.assertEqual(self.own_implementation.outcome, "successful")
        self.assertEqual(self.own_implementation.validation_result, "Checks passed")

    def test_employee_cannot_update_or_delete_restricted_implementation(self):
        self._authenticate(self.employee)
        url = self._detail_url(self.other_implementation)

        patch_response = self.client.patch(
            url,
            {"status": "succeeded", "implementation_notes": "Should not work"},
            format="json",
        )
        delete_response = self.client.delete(url)

        self.assertEqual(patch_response.status_code, 404, patch_response.data)
        self.assertEqual(delete_response.status_code, 404, delete_response.data)
        self.other_implementation.refresh_from_db()
        self.assertEqual(self.other_implementation.status, "in_progress")
        self.assertEqual(
            self.other_implementation.implementation_notes,
            "Implementation in progress",
        )

    def test_it_staff_can_access_all_implementation_records(self):
        for user in (self.it_support, self.it_manager):
            with self.subTest(role=user.role):
                self._authenticate(user)

                list_response = self.client.get(LIST_URL)
                detail_response = self.client.get(
                    self._detail_url(self.other_implementation)
                )

                self.assertEqual(list_response.status_code, 200, list_response.data)
                ids = [row["id"] for row in self._results(list_response)]
                self.assertIn(self.own_implementation.pk, ids)
                self.assertIn(self.other_implementation.pk, ids)
                self.assertIn(self.inactive_implementation.pk, ids)
                self.assertEqual(detail_response.status_code, 200, detail_response.data)
                self.assertEqual(
                    detail_response.data["id"], self.other_implementation.pk
                )

    def test_administrators_can_access_restricted_implementation_record(self):
        for user in (self.admin, self.superuser):
            with self.subTest(user=user.username):
                self._authenticate(user)

                response = self.client.get(
                    self._detail_url(self.other_implementation)
                )

                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(
                    response.data["id"], self.other_implementation.pk
                )

    def test_unauthenticated_access_is_denied(self):
        list_response = self.client.get(LIST_URL)
        detail_response = self.client.get(
            self._detail_url(self.own_implementation)
        )

        self.assertIn(list_response.status_code, (401, 403))
        self.assertIn(detail_response.status_code, (401, 403))

    def test_inactive_user_access_is_denied(self):
        self._authenticate(self.inactive_employee)

        list_response = self.client.get(LIST_URL)
        detail_response = self.client.get(
            self._detail_url(self.inactive_implementation)
        )

        self.assertEqual(list_response.status_code, 403, list_response.data)
        self.assertEqual(detail_response.status_code, 403, detail_response.data)
