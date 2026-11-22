from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone

from common.models import DataRetentionPolicy
from common.tasks import evaluate_retention_policies


class RetentionTaskTests(TestCase):
    def test_retention_task_registered(self):
        import config.celery  # noqa: F401
        from celery import current_app
        self.assertIn("common.tasks.evaluate_retention_policies", current_app.tasks)

    def test_beat_schedule_points_to_real_implementation(self):
        from django.conf import settings
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["evaluate-retention-policies"]["task"],
            "common.tasks.evaluate_retention_policies",
        )

    def test_disabled_policy_not_dispatched(self):
        DataRetentionPolicy.objects.create(
            name="disabled", data_category="notifications",
            retention_duration=1, enabled=False)
        with patch("common.tasks.execute_retention_policy") as mock_task:
            mock_task.delay = MagicMock()
            result = evaluate_retention_policies()
            mock_task.delay.assert_not_called()
            self.assertEqual(result["checked"], 0)
            self.assertEqual(result["dispatched"], 0)

    def test_due_policy_dispatched(self):
        policy = DataRetentionPolicy.objects.create(
            name="due", data_category="notifications",
            retention_duration=1, enabled=True, next_run_at=None)
        with patch("common.tasks.execute_retention_policy") as mock_task:
            mock_task.delay = MagicMock()
            result = evaluate_retention_policies()
            mock_task.delay.assert_called_once_with(policy.pk)
            self.assertEqual(result["checked"], 1)
            self.assertEqual(result["dispatched"], 1)

    def test_future_policy_not_dispatched(self):
        DataRetentionPolicy.objects.create(
            name="future", data_category="notifications",
            retention_duration=1, enabled=True,
            next_run_at=timezone.now() + timezone.timedelta(days=1))
        with patch("common.tasks.execute_retention_policy") as mock_task:
            mock_task.delay = MagicMock()
            result = evaluate_retention_policies()
            mock_task.delay.assert_not_called()
            self.assertEqual(result["dispatched"], 0)

    def test_dispatch_failure_records_failure(self):
        DataRetentionPolicy.objects.create(
            name="fail", data_category="notifications",
            retention_duration=1, enabled=True, next_run_at=None)
        with patch("common.tasks.execute_retention_policy") as mock_task:
            mock_task.delay.side_effect = Exception("broker down")
            mock_task.side_effect = Exception("inline fail")
            result = evaluate_retention_policies()
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["dispatched"], 0)
