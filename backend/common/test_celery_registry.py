"""Celery registration consistency checks.

A configured Beat entry that points at an unregistered (or placeholder) task
fails silently in production: Beat publishes it, workers reject it as unknown,
and nothing surfaces in the UI. These tests make that class of defect fail the
suite instead.
"""
from django.conf import settings
from django.test import TestCase


def _registered_task_names():
    import config.celery  # noqa: F401  (initialises the Celery app)
    from celery import current_app

    # Force autodiscovery the same way a worker does at startup, so this test
    # verifies real registration rather than the modules imported by tests.
    current_app.loader.import_default_modules()
    return set(current_app.tasks.keys())


class CeleryBeatRegistryTests(TestCase):
    def test_every_beat_entry_points_to_a_registered_task(self):
        registered = _registered_task_names()
        missing = {
            name: entry.get("task")
            for name, entry in settings.CELERY_BEAT_SCHEDULE.items()
            if entry.get("task") not in registered
        }
        self.assertEqual(missing, {}, f"Unregistered Beat tasks: {missing}")

    def test_retention_beat_uses_the_real_implementation(self):
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["evaluate-retention-policies"]["task"],
            "common.tasks.evaluate_retention_policies",
        )
        self.assertIn(
            "common.tasks.evaluate_retention_policies",
            _registered_task_names(),
        )

    def test_no_placeholder_tasks_are_scheduled(self):
        scheduled = {
            entry.get("task")
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
        }
        # The no-op retention placeholder was replaced by the real task.
        self.assertNotIn(
            "common.monitoring_tasks.evaluate_retention_policies", scheduled)
        # The backup task is an explicit not-implemented placeholder; it must
        # not be scheduled as if backups were running.
        self.assertNotIn("backup.tasks.sync_beat_schedules", scheduled)

    def test_changes_tasks_are_registered_and_scheduled(self):
        registered = _registered_task_names()
        scheduled = {
            entry.get("task")
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
        }
        for task_name in (
            "changes.tasks.activate_change_windows",
            "changes.tasks.evaluate_change_deadlines",
            "changes.tasks.detect_change_conflicts",
            "changes.tasks.review_standard_change_templates",
        ):
            self.assertIn(task_name, registered)
            self.assertIn(task_name, scheduled)

    def test_beat_task_names_are_unique(self):
        tasks = [
            entry.get("task")
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
            if entry.get("task")
        ]
        self.assertEqual(len(tasks), len(set(tasks)))
