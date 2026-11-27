"""Regression tests for controlled PIR completion and change closure.

A PIR is completed through ``POST /api/changes/post-implementation-reviews/
{id}/complete/`` rather than by writing ``status`` through the general-purpose
serializer. Once completed, a change in ``pir_required`` must be closable while
the existing mandatory-PIR rules for high/critical, failed and rolled-back
changes remain intact.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from changes.models import ChangeHistory, ChangeRequest, PostImplementationReview
from changes.services import _generate_change_number
from common.models import AuditLog


PIR_LIST_URL = "/api/changes/post-implementation-reviews/"


class PIRCompletionWorkflowTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="Engineering", code="ENGPIR"
        )
        self.requester = self._make_user("pir_req", "employee")
        self.manager = self._make_user("pir_mgr", "it_manager")
        self.admin = self._make_user("pir_admin", "system_admin")
        self.support = self._make_user("pir_sup", "it_support")
        self.superuser = self._make_user(
            "pir_root", "employee", is_superuser=True, is_staff=True
        )
        self.client = APIClient()
        self._authenticate(self.manager)

        self.change = self._make_change(status="pir_required", risk_level="low")
        self.pir = self._make_pir(status="pending", outcome="successful")

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

    def _make_change(self, status, risk_level="low"):
        return ChangeRequest.objects.create(
            change_number=_generate_change_number(),
            title="PIR workflow change",
            change_type="normal",
            category="application",
            priority="normal",
            status=status,
            risk_level=risk_level,
            requester=self.requester,
            change_owner=self.requester,
            implementation_plan="Implementation plan",
            rollback_plan="Rollback plan",
            planned_start=timezone.now(),
            planned_end=timezone.now() + timedelta(hours=1),
        )

    def _make_pir(self, status, outcome):
        return PostImplementationReview.objects.create(
            change=self.change,
            status=status,
            outcome=outcome,
            objectives_met="Objectives confirmed",
            lessons_learned="Communicate earlier",
        )

    def _authenticate(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _complete_url(self, pir=None):
        pir = pir or self.pir
        return f"{PIR_LIST_URL}{pir.pk}/complete/"

    def _detail_url(self, pir=None):
        pir = pir or self.pir
        return f"{PIR_LIST_URL}{pir.pk}/"

    def _close_url(self):
        return f"/api/changes/{self.change.pk}/close/"

    def _post_complete(self):
        return self.client.post(self._complete_url(), {}, format="json")

    def _post_close(self):
        return self.client.post(
            self._close_url(),
            {"closure_summary": "All objectives met."},
            format="json",
        )

    def _reset_pir(self, status="pending", outcome="successful"):
        self.pir.status = status
        self.pir.outcome = outcome
        self.pir.completed_at = None
        self.pir.reviewed_by = None
        self.pir.save(
            update_fields=["status", "outcome", "completed_at", "reviewed_by", "updated_at"]
        )

    @staticmethod
    def _event_count():
        return ChangeHistory.objects.filter(event_type="pir_completed").count()

    def test_complete_pir_persists_status_and_completion_metadata(self):
        response = self._post_complete()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["reviewed_by"], self.manager.pk)
        self.assertEqual(response.data["reviewed_by_email"], self.manager.email)
        self.assertIsNotNone(response.data["completed_at"])
        self.assertEqual(response.data["outcome"], "successful")

        self.pir.refresh_from_db()
        self.assertEqual(self.pir.status, "completed")
        self.assertEqual(self.pir.reviewed_by, self.manager)
        self.assertIsNotNone(self.pir.completed_at)

        event = ChangeHistory.objects.get(
            change=self.change, event_type="pir_completed"
        )
        self.assertEqual(event.actor, self.manager)
        self.assertIn(self.manager.employee_id, event.detail)
        self.assertTrue(
            AuditLog.objects.filter(
                action="update", reason="PIR completed",
                entity_type="changes.postimplementationreview",
            ).exists()
        )

    def test_invalid_completion_attempts_are_rejected(self):
        cases = [
            ("waived", "successful", "waived PIR cannot be completed"),
            ("completed", "successful", "already been completed"),
            ("pending", "", "review outcome is required"),
            ("pending", "unknown_outcome", "Invalid review outcome"),
        ]
        for status, outcome, message in cases:
            with self.subTest(status=status, outcome=outcome):
                self._reset_pir(status=status, outcome=outcome)
                before_events = self._event_count()

                response = self._post_complete()

                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(message, str(response.data).lower() if message.islower() else str(response.data))
                self.pir.refresh_from_db()
                self.assertEqual(self.pir.status, status)
                self.assertIsNone(self.pir.completed_at)
                self.assertEqual(self._event_count(), before_events)

    def test_repeated_completion_is_rejected_without_new_metadata(self):
        first = self._post_complete()
        self.assertEqual(first.status_code, 200, first.data)
        self.pir.refresh_from_db()
        completed_at = self.pir.completed_at

        second = self._post_complete()

        self.assertEqual(second.status_code, 400, second.data)
        self.assertIn("already been completed", str(second.data).lower())
        self.pir.refresh_from_db()
        self.assertEqual(self.pir.completed_at, completed_at)
        self.assertEqual(self._event_count(), 1)

    def test_pir_status_is_not_writable_through_general_serializer(self):
        response = self.client.patch(
            self._detail_url(), {"status": "completed"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "pending")
        self.pir.refresh_from_db()
        self.assertEqual(self.pir.status, "pending")
        self.assertIsNone(self.pir.completed_at)

    def test_completion_permissions_are_limited_to_managers_and_admins(self):
        self.client.credentials()
        response = self._post_complete()
        self.assertIn(response.status_code, (401, 403))
        self.pir.refresh_from_db()
        self.assertEqual(self.pir.status, "pending")

        for user in (self.requester, self.support):
            with self.subTest(role=user.role):
                self._authenticate(user)
                response = self._post_complete()
                self.assertEqual(response.status_code, 403, response.data)
                self.pir.refresh_from_db()
                self.assertEqual(self.pir.status, "pending")

        for user in (self.manager, self.admin, self.superuser):
            with self.subTest(user=user.username):
                self._reset_pir()
                self._authenticate(user)
                response = self._post_complete()
                self.assertEqual(response.status_code, 200, response.data)

    def test_pir_required_change_closes_after_completion(self):
        self.assertEqual(self._post_complete().status_code, 200)
        self._authenticate(self.manager)

        response = self._post_close()

        self.assertEqual(response.status_code, 200, response.data)
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "closed")
        self.assertIsNotNone(self.change.closed_at)
        self.assertEqual(self.change.closure_summary, "All objectives met.")
        self.assertTrue(
            ChangeHistory.objects.filter(
                change=self.change, event_type="closed"
            ).exists()
        )

    def test_pir_required_change_cannot_close_without_completed_pir(self):
        self.pir.delete()
        response = self._post_close()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("review is required", str(response.data))
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "pir_required")

        self.pir = self._make_pir(status="in_progress", outcome="successful")
        response = self._post_close()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("completed post-implementation review", str(response.data).lower())
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "pir_required")

    def test_mandatory_pir_rules_are_preserved_for_high_risk_and_failed_states(self):
        cases = [
            ("completed", "high"),
            ("completed", "critical"),
            ("failed", "low"),
            ("rolled_back", "low"),
        ]
        for change_status, risk_level in cases:
            with self.subTest(status=change_status, risk_level=risk_level):
                self.change.status = change_status
                self.change.risk_level = risk_level
                self.change.save(update_fields=["status", "risk_level", "updated_at"])
                self._reset_pir(status="in_progress")

                incomplete_response = self._post_close()
                self.assertEqual(incomplete_response.status_code, 400, incomplete_response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, change_status)

                self._reset_pir(status="completed")
                self.pir.completed_at = timezone.now()
                self.pir.reviewed_by = self.manager
                self.pir.save(
                    update_fields=["completed_at", "reviewed_by", "updated_at"]
                )

                completed_response = self._post_close()
                self.assertEqual(completed_response.status_code, 200, completed_response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, "closed")

    def test_existing_low_and_medium_risk_closure_still_works_without_pir(self):
        self.pir.delete()
        for risk_level in ("low", "medium"):
            with self.subTest(risk_level=risk_level):
                self.change.status = "completed"
                self.change.risk_level = risk_level
                self.change.closed_at = None
                self.change.closure_summary = ""
                self.change.save(
                    update_fields=[
                        "status", "risk_level", "closed_at",
                        "closure_summary", "updated_at",
                    ]
                )

                response = self._post_close()

                self.assertEqual(response.status_code, 200, response.data)
                self.change.refresh_from_db()
                self.assertEqual(self.change.status, "closed")
                self.assertIsNotNone(self.change.closed_at)
