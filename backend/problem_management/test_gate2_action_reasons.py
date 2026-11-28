"""ProblemAction transition reason contract tests."""
from unittest import mock

from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import User
from common.models import AuditLog
from problem_management import services
from problem_management.models import ProblemAction, ProblemHistory

BASE = "/api/problems"


def _user(role, n):
    return User.objects.create_user(
        username=f"reason_{role}{n}", role=role,
        email=f"reason.{role}{n}@example.test", employee_id=f"R{role}{n}"[:30],
    )


class ActionReasonContractTests(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Reason problem", description="Desc",
            owner=self.manager,
        )
        services.submit_problem(actor=self.support, problem=self.problem)
        services.accept_problem(actor=self.manager, problem=self.problem)
        self.client = APIClient()
        self.client.force_authenticate(self.support)

    def action_at(self, status="planned", **fields):
        payload = {"title": "Reason action"}
        payload.update(fields)
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, **payload)
        if status != "planned":
            ProblemAction.objects.filter(pk=action.pk).update(status=status)
            action.refresh_from_db()
        return action

    def create_action_api(self, **fields):
        payload = {"title": "Reason action", "description": "Desc"}
        payload.update(fields)
        return self.client.post(
            f"{BASE}/problems/{self.problem.pk}/actions/", payload,
            format="json")

    def history_for(self, action, event):
        return ProblemHistory.objects.filter(
            problem=self.problem, event_type=event,
            detail__contains=f'Action "{action.title}"',
        )

    def audit_for(self, action, event):
        return AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(action.pk), action=event,
        )

    def total_side_effects(self):
        return (
            ProblemHistory.objects.filter(problem=self.problem).count(),
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction").count(),
        )

    def test_api_cancel_requires_trims_and_persists_reason(self):
        action_id = self.create_action_api().data["id"]
        before = self.total_side_effects()
        path = f"{BASE}/actions/{action_id}/cancel/"

        for payload in ({}, {"reason": "   "}):
            with self.subTest(payload=payload):
                resp = self.client.post(path, payload, format="json")
                self.assertEqual(resp.status_code, 400, resp.data)
                self.assertIn("reason", resp.data)

        action = ProblemAction.objects.get(pk=action_id)
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)
        self.assertEqual(self.total_side_effects(), before)

        resp = self.client.post(
            path, {"reason": "  Superseded by PRB-9  "}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        action.refresh_from_db()
        self.assertEqual(action.status, "cancelled")
        self.assertEqual(action.version, 2)

        history = self.history_for(action, "action_cancelled")
        self.assertEqual(history.count(), 1)
        self.assertEqual(
            history.get().detail,
            'Action "Reason action" cancelled: planned -> cancelled. '
            'Reason: Superseded by PRB-9.',
        )

        audit = self.audit_for(action, "problem_action_cancelled")
        self.assertEqual(audit.count(), 1)
        row = audit.get()
        self.assertEqual(
            row.reason,
            f"action={action.pk} cancelled by {self.support.id}: "
            "planned -> cancelled, reason=Superseded by PRB-9",
        )
        self.assertEqual(row.details, {"reason": "Superseded by PRB-9"})

    def test_api_ineffective_requires_trims_and_persists_reason(self):
        action_id = self.create_action_api().data["id"]
        action = ProblemAction.objects.get(pk=action_id)
        services.start_problem_action(actor=self.support, action=action)
        services.complete_problem_action(actor=self.support, action=action)
        before = self.total_side_effects()
        path = f"{BASE}/actions/{action_id}/ineffective/"

        for payload in ({}, {"reason": "\t\n "}):
            with self.subTest(payload=payload):
                resp = self.client.post(path, payload, format="json")
                self.assertEqual(resp.status_code, 400, resp.data)
                self.assertIn("reason", resp.data)

        action.refresh_from_db()
        self.assertEqual(action.status, "completed")
        self.assertEqual(action.version, 3)
        self.assertEqual(self.total_side_effects(), before)

        resp = self.client.post(
            path, {"reason": "  Fix did not hold  "}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        action.refresh_from_db()
        self.assertEqual(action.status, "ineffective")
        self.assertEqual(action.version, 4)

        history = self.history_for(action, "action_ineffective")
        self.assertEqual(history.count(), 1)
        self.assertEqual(
            history.get().detail,
            'Action "Reason action" marked ineffective: '
            'completed -> ineffective. Reason: Fix did not hold.',
        )

        audit = self.audit_for(action, "problem_action_ineffective")
        self.assertEqual(audit.count(), 1)
        row = audit.get()
        self.assertEqual(
            row.reason,
            f"action={action.pk} marked ineffective by {self.support.id}: "
            "completed -> ineffective, reason=Fix did not hold",
        )
        self.assertEqual(row.details, {"reason": "Fix did not hold"})

    def test_direct_services_require_non_blank_reasons_without_writes(self):
        cases = (
            ("cancel", "planned", services.cancel_problem_action, "cancelled"),
            ("ineffective", "completed",
             services.mark_problem_action_ineffective, "ineffective"),
        )
        for name, source, service, target in cases:
            with self.subTest(transition=name):
                action = self.action_at(status=source)
                before = self.total_side_effects()

                for reason in (None, "   "):
                    with self.assertRaises(ValidationError) as caught:
                        service(
                            actor=self.support, action=action, reason=reason)
                    self.assertIn("reason", caught.exception.detail)

                action.refresh_from_db()
                self.assertEqual(action.status, source)
                self.assertEqual(action.version, 1)
                self.assertEqual(self.total_side_effects(), before)

                result = service(
                    actor=self.support, action=action,
                    reason=f"  Valid {name} reason  ")
                self.assertEqual(result.status, target)
                self.assertEqual(result.version, 2)

                event = f"action_{'cancelled' if name == 'cancel' else 'ineffective'}"
                history = self.history_for(action, event)
                self.assertEqual(history.count(), 1)
                self.assertIn(
                    f"Reason: Valid {name} reason.", history.get().detail)

                audit_event = (
                    "problem_action_cancelled" if name == "cancel"
                    else "problem_action_ineffective"
                )
                audit = self.audit_for(action, audit_event)
                self.assertEqual(audit.count(), 1)
                self.assertEqual(
                    audit.get().details, {"reason": f"Valid {name} reason"})

    def test_optional_reasons_are_trimmed_and_omission_still_works(self):
        supplied_id = self.create_action_api(
            title="Supplied reason action").data["id"]
        omitted_id = self.create_action_api(
            title="Omitted reason action").data["id"]
        self.client.force_authenticate(self.manager)

        supplied = self.client.post(
            f"{BASE}/actions/{supplied_id}/approve/",
            {"reason": "  Approve after review  ",
             "expected_record_version": 1},
            format="json",
        )
        self.assertEqual(supplied.status_code, 200, supplied.data)

        supplied_action = ProblemAction.objects.get(pk=supplied_id)
        supplied_history = self.history_for(supplied_action, "action_approved")
        self.assertEqual(supplied_history.count(), 1)
        self.assertEqual(
            supplied_history.get().detail,
            'Action "Supplied reason action" approved: planned -> approved. '
            'Reason: Approve after review.',
        )
        supplied_audit = self.audit_for(
            supplied_action, "problem_action_approved")
        self.assertEqual(supplied_audit.get().details,
                         {"reason": "Approve after review"})
        self.assertIn("reason=Approve after review", supplied_audit.get().reason)

        omitted = self.client.post(
            f"{BASE}/actions/{omitted_id}/approve/",
            {"expected_record_version": 1},
            format="json",
        )
        self.assertEqual(omitted.status_code, 200, omitted.data)

        omitted_action = ProblemAction.objects.get(pk=omitted_id)
        omitted_history = self.history_for(omitted_action, "action_approved")
        self.assertEqual(omitted_history.count(), 1)
        self.assertEqual(
            omitted_history.get().detail,
            'Action "Omitted reason action" approved: planned -> approved.',
        )
        omitted_audit = self.audit_for(
            omitted_action, "problem_action_approved")
        self.assertEqual(omitted_audit.get().details, {})
        self.assertNotIn(", reason=", omitted_audit.get().reason)

    def test_stale_version_returns_409_with_a_valid_reason(self):
        action_id = self.create_action_api().data["id"]
        before = self.total_side_effects()

        resp = self.client.post(
            f"{BASE}/actions/{action_id}/cancel/",
            {"reason": "Stale token test", "expected_record_version": 999},
            format="json",
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertIn("version", str(resp.data).lower())

        action = ProblemAction.objects.get(pk=action_id)
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)
        self.assertEqual(self.total_side_effects(), before)

    def test_history_or_audit_failure_rolls_back_full_transition(self):
        cases = (
            ("problem_management.services.record_history",
             "history write failed"),
            ("problem_management.services.log_action", "audit write failed"),
        )
        for target, message in cases:
            with self.subTest(target=target):
                action = self.action_at()
                before = self.total_side_effects()

                with mock.patch(target, side_effect=RuntimeError(message)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        services.cancel_problem_action(
                            actor=self.support, action=action,
                            reason="  Rollback check  ")

                action.refresh_from_db()
                self.assertEqual(action.status, "planned")
                self.assertEqual(action.version, 1)
                self.assertEqual(self.total_side_effects(), before)
