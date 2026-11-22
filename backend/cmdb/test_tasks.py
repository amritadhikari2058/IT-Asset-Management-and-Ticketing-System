"""CMDB background task tests."""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Department
from assets.models import Asset, AssetCategory
from cmdb.models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemType,
)
from cmdb.tasks import (
    check_ci_verification_age_task,
    evaluate_configuration_drift_task,
    sync_assets_to_cmdb_task,
)
from cmdb.tests import make_user
from common.models import BackgroundTaskRun, Notification


class DriftTaskTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.ci = ConfigurationItem.objects.create(
            name="CI", ci_type=self.t, status="active", source="manual",
        )
        self.baseline = ConfigurationBaseline.objects.create(
            name="BL", code="BL-T1", scope_type="single_ci", status="approved",
            snapshot={"cis": {self.ci.ci_number: {"name": "CI", "status": "active"}}},
            checksum="x", created_by=self.admin,
        )
        self.baseline.configuration_items.add(self.ci)

    def test_evaluate_drift_task_success_idempotent(self):
        # make drift
        self.ci.name = "CI2"
        self.ci.save()
        with patch("cmdb.tasks.evaluate_configuration_drift_task.retry", side_effect=Exception("retry")):
            result = evaluate_configuration_drift_task(batch_size=50)
        self.assertIn("evaluated_cis", result)
        self.assertIn("findings_opened", result)
        self.assertIn("baselines", result)
        run = BackgroundTaskRun.objects.filter(
            task_name="cmdb.tasks.evaluate_configuration_drift_task",
        ).order_by("-id").first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(run.success)
        self.assertIsNotNone(run.finished_at)

    def test_evaluate_drift_task_failure_path(self):
        with patch("cmdb.baselines.evaluate_configuration_drift", side_effect=RuntimeError("boom")):
            with self.assertRaises(Exception):
                evaluate_configuration_drift_task(batch_size=10)
        run = BackgroundTaskRun.objects.filter(
            task_name="cmdb.tasks.evaluate_configuration_drift_task",
        ).order_by("-id").first()
        self.assertEqual(run.status, "failed")
        self.assertFalse(run.success)
        self.assertEqual(run.error_summary, "RuntimeError")


class SyncTaskTests(TestCase):
    def setUp(self):
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.dept = Department.objects.create(name="IT", code="IT2")

    def test_sync_assets_task_counts_and_run(self):
        Asset.objects.create(
            name="A1", asset_tag="A1", category=self.cat, department=self.dept, status="available",
        )
        with patch("cmdb.tasks.sync_assets_to_cmdb_task.retry", side_effect=Exception("retry")):
            result = sync_assets_to_cmdb_task(batch_size=50, offset=0)
        for k in ["processed", "created", "updated", "skipped", "batch_size", "offset"]:
            self.assertIn(k, result)
        run = BackgroundTaskRun.objects.filter(
            task_name="cmdb.tasks.sync_assets_to_cmdb_task",
        ).order_by("-id").first()
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(run.success)


class VerificationAgeTaskTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )

    def test_check_verification_age_task_flags_and_dedupes(self):
        ci = ConfigurationItem.objects.create(
            name="Old", ci_type=self.t, status="active", source="manual",
            owner=self.admin, criticality="high",
        )
        with patch("cmdb.tasks.check_ci_verification_age_task.retry", side_effect=Exception("retry")):
            r1 = check_ci_verification_age_task(batch_size=50, notify=True)
        self.assertIn("overdue_cis", r1)
        self.assertIn("flagged", r1)
        self.assertIn("notifications_sent", r1)
        self.assertIn("threshold_days", r1)
        count1 = ConfigurationDriftFinding.objects.filter(
            configuration_item=ci, finding_type="unverified_ci",
        ).count()
        self.assertGreaterEqual(count1, 1)
        with patch("cmdb.tasks.check_ci_verification_age_task.retry", side_effect=Exception("retry")):
            r2 = check_ci_verification_age_task(batch_size=50, notify=True)
        count2 = ConfigurationDriftFinding.objects.filter(
            configuration_item=ci, finding_type="unverified_ci",
        ).count()
        self.assertEqual(count1, count2)
        run = BackgroundTaskRun.objects.filter(
            task_name="cmdb.tasks.check_ci_verification_age_task",
        ).order_by("-id").first()
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(run.success)

    def test_verification_age_notification_contract(self):
        """Migrated verification notification uses central contract; time-windowed repeat."""
        ci = ConfigurationItem.objects.create(
            name="OverdueCI", ci_type=self.t, status="active", source="manual",
            owner=self.admin, criticality="high",
        )
        with patch("cmdb.tasks.check_ci_verification_age_task.retry", side_effect=Exception("retry")):
            r1 = check_ci_verification_age_task(batch_size=50, notify=True)
        self.assertGreaterEqual(r1["notifications_sent"], 1)

        notif = Notification.objects.get(
            recipient=self.admin,
            entity_type="cmdb.ConfigurationItem",
            object_id=str(ci.pk),
        )
        self.assertIn(ci.ci_number, notif.title)
        self.assertIn("verified within", notif.body)
        self.assertIsNone(notif.dedupe_key)

        # Existing open finding is idempotent; no duplicate notification.
        with patch("cmdb.tasks.check_ci_verification_age_task.retry", side_effect=Exception("retry")):
            r2 = check_ci_verification_age_task(batch_size=50, notify=True)
        self.assertEqual(r2["notifications_sent"], 0)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.admin,
                entity_type="cmdb.ConfigurationItem",
                object_id=str(ci.pk),
            ).count(),
            1,
        )
