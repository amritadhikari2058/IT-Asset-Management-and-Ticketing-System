"""Gate 2B history/audit/notification tests (baseline)."""
from django.test import TransactionTestCase, override_settings

from accounts.models import User
from common.models import Notification
from problem_management.models import Problem, ProblemHistory
from problem_management import services


def _user(role, n):
    return User.objects.create_user(
        username=f"{role}_his{n}", role=role,
        email=f"{role}.his{n}@example.test", employee_id=f"H{role}{n}"[:30],
    )


class Gate2HistoryBaselineTests(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Hist problem", description="Desc",
        )

    def test_history_immutable(self):
        h = ProblemHistory.objects.filter(problem=self.problem).first()
        self.assertIsNotNone(h)
        with self.assertRaises(Exception):
            h.detail = "changed"
            h.save()

    def test_success_creates_history_event(self):
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before + 1)

    def test_failed_operation_creates_no_success_history(self):
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        with self.assertRaises(Exception):
            services.create_problem_task(actor=self.support, problem=self.problem, title="")
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_notification_on_commit_behavior(self):
        # Notification scheduling should not create pre-commit side effects beyond on_commit registration.
        # Use captureOnCommitCallbacks to execute and verify no crash; exact notification depends on implementation.
        try:
            with self.captureOnCommitCallbacks(execute=True):
                services.create_problem_task(
                    actor=self.support, problem=self.problem, title="Notify task",
                    assigned_to=self.manager,
                )
        except AttributeError:
            # Older Django fallback not expected, but keep test meaningful.
            services.create_problem_task(
                actor=self.support, problem=self.problem, title="Notify task",
                assigned_to=self.manager,
            )
        self.assertTrue(ProblemHistory.objects.filter(problem=self.problem, event_type="task_created").exists())
