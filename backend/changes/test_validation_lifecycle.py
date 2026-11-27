"""Regression tests for the Change Management validation lifecycle.

The intended sequence is::

    in_progress -> begin_validation -> validation -> complete -> completed

The complete action historically only accepted ``in_progress``, which left a
validated change with no completion path. These tests exercise the API
contract used by the frontend as well as the shared service functions.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from changes.models import ChangeApproval, ChangeHistory, ChangeRequest
from changes.services import (
    _generate_change_number,
    complete_rollback,
    fail_implementation,
    start_rollback,
)


class ChangeValidationLifecycleTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Engineering", code="ENGVL")
        self.requester = self._make_user("vl_req", "employee")
        self.manager = self._make_user("vl_mgr", "it_manager")
        self.change = self._make_change(status="in_progress")
        self.client = APIClient()
        self._authenticate(self.manager)

    def _make_user(self, prefix, role):
        return User.objects.create_user(
            username=f"{prefix}@example.test",
            email=f"{prefix}@example.test",
            employee_id=prefix.upper(),
            password="pw12345678",
            role=role,
            home_department=self.department,
        )

    def _make_change(self, status, **extra):
        defaults = {
            "change_number": _generate_change_number(),
            "title": "Deploy release",
            "change_type": "normal",
            "category": "application",
            "priority": "normal",
            "status": status,
            "requester": self.requester,
            "change_owner": self.requester,
            "implementation_plan": "Implementation plan",
            "rollback_plan": "Rollback plan",
            "planned_start": timezone.now(),
            "planned_end": timezone.now() + timedelta(hours=1),
            "actual_start": timezone.now() if status == "in_progress" else None,
        }
        defaults.update(extra)
        return ChangeRequest.objects.create(**defaults)

    def _authenticate(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _post(self, action, payload=None):
        return self.client.post(
            f"/api/changes/{self.change.pk}/{action}/",
            payload or {},
            format="json",
        )

    def _set_status(self, status):
        self.change.status = status
        self.change.save(update_fields=["status", "updated_at"])

    def _event_exists(self, event_type):
        return ChangeHistory.objects.filter(
            change=self.change, event_type=event_type
        ).exists()

    def test_begin_validation_from_in_progress(self):
        response = self._post("begin_validation")

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "validation")
        self.assertTrue(self._event_exists("validation_started"))

    def test_begin_validation_rejected_from_other_states(self):
        for status in ("scheduled", "validation", "completed"):
            with self.subTest(status=status):
                self._set_status(status)
                response = self._post("begin_validation")
                self.assertEqual(response.status_code, 400, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, status)

    def test_complete_succeeds_after_begin_validation(self):
        started = self._post("begin_validation")
        self.assertEqual(started.status_code, 200, started.data)

        # This is the payload the ChangeDetail page sends: notes only, with
        # validation_passed defaulting to True in ChangeCompleteSerializer.
        response = self._post("complete", {"implementation_notes": "Checks passed"})

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "completed")
        self.assertEqual(response.data["status"], "completed")
        self.assertIsNotNone(self.change.actual_end)
        for event_type in ("validation_started", "validation_passed", "completed"):
            with self.subTest(event_type=event_type):
                self.assertTrue(self._event_exists(event_type))

    def test_complete_with_failed_validation_does_not_complete(self):
        response = self._post(
            "complete",
            {"validation_passed": False, "implementation_notes": "Checks failed"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "validation")
        self.assertFalse(self._event_exists("completed"))
        self.assertTrue(self._event_exists("validation_failed"))

    def test_complete_after_validation_failure_is_rejected(self):
        failed = self._post(
            "complete",
            {"validation_passed": False, "implementation_notes": "Checks failed"},
        )
        self.assertEqual(failed.status_code, 200, failed.data)

        retry = self._post(
            "complete", {"validation_passed": True, "implementation_notes": "Retry"}
        )

        self.assertEqual(retry.status_code, 400, retry.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "validation")
        self.assertFalse(self._event_exists("completed"))

    def test_complete_from_validation_requires_notes(self):
        self._set_status("validation")

        response = self._post("complete", {"implementation_notes": ""})

        self.assertEqual(response.status_code, 400, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "validation")
        self.assertFalse(self._event_exists("completed"))

    def test_complete_from_unrelated_states_is_rejected(self):
        for status in (
            "draft",
            "submitted",
            "pending_approval",
            "approved",
            "scheduled",
            "on_hold",
            "completed",
            "pir_required",
            "failed",
            "rolled_back",
            "closed",
        ):
            with self.subTest(status=status):
                self._set_status(status)
                response = self._post("complete", {"implementation_notes": "Done"})
                self.assertEqual(response.status_code, 400, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, status)
                self.assertFalse(
                    ChangeHistory.objects.filter(
                        change=self.change, event_type="completed"
                    ).exists()
                )

    def test_failure_and_rollback_transitions_are_preserved(self):
        failed = fail_implementation(self.change, self.manager, "Deployment failed")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.failure_reason, "Deployment failed")

        rolled_back = start_rollback(failed, self.manager)
        self.assertEqual(rolled_back.status, "rolled_back")
        self.assertIsNotNone(rolled_back.rollback_started_at)

        completed = complete_rollback(rolled_back, self.manager)
        self.assertIsNotNone(completed.rollback_completed_at)
        self.assertEqual(completed.rollback_completed_by_id, self.manager.pk)
        self.assertFalse(self._event_exists("completed"))

    def test_unauthenticated_completion_is_rejected(self):
        self._set_status("validation")
        self.client.credentials()

        response = self._post("complete", {"implementation_notes": "Done"})

        self.assertIn(response.status_code, (401, 403))
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "validation")

    def test_approve_role_check_is_still_enforced(self):
        approval_change = self._make_change(
            status="pending_approval", title="Needs approval"
        )
        ChangeApproval.objects.create(
            change=approval_change,
            approval_level="manager",
            status="pending",
            requester=self.requester,
            change_version=approval_change.version,
        )
        self._authenticate(self.requester)

        response = self.client.post(
            f"/api/changes/{approval_change.pk}/approve/", {}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        approval_change.refresh_from_db()
        self.assertEqual(approval_change.status, "pending_approval")
