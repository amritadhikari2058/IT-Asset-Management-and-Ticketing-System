"""Action transition atomicity, rollback, and PostgreSQL concurrency tests."""
import threading
from unittest import mock, skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from accounts.models import User
from common.models import AuditLog
from problem_management import services
from problem_management.models import ProblemAction, ProblemHistory

BASE = "/api/problems"


def _user(role, n):
    return User.objects.create_user(
        username=f"action_{role}_atomic{n}", role=role,
        email=f"action.{role}.atomic{n}@example.test",
        employee_id=f"A{role}{n}"[:30],
    )


class _ActionTransitionTestBase(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.employee = _user("employee", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Action atomicity problem",
            description="Desc", owner=self.manager,
        )
        services.submit_problem(actor=self.support, problem=self.problem)
        services.accept_problem(actor=self.manager, problem=self.problem)

    def action_at(self, status="planned", **fields):
        payload = {"title": "Atomic action"}
        payload.update(fields)
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, **payload)
        if status != "planned":
            ProblemAction.objects.filter(pk=action.pk).update(status=status)
            action.refresh_from_db()
        return action

    def history_count(self, event=None):
        qs = ProblemHistory.objects.filter(problem=self.problem)
        if event:
            qs = qs.filter(event_type=event)
        return qs.count()

    def audit_count(self, action=None, event=None):
        qs = AuditLog.objects.filter(
            entity_type="problem_management.problemaction")
        if action:
            qs = qs.filter(object_id=str(action.pk))
        if event:
            qs = qs.filter(action=event)
        return qs.count()


class ActionTransitionAtomicityTests(_ActionTransitionTestBase):
    """Sequential invariants that must hold on every supported database."""

    def test_each_transition_increments_version_exactly_once(self):
        cases = (
            ("approve", services.approve_problem_action, self.manager,
             "planned", "approved", "action_approved", "problem_action_approved"),
            ("start", services.start_problem_action, self.support,
             "planned", "in_progress", "action_started", "problem_action_started"),
            ("complete", services.complete_problem_action, self.support,
             "in_progress", "completed", "action_completed", "problem_action_completed"),
            ("validate", services.validate_problem_action, self.support,
             "completed", "verified", "action_validated", "problem_action_validated"),
            ("ineffective", services.mark_problem_action_ineffective,
             self.support, "completed", "ineffective",
             "action_ineffective", "problem_action_ineffective"),
            ("cancel", services.cancel_problem_action, self.support,
             "planned", "cancelled", "action_cancelled", "problem_action_cancelled"),
        )
        for (name, transition, actor, source, target,
             history_event, audit_event) in cases:
            with self.subTest(transition=name):
                action = self.action_at(status=source)
                audit_before = self.audit_count(action, audit_event)

                result = transition(
                    actor=actor, action=action, expected_record_version=1,
                    reason="Reason for atomicity test")

                result.refresh_from_db()
                self.assertEqual(result.status, target)
                self.assertEqual(result.version, 2)
                self.assertEqual(self.history_count(history_event), 1)
                self.assertEqual(self.audit_count(action, audit_event),
                                 audit_before + 1)

    def test_stale_version_token_returns_409_without_writes(self):
        action = self.action_at()

        with self.assertRaises(services.StaleRecordError) as caught:
            services.approve_problem_action(
                actor=self.manager, action=action,
                expected_record_version=999)
        self.assertEqual(caught.exception.status_code, 409)

        client = APIClient()
        client.force_authenticate(self.manager)
        response = client.post(
            f"{BASE}/actions/{action.pk}/approve/",
            {"expected_record_version": 999}, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("version", str(response.data).lower())

        action.refresh_from_db()
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)
        self.assertEqual(self.history_count("action_approved"), 0)
        self.assertEqual(self.audit_count(action, "problem_action_approved"), 0)

    def test_invalid_source_status_leaves_state_and_side_effects_unchanged(self):
        cases = (
            ("approve", services.approve_problem_action, self.manager,
             "in_progress"),
            ("start", services.start_problem_action, self.support, "completed"),
            ("complete", services.complete_problem_action, self.support, "planned"),
            ("validate", services.validate_problem_action, self.support,
             "in_progress"),
            ("ineffective", services.mark_problem_action_ineffective,
             self.support, "planned"),
            ("cancel", services.cancel_problem_action, self.support, "verified"),
        )
        for name, transition, actor, source in cases:
            with self.subTest(transition=name):
                action = self.action_at(status=source)
                history_before = self.history_count()
                audit_before = self.audit_count(action)

                with self.assertRaises(ValidationError) as caught:
                    transition(
                        actor=actor, action=action,
                        expected_record_version=1)
                self.assertIn("action", caught.exception.detail)

                action.refresh_from_db()
                self.assertEqual(action.status, source)
                self.assertEqual(action.version, 1)
                self.assertEqual(self.history_count(), history_before)
                self.assertEqual(self.audit_count(action), audit_before)

    def test_history_failure_rolls_back_action_state_and_version(self):
        action = self.action_at()

        with mock.patch(
                "problem_management.services.record_history",
                side_effect=RuntimeError("history write failed")):
            with self.assertRaisesRegex(RuntimeError, "history write failed"):
                services.approve_problem_action(
                    actor=self.manager, action=action)

        action.refresh_from_db()
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)
        self.assertEqual(self.history_count("action_approved"), 0)
        self.assertEqual(self.audit_count(action, "problem_action_approved"), 0)

    def test_audit_failure_rolls_back_state_version_and_history(self):
        action = self.action_at()

        with mock.patch(
                "problem_management.services.log_action",
                side_effect=RuntimeError("audit write failed")):
            with self.assertRaisesRegex(RuntimeError, "audit write failed"):
                services.cancel_problem_action(
                    actor=self.support, action=action,
                    reason="Rollback test cancellation")

        action.refresh_from_db()
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)
        self.assertEqual(self.history_count("action_cancelled"), 0)
        self.assertEqual(self.audit_count(action, "problem_action_cancelled"), 0)

    def test_repeated_approval_creates_only_one_transition_and_side_effect_pair(self):
        action = self.action_at()

        approved = services.approve_problem_action(
            actor=self.manager, action=action)
        self.assertEqual(approved.status, "approved")

        with self.assertRaises(ValidationError) as caught:
            services.approve_problem_action(actor=self.manager, action=action)
        self.assertIn("action", caught.exception.detail)

        action.refresh_from_db()
        self.assertEqual(action.status, "approved")
        self.assertEqual(action.version, 2)
        self.assertEqual(self.history_count("action_approved"), 1)
        self.assertEqual(self.audit_count(action, "problem_action_approved"), 1)

    def test_role_restrictions_remain_enforced(self):
        action = self.action_at()

        with self.assertRaises(PermissionDenied):
            services.approve_problem_action(actor=self.support, action=action)
        action.refresh_from_db()
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)

        for name, transition in (
            ("start", services.start_problem_action),
            ("complete", services.complete_problem_action),
            ("validate", services.validate_problem_action),
            ("ineffective", services.mark_problem_action_ineffective),
            ("cancel", services.cancel_problem_action),
        ):
            with self.subTest(transition=name):
                with self.assertRaises(PermissionDenied):
                    transition(actor=self.employee, action=action)
                action.refresh_from_db()
                self.assertEqual(action.status, "planned")
                self.assertEqual(action.version, 1)
                self.assertEqual(self.audit_count(action), 1)


