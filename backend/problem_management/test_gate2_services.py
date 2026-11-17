"""Gate 2B service workflow tests (baseline)."""
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError

from accounts.models import User
from problem_management.models import (
    Problem, ProblemHistory, ProblemTask, ProblemTimelineEvent,
    RootCauseAnalysis, RootCauseWhy, RootCauseFactor,
    ProblemAction, ProblemWorkaround, ProblemValidation, ProblemException,
)
from problem_management import services


def _user(role, n):
    return User.objects.create_user(
        username=f"{role}_svc{n}", role=role,
        email=f"{role}.svc{n}@example.test", employee_id=f"S{role}{n}"[:30],
    )


class Gate2ServiceBaselineTests(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support,
            title="Svc problem",
            description="Desc",
        )

    def test_create_problem_task_service_and_history(self):
        task = services.create_problem_task(
            actor=self.support, problem=self.problem, title="Investigate",
        )
        self.assertEqual(task.problem_id, self.problem.pk)
        self.assertEqual(task.sequence, 1)
        self.assertTrue(
            ProblemHistory.objects.filter(
                problem=self.problem, event_type="task_created", task=task
            ).exists()
        )

    def test_update_problem_fields_records_history(self):
        updated = services.update_problem_fields(
            actor=self.support, problem=self.problem, fields={"title": "Updated title"},
        )
        self.assertEqual(updated.title, "Updated title")
        self.assertTrue(ProblemHistory.objects.filter(problem=self.problem, event_type="other").exists())

    def test_create_timeline_event_if_available(self):
        if hasattr(services, "create_problem_timeline_event"):
            from django.utils import timezone
            evt = services.create_problem_timeline_event(
                actor=self.support, problem=self.problem,
                occurred_at=timezone.now(), source="manual",
                event_type="milestone", title="Milestone", description="d",
            )
            self.assertEqual(evt.problem_id, self.problem.pk)

    def test_create_action_if_available(self):
        if hasattr(services, "create_problem_action"):
            action = services.create_problem_action(
                actor=self.support, problem=self.problem, title="Action", description="d",
            )
            self.assertEqual(action.problem_id, self.problem.pk)

    def test_create_workaround_if_available(self):
        if hasattr(services, "create_problem_workaround"):
            wa = services.create_problem_workaround(
                actor=self.support, problem=self.problem, title="WA", description="d",
            )
            self.assertEqual(wa.problem_id, self.problem.pk)
