"""Regression tests for PIR queryset scoping and per-change filtering.

``PostImplementationReview`` has no ``requester`` field. Visibility must be
inherited from the parent ``ChangeRequest`` (``change__requester``), matching
the scoping already used for child records such as ChangeImplementation. The
``change`` query parameter is applied only after that scope is enforced.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department, User
from changes.models import ChangeRequest, PostImplementationReview


PIR_LIST_URL = "/api/changes/post-implementation-reviews/"


class PIRQuerysetScopeTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="Engineering", code="ENGPIRSCOPE"
        )
        self.employee = self._make_user("scope_emp", "employee")
        self.other_employee = self._make_user("scope_other", "employee")
        self.it_support = self._make_user("scope_sup", "it_support")
        self.manager = self._make_user("scope_mgr", "it_manager")
        self.admin = self._make_user("scope_admin", "system_admin")
        self.superuser = self._make_user(
            "scope_root", "employee", is_superuser=True, is_staff=True
        )
        self.inactive_employee = self._make_user(
            "scope_inactive", "employee", is_active=False
        )

        self.own_change = self._make_change(self.employee, "PIRSCOPE-1")
        self.other_change = self._make_change(self.other_employee, "PIRSCOPE-2")
        self.own_pir = self._make_pir(self.own_change)
        self.other_pir = self._make_pir(self.other_change)

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

    def _make_change(self, requester, number, status="completed"):
        return ChangeRequest.objects.create(
            change_number=number,
            title=f"PIR scope change {number}",
            change_type="normal",
            category="application",
            priority="normal",
            status=status,
            risk_level="low",
            requester=requester,
            change_owner=requester,
            implementation_plan="Implementation plan",
            rollback_plan="Rollback plan",
            planned_start=timezone.now(),
            planned_end=timezone.now() + timedelta(hours=1),
        )

    def _make_pir(self, change, **extra):
        defaults = {
            "change": change,
            "status": "pending",
            "outcome": "successful",
            "objectives_met": "Objectives confirmed",
        }
        defaults.update(extra)
        return PostImplementationReview.objects.create(**defaults)

    def _authenticate(self, user):
        self.client.force_authenticate(user=user)

    def _detail_url(self, pir):
        return f"{PIR_LIST_URL}{pir.pk}/"

    @staticmethod
    def _results(response):
        data = response.data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data

    @staticmethod
    def _ids(rows):
        return [row["id"] for row in rows]

    def test_employee_can_list_and_retrieve_own_pir(self):
        self._authenticate(self.employee)

        list_response = self.client.get(PIR_LIST_URL)
        detail_response = self.client.get(self._detail_url(self.own_pir))

        self.assertEqual(list_response.status_code, 200, list_response.data)
        ids = self._ids(self._results(list_response))
        self.assertIn(self.own_pir.pk, ids)
        self.assertNotIn(self.other_pir.pk, ids)
        self.assertEqual(detail_response.status_code, 200, detail_response.data)
        self.assertEqual(detail_response.data["id"], self.own_pir.pk)
        self.assertEqual(detail_response.data["change"], self.own_change.pk)

    def test_employee_cannot_list_or_retrieve_another_employees_pir(self):
        self._authenticate(self.employee)

        list_response = self.client.get(PIR_LIST_URL)
        detail_response = self.client.get(self._detail_url(self.other_pir))

        self.assertEqual(list_response.status_code, 200, list_response.data)
        self.assertNotIn(self.other_pir.pk, self._ids(self._results(list_response)))
        self.assertEqual(detail_response.status_code, 404, detail_response.data)

    def test_it_staff_and_administrators_retain_full_pir_access(self):
        for user in (self.it_support, self.manager, self.admin, self.superuser):
            with self.subTest(user=user.username):
                self._authenticate(user)

                list_response = self.client.get(PIR_LIST_URL)
                detail_response = self.client.get(self._detail_url(self.other_pir))

                self.assertEqual(list_response.status_code, 200, list_response.data)
                ids = self._ids(self._results(list_response))
                self.assertIn(self.own_pir.pk, ids)
                self.assertIn(self.other_pir.pk, ids)
                self.assertEqual(detail_response.status_code, 200, detail_response.data)
                self.assertEqual(detail_response.data["id"], self.other_pir.pk)

    def test_inactive_user_is_denied(self):
        self._authenticate(self.inactive_employee)

        list_response = self.client.get(PIR_LIST_URL)
        detail_response = self.client.get(self._detail_url(self.own_pir))
        patch_response = self.client.patch(
            self._detail_url(self.own_pir),
            {"outcome": "failed"},
            format="json",
        )

        self.assertEqual(list_response.status_code, 403, list_response.data)
        self.assertEqual(detail_response.status_code, 403, detail_response.data)
        self.assertEqual(patch_response.status_code, 403, patch_response.data)

    def test_unauthenticated_access_is_denied(self):
        self._authenticate(None)

        list_response = self.client.get(PIR_LIST_URL)
        detail_response = self.client.get(self._detail_url(self.own_pir))

        self.assertIn(list_response.status_code, (401, 403))
        self.assertIn(detail_response.status_code, (401, 403))

    def test_change_filter_returns_only_the_matching_pir(self):
        self._authenticate(self.manager)

        filtered = self.client.get(PIR_LIST_URL, {"change": self.own_change.pk})
        unfiltered = self.client.get(PIR_LIST_URL)

        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual(filtered.data["count"], 1)
        self.assertEqual(
            self._ids(self._results(filtered)), [self.own_pir.pk]
        )
        self.assertEqual(unfiltered.status_code, 200, unfiltered.data)
        self.assertIn(
            self.other_pir.pk, self._ids(self._results(unfiltered))
        )

    def test_employee_change_filter_cannot_expose_another_employees_pir(self):
        self._authenticate(self.employee)

        blocked = self.client.get(PIR_LIST_URL, {"change": self.other_change.pk})
        allowed = self.client.get(PIR_LIST_URL, {"change": self.own_change.pk})

        self.assertEqual(blocked.status_code, 200, blocked.data)
        self.assertEqual(blocked.data["count"], 0)
        self.assertEqual(self._results(blocked), [])
        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.assertEqual(allowed.data["count"], 1)
        self.assertEqual(
            self._ids(self._results(allowed)), [self.own_pir.pk]
        )

    def test_change_filter_is_applied_before_pagination(self):
        # A PIR is unique per change. Create enough distinct changes to push a
        # target PIR onto page 2 of the default (PAGE_SIZE=20) listing, then
        # confirm the change filter still finds it.
        self._authenticate(self.employee)
        target_change = None
        target_pir = None
        for index in range(21):
            change = self._make_change(self.employee, f"PIRSCOPE-B{index}")
            target_change = change
            target_pir = self._make_pir(change)

        first_page = self.client.get(PIR_LIST_URL)
        second_page = self.client.get(PIR_LIST_URL, {"page": 2})
        filtered = self.client.get(PIR_LIST_URL, {"change": target_change.pk})

        self.assertEqual(first_page.status_code, 200, first_page.data)
        self.assertEqual(first_page.data["count"], 22)
        self.assertEqual(len(self._results(first_page)), 20)
        self.assertIsNotNone(first_page.data["next"])
        self.assertEqual(second_page.status_code, 200, second_page.data)
        self.assertEqual(len(self._results(second_page)), 2)

        all_listed = (
            self._ids(self._results(first_page))
            + self._ids(self._results(second_page))
        )
        self.assertEqual(len(set(all_listed)), 22)
        self.assertIn(target_pir.pk, all_listed)

        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual(filtered.data["count"], 1)
        self.assertEqual(self._ids(self._results(filtered)), [target_pir.pk])

    def test_invalid_change_filter_returns_empty_page(self):
        self._authenticate(self.manager)

        response = self.client.get(PIR_LIST_URL, {"change": "not-an-id"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(self._results(response), [])

    def test_manager_create_update_and_delete_still_work(self):
        self._authenticate(self.manager)
        create_change = self._make_change(self.other_employee, "PIRSCOPE-4")

        created = self.client.post(
            PIR_LIST_URL,
            {
                "change": create_change.pk,
                "outcome": "successful_with_issues",
                "objectives_met": "Reviewed with follow-up",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(
            PostImplementationReview.objects.filter(change=create_change).exists()
        )

        updated = self.client.patch(
            self._detail_url(self.own_pir),
            {"outcome": "failed"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.own_pir.refresh_from_db()
        self.assertEqual(self.own_pir.outcome, "failed")

        deleted = self.client.delete(self._detail_url(self.other_pir))
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertFalse(
            PostImplementationReview.objects.filter(pk=self.other_pir.pk).exists()
        )

    def test_employee_can_update_own_pir_but_not_another_employees_pir(self):
        self._authenticate(self.employee)

        allowed = self.client.patch(
            self._detail_url(self.own_pir),
            {"outcome": "inconclusive"},
            format="json",
        )
        blocked = self.client.patch(
            self._detail_url(self.other_pir),
            {"outcome": "inconclusive"},
            format="json",
        )

        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.own_pir.refresh_from_db()
        self.assertEqual(self.own_pir.outcome, "inconclusive")
        self.assertEqual(blocked.status_code, 404, blocked.data)
        self.other_pir.refresh_from_db()
        self.assertEqual(self.other_pir.outcome, "successful")