@skipUnless(
    connection.vendor == "postgresql",
    "PostgreSQL required for real select_for_update row-lock verification",
)
class ActionTransitionConcurrencyPostgresTests(_ActionTransitionTestBase):
    """Separate-connection tests; these are skipped on SQLite."""

    reset_sequences = True

    def _run_concurrent(self, calls):
        barrier = threading.Barrier(len(calls))
        results = [None] * len(calls)
        errors = [None] * len(calls)

        def worker(index, user, path, payload):
            try:
                close_old_connections()
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=15)
                response = client.post(f"{BASE}{path}", payload or {}, format="json")
                results[index] = {
                    "status": response.status_code,
                    "data": getattr(response, "data", None),
                }
            except Exception as exc:  # noqa: BLE001 - surfaced to the test below
                errors[index] = exc
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(index, *call))
            for index, call in enumerate(calls)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        if any(thread.is_alive() for thread in threads):
            self.fail("Concurrent transition workers did not finish within timeout")
        for error in errors:
            if error is not None:
                raise error
        return results

    def test_concurrent_duplicate_approvals_only_one_succeeds(self):
        action = self.action_at()
        results = self._run_concurrent([
            (self.manager, f"/actions/{action.pk}/approve/",
             {"expected_record_version": 1}),
            (self.manager, f"/actions/{action.pk}/approve/",
             {"expected_record_version": 1}),
        ])

        self.assertEqual(sorted(r["status"] for r in results), [200, 409], results)
        action.refresh_from_db()
        self.assertEqual(action.status, "approved")
        self.assertEqual(action.version, 2)
        self.assertEqual(self.history_count("action_approved"), 1)
        self.assertEqual(self.audit_count(action, "problem_action_approved"), 1)

    def test_concurrent_approve_and_start_only_one_succeeds(self):
        action = self.action_at()
        results = self._run_concurrent([
            (self.manager, f"/actions/{action.pk}/approve/",
             {"expected_record_version": 1}),
            (self.support, f"/actions/{action.pk}/start/",
             {"expected_record_version": 1}),
        ])

        self.assertEqual(sorted(r["status"] for r in results), [200, 409], results)
        action.refresh_from_db()
        self.assertIn(action.status, ("approved", "in_progress"))
        self.assertEqual(action.version, 2)
        self.assertEqual(
            self.history_count("action_approved")
            + self.history_count("action_started"), 1)
        self.assertEqual(
            self.audit_count(action, "problem_action_approved")
            + self.audit_count(action, "problem_action_started"), 1)

    def test_concurrent_duplicate_starts_only_one_succeeds(self):
        action = self.action_at()
        results = self._run_concurrent([
            (self.support, f"/actions/{action.pk}/start/",
             {"expected_record_version": 1}),
            (self.support, f"/actions/{action.pk}/start/",
             {"expected_record_version": 1}),
        ])

        self.assertEqual(sorted(r["status"] for r in results), [200, 409], results)
        action.refresh_from_db()
        self.assertEqual(action.status, "in_progress")
        self.assertEqual(action.version, 2)
        self.assertEqual(self.history_count("action_started"), 1)
        self.assertEqual(self.audit_count(action, "problem_action_started"), 1)
