"""Regression tests for the Change Management failure action state contract.

``ChangeDetail`` exposes the Fail action from ``in_progress`` and
``validation``, and ``VALID_TRANSITIONS`` already allows both states to move
to ``failed``. These tests ensure the service agrees with that contract while
preserving the failure reason, history/audit writes, rollback, completion and
authorization behavior.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from changes.models import ChangeHistory, ChangeRequest
from changes.services import (
    _generate_change_number,
    complete_rollback,
    fail_implementation,
    start_rollback,
)
from common.models import AuditLog


class ChangeFailureStateAlignmentTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="Engineering", code="ENGFAIL"
        )
        self.requester = self._make_user("fail_req", "employee")
        self.manager = self._make_user("fail_mgr", "it_manager")
        self.change = self._make_change(status="in_progress")
        self.client = APIClient()
        self._authenticate(self.manager)

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
            "validation_plan": "Validation plan",
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

    def _failed_event(self):
        return ChangeHistory.objects.filter(
            change=self.change, event_type="failed"
        ).order_by("-id").first()

    def _failed_audit(self):
        return AuditLog.objects.filter(
            entity_type="changes.changerequest",
            object_id=str(self.change.pk),
            action="update",
            reason="Implementation failed",
        ).order_by("-id").first()

    def test_fail_from_in_progress_preserves_reason_history_and_audit(self):
        response = self._post("fail", {"failure_reason": "Deployment failed"})

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "failed")
        self.assertEqual(self.change.failure_reason, "Deployment failed")

        event = self._failed_event()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_id, self.manager.pk)
        self.assertIn("Deployment failed", event.detail)

        audit = self._failed_audit()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor_id, self.manager.pk)
        self.assertEqual(audit.details["reason"], "Deployment failed")

    def test_fail_from_validation_matches_frontend_action(self):
        started = self._post("begin_validation")
        self.assertEqual(started.status_code, 200, started.data)

        response = self._post("fail", {"failure_reason": "Validation found a defect"})

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "failed")
        self.assertEqual(self.change.failure_reason, "Validation found a defect")

        event = self._failed_event()
        self.assertIsNotNone(event)
        self.assertIn("Validation found a defect", event.detail)
        self.assertTrue(
            ChangeHistory.objects.filter(
                change=self.change, event_type="validation_started"
            ).exists()
        )

        audit = self._failed_audit()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details["reason"], "Validation found a defect")

    def test_fail_from_validation_requires_failure_reason(self):
        self._set_status("validation")

        for payload in ({}, {"failure_reason": ""}):
            with self.subTest(payload=payload):
                response = self._post("fail", payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, "validation")
                self.assertIsNone(self._failed_event())
                self.assertIsNone(self._failed_audit())

    def test_fail_from_unrelated_states_is_rejected(self):
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
                response = self._post("fail", {"failure_reason": "Should not work"})
                self.assertEqual(response.status_code, 400, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, status)
                self.assertIsNone(self._failed_event())
                self.assertIsNone(self._failed_audit())

    def test_failure_from_validation_can_still_be_rolled_back(self):
        self._set_status("validation")
        failed = fail_implementation(self.change, self.manager, "Bad configuration")

        self.assertEqual(failed.status, "failed")
        rolled_back = start_rollback(failed, self.manager)
        self.assertEqual(rolled_back.status, "rolled_back")
        self.assertIsNotNone(rolled_back.rollback_started_at)

        completed = complete_rollback(rolled_back, self.manager)
        self.assertIsNotNone(completed.rollback_completed_at)
        self.assertEqual(completed.rollback_completed_by_id, self.manager.pk)
        self.assertFalse(
            ChangeHistory.objects.filter(
                change=self.change, event_type="completed"
            ).exists()
        )

    def test_completion_from_validation_still_succeeds(self):
        started = self._post("begin_validation")
        self.assertEqual(started.status_code, 200, started.data)

        response = self._post("complete", {"implementation_notes": "Checks passed"})

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "completed")
        self.assertTrue(
            ChangeHistory.objects.filter(
                change=self.change, event_type="validation_passed"
            ).exists()
        )
        self.assertIsNone(self._failed_event())

    def test_completion_after_failure_is_still_rejected(self):
        self._set_status("validation")
        failed = fail_implementation(self.change, self.manager, "Validation failed")

        self.assertEqual(failed.status, "failed")
        response = self._post("complete", {"implementation_notes": "Retry"})

        self.assertEqual(response.status_code, 400, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "failed")

    def test_unauthenticated_failure_is_denied(self):
        self._set_status("validation")
        self.client.credentials()

        response = self._post("fail", {"failure_reason": "Should not work"})

        self.assertIn(response.status_code, (401, 403))
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "validation")
        self.assertIsNone(self._failed_event())

    def test_employee_can_still_fail_own_change(self):
        self._set_status("validation")
        self._authenticate(self.requester)

        response = self._post("fail", {"failure_reason": "Employee reported defect"})

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "failed")
        self.assertEqual(self.change.failure_reason, "Employee reported defect")
