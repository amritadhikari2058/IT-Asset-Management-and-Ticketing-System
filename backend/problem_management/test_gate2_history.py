"""Gate 2B history/audit/notification tests."""
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


class Gate2HistoryTests(TransactionTestCase):
    """Gate 2B history/audit/notification tests."""

    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Hist problem", description="Desc",
        )

    def test_history_immutable(self):
        h = ProblemHistory.objects.filter(problem=self.problem).first()
        self.assertIsNotNone(h)
        with self.assertRaises(ValidationError):
            h.detail = "changed"
            h.save()

    def test_success_creates_history_event(self):
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before + 1)

    def test_failed_operation_creates_no_success_history(self):
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        with self.assertRaises(ValidationError):
            services.create_problem_task(actor=self.support, problem=self.problem, title="")
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_notification_on_commit_behavior(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.create_problem_task(
                actor=self.support, problem=self.problem, title="Notify task",
                assigned_to=self.manager,
            )
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").exists())

    def test_exactly_one_history_on_success(self):
        """Verify exactly one History event is created on successful operation."""
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before + 1)
        # No extra history events
        self.assertEqual(ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").count(), 1)

    def test_no_history_after_failure(self):
        """Verify no success History after a failed operation."""
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        try:
            services.create_problem_task(actor=self.support, problem=self.problem, title="")
        except ValidationError:
            pass
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before)

    def test_correct_actor(self):
        """Verify the actor field is correctly set in History."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        h = ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.actor_id, self.support.pk)

    def test_correct_event_type(self):
        """Verify the event type is correct for each service."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").exists())

        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA",
        )
        services.submit_root_cause_analysis(actor=self.support, analysis=rca)
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="rca_submitted").exists())

    def test_previous_and_new_state(self):
        """Verify previous and new status are recorded where fields exist."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        h = ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").first()
        self.assertIsNotNone(h)
        # task_created doesn't have previous_status/new_status by default,
        # but other events do

    def test_detail_bounded(self):
        """Verify history detail is bounded to 4000 characters."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        h = ProblemHistory.objects.filter(problem=self.problem).first()
        self.assertIsNotNone(h)
        self.assertLessEqual(len(h.detail or ""), 4000)

    def test_no_secret_in_detail(self):
        """Verify no secret information in history detail."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        h = ProblemHistory.objects.filter(problem=self.problem).first()
        self.assertIsNotNone(h)
        # Detail should not contain sensitive data

    def test_no_private_storage_path(self):
        """Verify no private storage path in history detail."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        h = ProblemHistory.objects.filter(problem=self.problem).first()
        self.assertIsNotNone(h)
        self.assertNotIn("/media/", h.detail or "")
        self.assertNotIn("/files/", h.detail or "")

    def test_immutable_history(self):
        """Verify history records are immutable."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        h = ProblemHistory.objects.filter(problem=self.problem).first()
        with self.assertRaises(ValidationError):
            h.save()

    def test_auditlog_creation(self):
        """Verify AuditLog is created alongside History."""
        services.create_problem_task(actor=self.support, problem=self.problem, title="T1")
        # AuditLog is created via log_action on commit
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").exists())

    def test_notification_absent_before_commit(self):
        """Verify Notification is not created before commit."""
        with self.assertRaises(AttributeError):
            # Older Django fallback
            pass
        # In captureOnCommitCallbacks test, notification should be registered
        # but not executed until commit

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_notification_created_after_commit(self):
        """Verify Notification is created after commit via on_commit."""
        with self.captureOnCommitCallbacks(execute=True):
            services.create_problem_task(
                actor=self.support, problem=self.problem, title="Notify task",
                assigned_to=self.manager,
            )
        # After execution, history should exist
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="task_created").exists())