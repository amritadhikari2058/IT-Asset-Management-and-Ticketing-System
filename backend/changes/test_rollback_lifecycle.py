"""Regression tests for the Change Management rollback lifecycle.

The intended sequence is::

    in_progress -> failed -> start_rollback -> rolled_back
                 -> complete_rollback -> closed

``start_rollback()`` accepts only ``failed`` and ``complete_rollback()``
accepts only ``rolled_back``. These tests keep the authoritative transition
map and the API behavior aligned with that sequence.
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
from changes.views import VALID_TRANSITIONS
from common.models import AuditLog


class ChangeRollbackLifecycleTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="Engineering", code="ENGRB"
        )
        self.requester = self._make_user("rb_req", "employee")
        self.manager = self._make_user("rb_mgr", "it_manager")
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
            "title": "Rollback test change",
            "change_type": "normal",
            "category": "application",
            "priority": "normal",
            "status": status,
            "requester": self.requester,
            "change_owner": self.requester,
            "implementation_plan": "Implementation plan",
            "validation_plan": "Validation plan",
            "rollback_plan": "Restore previous version",
            "planned_start": timezone.now(),
            "planned_end": timezone.now() + timedelta(hours=1),
            "actual_start": timezone.now() if status == "in_progress" else None,
        }
        defaults.update(extra)
        return ChangeRequest.objects.create(**defaults)

    def _authenticate(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _post(self, action):
        return self.client.post(
            f"/api/changes/{self.change.pk}/{action}/",
            {},
            format="json",
        )

    def _set_status(self, status):
        self.change.status = status
        self.change.save(update_fields=["status", "updated_at"])

    @staticmethod
    def _event(event_type):
        return ChangeHistory.objects.filter(event_type=event_type).order_by("-id").first()

    @staticmethod
    def _audit(reason):
        return AuditLog.objects.filter(reason=reason).order_by("-id").first()

    def test_start_rollback_from_failed_records_history_and_audit(self):
        failed = fail_implementation(self.change, self.manager, "Deployment failed")
        self.assertEqual(failed.status, "failed")

        response = self._post("start_rollback")

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "rolled_back")
        self.assertIsNotNone(self.change.rollback_started_at)

        event = self._event("rollback_started")
        self.assertIsNotNone(event)
        self.assertEqual(event.change_id, self.change.pk)
        self.assertEqual(event.actor_id, self.manager.pk)
        self.assertIn(self.manager.employee_id, event.detail)

        audit = self._audit("Rollback started")
        self.assertIsNotNone(audit)
        self.assertEqual(audit.object_id, str(self.change.pk))
        self.assertEqual(audit.actor_id, self.manager.pk)
        self.assertEqual(audit.details["change_number"], self.change.change_number)

    def test_start_rollback_from_in_progress_is_rejected(self):
        response = self._post("start_rollback")

        self.assertEqual(response.status_code, 400, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "in_progress")
        self.assertIsNone(self._event("rollback_started"))
        self.assertIsNone(self._audit("Rollback started"))

    def test_start_rollback_from_other_invalid_states_is_rejected(self):
        for status in (
            "validation",
            "completed",
            "on_hold",
            "rolled_back",
            "cancelled",
            "closed",
        ):
            with self.subTest(status=status):
                self._set_status(status)
                response = self._post("start_rollback")
                self.assertEqual(response.status_code, 400, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, status)

    def test_start_rollback_requires_rollback_plan(self):
        self.change.rollback_plan = ""
        self.change.save(update_fields=["rollback_plan", "updated_at"])
        fail_implementation(self.change, self.manager, "Deployment failed")

        response = self._post("start_rollback")

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("rollback plan", str(response.data).lower())
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "failed")
        self.assertIsNone(self._event("rollback_started"))

    def test_complete_rollback_from_rolled_back_records_history_and_audit(self):
        failed = fail_implementation(self.change, self.manager, "Deployment failed")
        start_rollback(failed, self.manager)

        response = self._post("complete_rollback")

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "rolled_back")
        self.assertIsNotNone(self.change.rollback_completed_at)
        self.assertEqual(self.change.rollback_completed_by_id, self.manager.pk)

        event = self._event("rollback_completed")
        self.assertIsNotNone(event)
        self.assertEqual(event.change_id, self.change.pk)
        self.assertEqual(event.actor_id, self.manager.pk)
        self.assertIn(self.manager.employee_id, event.detail)

        audit = self._audit("Rollback completed")
        self.assertIsNotNone(audit)
        self.assertEqual(audit.object_id, str(self.change.pk))
        self.assertEqual(audit.details["change_number"], self.change.change_number)

    def test_complete_rollback_from_invalid_states_is_rejected(self):
        for status in (
            "in_progress",
            "validation",
            "failed",
            "completed",
            "on_hold",
            "closed",
        ):
            with self.subTest(status=status):
                self._set_status(status)
                response = self._post("complete_rollback")
                self.assertEqual(response.status_code, 400, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, status)
                self.assertIsNone(self.change.rollback_completed_at)
                self.assertIsNone(self._event("rollback_completed"))
                self.assertIsNone(self._audit("Rollback completed"))

    def test_authoritative_transition_map_matches_rollback_service(self):
        self.assertIn("rolled_back", VALID_TRANSITIONS["failed"])
        self.assertNotIn("rolled_back", VALID_TRANSITIONS["in_progress"])
        self.assertIn("closed", VALID_TRANSITIONS["rolled_back"])

    def test_unauthenticated_rollback_actions_are_denied(self):
        self._set_status("failed")
        self.client.credentials()

        start_response = self._post("start_rollback")
        self.assertIn(start_response.status_code, (401, 403))
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "failed")

        self._set_status("rolled_back")
        complete_response = self._post("complete_rollback")
        self.assertIn(complete_response.status_code, (401, 403))
        self.change.refresh_from_db()
        self.assertIsNone(self.change.rollback_completed_at)

    def test_employee_can_still_roll_back_own_change(self):
        failed = fail_implementation(self.change, self.manager, "Deployment failed")
        self._authenticate(self.requester)

        response = self._post("start_rollback")

        self.assertEqual(response.status_code, 200, response.data)
        failed.refresh_from_db()
        self.assertEqual(failed.status, "rolled_back")
