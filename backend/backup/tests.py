"""Backup & DR: schedules, jobs, restore points API tests."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from backup.models import BackupJob, BackupSchedule, RestorePoint


class BackupApiTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.schedule = BackupSchedule.objects.create(
            name="Daily DB backup",
            schedule_type="database",
            frequency="daily",
            time="02:00",
            enabled=True,
            retention_days=30,
            created_by=self.admin,
        )
        self.job = BackupJob.objects.create(
            schedule=self.schedule,
            job_type="database",
            status="success",
            created_by=self.admin,
        )

    # ---- schedules ----

    def test_employee_cannot_list_schedules(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/backup/schedules/")
        self.assertEqual(res.status_code, 403)

    def test_it_staff_can_create_schedule(self):
        auth(self.c, self.mgr)
        res = self.c.post(
            "/api/backup/schedules/",
            {"name": "Weekly config", "schedule_type": "config",
             "frequency": "weekly", "time": "01:00", "enabled": True,
             "retention_days": 30, "targets": ["localhost"]},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["schedule_type"], "config")

    def test_it_staff_cannot_delete_active_schedule(self):
        BackupJob.objects.create(
            job_type="database", status="running", schedule=self.schedule,
        )
        auth(self.c, self.mgr)
        res = self.c.delete(f"/api/backup/schedules/{self.schedule.pk}/")
        self.assertEqual(res.status_code, 409)

    def test_soft_delete_hides_schedule(self):
        auth(self.c, self.mgr)
        res = self.c.delete(f"/api/backup/schedules/{self.schedule.pk}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(
            BackupSchedule.objects.filter(pk=self.schedule.pk).exists())
        self.assertTrue(
            BackupSchedule.objects.with_deleted().filter(
                pk=self.schedule.pk).exists())

    # ---- jobs ----

    def test_list_jobs_requires_staff(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/backup/jobs/")
        self.assertEqual(res.status_code, 403)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_manual_backup_job_creates_and_runs(self):
        from backup import tasks as backup_tasks
        auth(self.c, self.mgr)
        with patch.object(
            backup_tasks.run_backup_job, "delay",
            lambda *a, **k: backup_tasks.run_backup_job.apply(args=[a[0]]),
        ):
            res = self.c.post(
                "/api/backup/jobs/run_manual/",
                {"type": "config", "target": "localhost"},
                format="json",
            )
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.data["status"], "pending")
        # Eager task execution should have moved the job out of pending.
        job = BackupJob.objects.get(pk=res.data["id"])
        self.assertIn(job.status, ("success", "failed"))

    def test_cancel_pending_job(self):
        job = BackupJob.objects.create(
            job_type="config", status="pending", schedule=self.schedule)
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/backup/jobs/{job.pk}/cancel/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "cancelled")

    # ---- restore points ----

    def test_restore_point_expire_old(self):
        rp = RestorePoint.objects.create(
            restore_type="database", status="available", expires_at=None,
        )
        rp.expires_at = timezone.now() - timedelta(days=1)
        rp.save(update_fields=["expires_at"])

        auth(self.c, self.admin)
        res = self.c.post("/api/backup/restore-points/expire_old/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["expired"], 1)
        rp.refresh_from_db()
        self.assertEqual(rp.status, "expired")
