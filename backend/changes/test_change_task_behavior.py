"""Behavioural tests for the four Change Management background tasks."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, User
from changes import tasks as change_tasks
from changes.conflicts import detect_conflicts
from changes.models import (BlackoutPeriod, ChangeConflict, ChangeRequest,
                            ChangeTemplate, MaintenanceWindow)
from changes.tests import make_change, make_users
from common.models import BackgroundTaskRun


class ChangeTaskTestCase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.now = timezone.now()

    def _runs(self, task_name):
        return BackgroundTaskRun.objects.filter(task_name=task_name)


class EvaluateChangeDeadlinesTests(ChangeTaskTestCase):
    TASK = "changes.tasks.evaluate_change_deadlines"

    def test_upcoming_implementation_within_24h_is_reported(self):
        make_change(
            self.mgr, None, status="scheduled",
            planned_start=self.now + timedelta(hours=2),
            planned_end=self.now + timedelta(hours=3),
        )
        result = change_tasks.evaluate_change_deadlines.run()
        self.assertTrue(any("due in next 24h" in f for f in result["findings"]))
        run = self._runs(self.TASK).get()
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(run.payload["findings"])

    def test_implementation_beyond_24h_is_not_reported_as_upcoming(self):
        make_change(
            self.mgr, None, status="scheduled",
            planned_start=self.now + timedelta(hours=48),
            planned_end=self.now + timedelta(hours=49),
        )
        result = change_tasks.evaluate_change_deadlines.run()
        self.assertFalse(
            any("due in next 24h" in f for f in result["findings"]))

    def test_overdue_approval_is_reported(self):
        make_change(
            self.mgr, None, status="pending_approval",
            planned_start=self.now - timedelta(hours=1),
        )
        result = change_tasks.evaluate_change_deadlines.run()
        self.assertTrue(any("approval(s) overdue" in f
                            for f in result["findings"]))

    def test_each_run_records_exactly_one_execution_row(self):
        change_tasks.evaluate_change_deadlines.run()
        change_tasks.evaluate_change_deadlines.run()
        rows = self._runs(self.TASK)
        self.assertEqual(rows.count(), 2)
        self.assertFalse(rows.filter(status="running").exists())
        for row in rows:
            self.assertIsNotNone(row.finished_at)


class DetectChangeConflictsTaskTests(ChangeTaskTestCase):
    TASK = "changes.tasks.detect_change_conflicts"

    def _overlapping_pair(self):
        start = self.now + timedelta(hours=4)
        end = start + timedelta(hours=2)
        first = make_change(
            self.mgr, None, status="scheduled", department=self.dep,
            planned_start=start, planned_end=end,
        )
        second = make_change(
            self.mgr, None, status="scheduled", department=self.dep,
            planned_start=start, planned_end=end,
        )
        return first, second

    def test_repeated_runs_do_not_duplicate_conflicts(self):
        self._overlapping_pair()
        change_tasks.detect_change_conflicts.run()
        first_count = ChangeConflict.objects.count()
        self.assertGreater(first_count, 0)

        result = change_tasks.detect_change_conflicts.run()
        self.assertEqual(ChangeConflict.objects.count(), first_count)
        self.assertEqual(result["created"], 0)
        self.assertGreater(result["updated"], 0)
        self.assertEqual(self._runs(self.TASK).count(), 2)

    def test_scan_does_not_reopen_a_resolved_conflict(self):
        self._overlapping_pair()
        change_tasks.detect_change_conflicts.run()
        conflict = ChangeConflict.objects.first()
        conflict.status = "resolved"
        conflict.save(update_fields=["status"])

        change_tasks.detect_change_conflicts.run()
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, "resolved")

    def test_blackout_with_service_scope_does_not_raise(self):
        from tickets.models import TicketCategory
        cat = TicketCategory.objects.create(name="CT")
        from changes.tests import make_service_item
        item = make_service_item(cat)
        change = make_change(
            self.mgr, item, status="scheduled",
            planned_start=self.now + timedelta(hours=1),
            planned_end=self.now + timedelta(hours=2),
        )
        BlackoutPeriod.objects.create(
            code="BP-SVC", name="Service freeze", period_type="freeze",
            start_at=self.now, end_at=self.now + timedelta(days=1),
            scope_service=item, created_by=self.admin,
        )
        # Must not raise AttributeError for a change with no service impact.
        conflicts = detect_conflicts(change)
        self.assertIsInstance(conflicts, list)


class ActivateChangeWindowsTests(ChangeTaskTestCase):
    TASK = "changes.tasks.activate_change_windows"

    def _window(self, start, end, status="approved"):
        return MaintenanceWindow.objects.create(
            name="Window", code=f"W-{MaintenanceWindow.objects.count() + 1}",
            window_type="one_time", start_at=start, end_at=end,
            status=status, created_by=self.admin,
        )

    def test_window_becomes_active_then_completes(self):
        window = self._window(self.now - timedelta(minutes=5),
                              self.now + timedelta(minutes=30))
        result = change_tasks.activate_change_windows.run()
        window.refresh_from_db()
        self.assertEqual(window.status, "active")
        self.assertEqual(result["activated"], 1)

        # Idempotent: a second run performs no further transitions.
        again = change_tasks.activate_change_windows.run()
        self.assertEqual(again["activated"], 0)
        self.assertEqual(again["completed"], 0)

    def test_expired_active_window_is_completed(self):
        window = self._window(self.now - timedelta(hours=2),
                              self.now - timedelta(hours=1), status="active")
        result = change_tasks.activate_change_windows.run()
        window.refresh_from_db()
        self.assertEqual(window.status, "completed")
        self.assertEqual(result["completed"], 1)

    def test_draft_window_is_not_activated(self):
        window = self._window(self.now - timedelta(minutes=5),
                              self.now + timedelta(minutes=30),
                              status="draft")
        change_tasks.activate_change_windows.run()
        window.refresh_from_db()
        self.assertEqual(window.status, "draft")


class ReviewStandardChangeTemplatesTests(ChangeTaskTestCase):
    TASK = "changes.tasks.review_standard_change_templates"

    def test_overdue_template_is_reported_without_state_change(self):
        template = ChangeTemplate.objects.create(
            name="Restart service", code="TPL-1", category="infrastructure",
            owner=self.mgr, created_by=self.admin,
            is_active=True, is_preapproved=True,
            next_review_due=self.now - timedelta(days=1),
        )
        result = change_tasks.review_standard_change_templates.run()
        self.assertEqual(result["overdue_templates"], 1)
        template.refresh_from_db()
        self.assertTrue(template.is_active)
        run = self._runs(self.TASK).get()
        self.assertEqual(run.payload["overdue_template_ids"], [template.pk])

    def test_template_not_yet_due_is_ignored(self):
        ChangeTemplate.objects.create(
            name="Future review", code="TPL-2", category="infrastructure",
            owner=self.mgr, created_by=self.admin,
            is_active=True, is_preapproved=True,
            next_review_due=self.now + timedelta(days=10),
        )
        result = change_tasks.review_standard_change_templates.run()
        self.assertEqual(result["overdue_templates"], 0)
