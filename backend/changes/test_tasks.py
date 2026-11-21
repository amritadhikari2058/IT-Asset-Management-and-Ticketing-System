from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, User
from changes.models import MaintenanceWindow, ChangeRequest
from changes.tasks import (
    evaluate_change_deadlines,
    detect_change_conflicts,
    review_standard_change_templates,
    activate_change_windows,
)
from common.models import BackgroundTaskRun


class ChangeTaskTests(TestCase):
    def setUp(self):
        self.dep = Department.objects.create(name="Eng", code="ENGX")
        self.user = User.objects.create_user(
            username="u@x", email="u@x", employee_id="U1",
            password="pw12345678", role="it_manager", home_department=self.dep,
        )

    def test_evaluate_change_deadlines_runs(self):
        evaluate_change_deadlines.run()
        self.assertTrue(BackgroundTaskRun.objects.filter(
            task_name="changes.tasks.evaluate_change_deadlines", status="succeeded").exists())

    def test_detect_change_conflicts_runs(self):
        detect_change_conflicts.run()
        self.assertTrue(BackgroundTaskRun.objects.filter(
            task_name="changes.tasks.detect_change_conflicts", status="succeeded").exists())

    def test_review_standard_change_templates_runs(self):
        review_standard_change_templates.run()
        self.assertTrue(BackgroundTaskRun.objects.filter(
            task_name="changes.tasks.review_standard_change_templates", status="succeeded").exists())

    def test_activate_change_windows_updates_status(self):
        now = timezone.now()
        mw = MaintenanceWindow.objects.create(
            name="MW", status="approved",
            start_at=now - timezone.timedelta(minutes=1),
            end_at=now + timezone.timedelta(minutes=10),
            created_by=self.user,
        )
        result = activate_change_windows.run()
        mw.refresh_from_db()
        self.assertEqual(mw.status, "active")
        self.assertGreaterEqual(result["activated"], 1)
        self.assertTrue(BackgroundTaskRun.objects.filter(
            task_name="changes.tasks.activate_change_windows", status="succeeded").exists())
