"""Scheduled report management: CRUD permissions, history, and retry."""
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from common.models import ScheduledReport, ScheduledReportRun, SavedReport
from tickets.models import TicketCategory


@override_settings(
    **{"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"})
class ScheduledReportTests(TestCase):
    """Scheduled report delivery: permission, history, retry behavior."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="HW")
        self.sr = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category", name="HW weekly",
            filters={"category": self.tcat.pk})

    def _schedule(self, **over):
        defaults = {
            "saved_report": self.sr, "schedule": "weekly",
            "recipients": ["ops@example.com"], "format": "csv",
            "enabled": True, "next_run_at": None,
        }
        defaults.update(over)
        return ScheduledReport.objects.create(**defaults)

    def _runs_for(self, sr):
        return list(
            ScheduledReportRun.objects.filter(scheduled_report=sr)
            .order_by("-started_at"))

    def _succeeded_runs_for(self, sr):
        return [
            r for r in self._runs_for(sr) if r.status == "succeeded"]

    # ---------- CRUD permissions ----------

    def test_it_staff_can_create_schedule(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "monthly",
            "recipients": ["ops@example.com", "it@example.com"],
            "format": "xlsx", "enabled": True,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["format"], "xlsx")
        sr2 = ScheduledReport.objects.get(pk=res.data["id"])
        self.assertEqual(sr2.recipients, ["ops@example.com", "it@example.com"])
        self.assertTrue(sr2.enabled)
        self.assertIsNotNone(sr2.next_run_at)

    def test_employee_cannot_create_schedule(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "weekly",
            "recipients": ["ops@example.com"], "format": "csv",
            "enabled": True,
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_invalid_schedule_payload_rejected(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "hourly",
            "recipients": ["ops@example.com"], "format": "csv",
            "enabled": True,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_schedules_scoped_to_visible_saved_reports(self):
        # Employee only sees schedules for their own + shared saved reports.
        emp_sr = SavedReport.objects.create(
            user=self.emp, report_type="ticket_category", name="Mine",
            filters={})
        ScheduledReport.objects.create(
            saved_report=emp_sr, schedule="daily",
            recipients=["e@example.com"], format="csv", enabled=True)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/scheduled-reports/")
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["saved_report"], emp_sr.pk)

    # ---------- Execution history ----------

    def test_failed_run_recorded_and_visible(self):
        sr = self._schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="failed", success=False,
            error_summary="SMTPRefused", started_at=None)
        # started_at is auto_now_add; stamp finished_at via update.
        ScheduledReportRun.objects.filter(pk=run.pk).update(
            finished_at=run.started_at)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertFalse(run.success)

        auth(self.c, self.mgr)
        res = self.c.get("/api/common/scheduled-report-runs/")
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["error_summary"], "SMTPRefused")
        self.assertEqual(rows[0]["recipient_count"], 0)

    # ---------- Failed run retry ----------

    def test_retry_failed_run_redelivers_and_skips_old(self):
        sr = self._schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="failed", success=False,
            error_summary="SMTPRefused")
        ScheduledReportRun.objects.filter(pk=run.pk).update(
            finished_at=run.started_at)

        auth(self.c, self.mgr)
        res = self.c.post(f"/api/common/scheduled-report-runs/{run.pk}/retry/",
                          {}, format="json")
        self.assertEqual(res.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.status, "skipped")
        new_runs = self._succeeded_runs_for(sr)
        self.assertEqual(len(new_runs), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_retry_requires_it_staff(self):
        sr = self._schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="failed", success=False,
            error_summary="SMTPRefused")
        ScheduledReportRun.objects.filter(pk=run.pk).update(
            finished_at=run.started_at)
        auth(self.c, self.emp)
        res = self.c.post(f"/api/common/scheduled-report-runs/{run.pk}/retry/",
                          {}, format="json")
        self.assertEqual(res.status_code, 403)
