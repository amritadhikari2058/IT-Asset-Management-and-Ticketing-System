"""Scheduled report management: CRUD permissions, history, and retry."""
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from common.tasks import (
    _finalize_scheduled_report_run,
    _renew_scheduled_report_lease,
    _scheduled_run_lease_expired,
    run_scheduled_reports,
)
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
    # ---------- Lease and heartbeat tests ----------

    def _due_schedule(self):
        sr = self._schedule()
        ScheduledReport.objects.filter(pk=sr.pk).update(
            next_run_at=timezone.now() - timezone.timedelta(hours=1))
        sr.refresh_from_db()
        return sr

    def test_long_running_report_not_recovered_prematurely(self):
        """A live lease protects a legitimately long-running report."""
        sr = self._due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=4),
            execution_token="live-token",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=1))
        results = run_scheduled_reports()
        self.assertEqual(results["checked"], 1)
        # Not reclaimed while the lease is still valid.
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="failed").count(), 0)
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="running").count(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, "running")

    def test_heartbeat_renews_lease_during_long_run(self):
        """Renewing the lease keeps ownership even past the fixed window."""
        sr = self._due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=30),
            execution_token="beating-token",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=1),
            last_heartbeat_at=timezone.now())
        # Simulate a heartbeat renewal extending the lease.
        renewed = _renew_scheduled_report_lease(run.pk, "beating-token")
        self.assertTrue(renewed)
        run.refresh_from_db()
        self.assertGreater(run.lease_expires_at, timezone.now())
        results = run_scheduled_reports()
        self.assertEqual(results["checked"], 1)
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="failed").count(), 0)
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="running").count(), 1)

    def test_crashed_worker_recovery_after_lease_expire(self):
        """An expired lease makes a crashed execution recoverable."""
        sr = self._due_schedule()
        crashed = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=6),
            execution_token="dead-token",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1))
        results = run_scheduled_reports()
        self.assertEqual(results["checked"], 1)
        self.assertGreaterEqual(results["recovered"], 1)
        crashed.refresh_from_db()
        self.assertEqual(crashed.status, "failed")
        self.assertEqual(crashed.error_summary, "stale_worker_recovered")
        # A fresh execution replaced the recovered one and delivered.
        new_runs = ScheduledReportRun.objects.filter(
            scheduled_report=sr, status="succeeded")
        self.assertEqual(new_runs.count(), 1)
        self.assertNotEqual(new_runs.first().pk, crashed.pk)

    def test_crashed_worker_recovery_when_schedule_already_advanced(self):
        """A crash after next_run_at advanced must still be recovered.

        Regression: recovery used to scan only due schedules, so a worker
        that crashed after advancing next_run_at left its run ``running``
        until the next scheduled period (a week for weekly reports).
        """
        sr = self._schedule()
        ScheduledReport.objects.filter(pk=sr.pk).update(
            next_run_at=timezone.now() + timezone.timedelta(days=6))
        crashed = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=6),
            execution_token="dead-token",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1))
        results = run_scheduled_reports()
        self.assertEqual(results["recovered"], 1)
        self.assertEqual(results["sent"], 1)
        crashed.refresh_from_db()
        self.assertEqual(crashed.status, "failed")
        self.assertEqual(crashed.error_summary, "stale_worker_recovered")
        sr.refresh_from_db()
        self.assertGreater(sr.next_run_at, timezone.now())
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="succeeded").count(), 1)

    def test_legacy_run_without_lease_uses_started_at_grace(self):
        """Pre-lease rows fall back to the started_at grace window."""
        sr = self._due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False)
        # started_at is auto_now_add, so stamp the legacy age via update.
        ScheduledReportRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timezone.timedelta(minutes=1))
        run.refresh_from_db()
        self.assertIsNone(run.lease_expires_at)
        self.assertFalse(_scheduled_run_lease_expired(run))
        ScheduledReportRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timezone.timedelta(minutes=6))
        run.refresh_from_db()
        self.assertTrue(_scheduled_run_lease_expired(run))

    def test_recovery_is_single_winner(self):
        """The optimistic recovery guard lets exactly one scanner win."""
        sr = self._due_schedule()
        crashed = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=6),
            execution_token="dead-token",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1))
        # Two scanners both observed the same expired lease. Apply the
        # recovery update the task uses, twice: only the first matches.
        def recover():
            return ScheduledReportRun.objects.filter(
                pk=crashed.pk, status="running",
                lease_expires_at=crashed.lease_expires_at,
                execution_token=crashed.execution_token,
            ).update(status="failed", success=False,
                     error_summary="stale_worker_recovered",
                     finished_at=timezone.now())

        first = recover()
        second = recover()
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)

    def test_stale_worker_cannot_finalize_newer_execution(self):
        """A worker that lost ownership cannot overwrite the run state."""
        sr = self._due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="owner-token",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=5))
        # A stale worker still holding the old token tries to finalize.
        wrote = _finalize_scheduled_report_run(
            run.pk, "stale-token", status="succeeded", success=True,
            finished_at=timezone.now(), recipient_count=1)
        self.assertFalse(wrote)
        run.refresh_from_db()
        self.assertEqual(run.status, "running")
        self.assertFalse(run.success)
        # The real owner can still finalize.
        wrote = _finalize_scheduled_report_run(
            run.pk, "owner-token", status="succeeded", success=True,
            finished_at=timezone.now(), recipient_count=1)
        self.assertTrue(wrote)
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded")

    def test_lease_expiry_triggers_recovery(self):
        """An expired lease causes recovery on the next scan."""
        sr = self._due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=5.5),
            execution_token="expired-token",
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=1))
        results = run_scheduled_reports()
        self.assertEqual(results["checked"], 1)
        self.assertGreaterEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="failed").count(), 1)
        # The replacement execution runs to completion in the same scan.
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="succeeded").count(), 1)
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="running").count(), 0)


    def test_all_delivery_failures_mark_run_failed(self):
        sr = self._due_schedule()
        from unittest.mock import patch
        with patch("common.email.send_scheduled_report_email",
                   return_value=False):
            results = run_scheduled_reports()
        self.assertEqual(results["sent"], 0)
        self.assertEqual(results["failed"], 1)
        run = ScheduledReportRun.objects.get(scheduled_report=sr)
        self.assertEqual(run.status, "failed")
        self.assertFalse(run.success)
        self.assertEqual(run.error_summary, "all_deliveries_failed")
        self.assertEqual(run.recipient_count, 0)

    def test_invalid_recipient_email_rejected(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "weekly",
            "recipients": ["not-an-email"], "format": "csv",
            "enabled": True,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_blank_recipient_rejected(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "weekly",
            "recipients": ["ops@example.com", " "], "format": "csv",
            "enabled": True,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_disabled_schedule_has_no_next_run(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "daily",
            "recipients": ["ops@example.com"], "format": "csv",
            "enabled": False,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        sr = ScheduledReport.objects.get(pk=res.data["id"])
        self.assertIsNone(sr.next_run_at)

    def test_deleted_saved_report_schedule_is_skipped(self):
        sr = self._due_schedule()
        self.sr.soft_delete(by_user=self.admin, reason="test")
        results = run_scheduled_reports()
        self.assertEqual(results["failed"], 1)
        sr.refresh_from_db()
        self.assertGreater(sr.next_run_at, timezone.now())
        self.assertEqual(
            ScheduledReportRun.objects.filter(scheduled_report=sr).count(), 0)

    def test_inactive_owner_schedule_is_skipped(self):
        sr = self._due_schedule()
        self.mgr.is_active = False
        self.mgr.save(update_fields=["is_active"])
        results = run_scheduled_reports()
        self.assertEqual(results["failed"], 1)
        sr.refresh_from_db()
        self.assertGreater(sr.next_run_at, timezone.now())

    def test_employee_cannot_retry_run(self):
        sr = self._schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="failed", success=False,
            error_summary="SMTPRefused")
        auth(self.c, self.emp)
        res = self.c.post(f"/api/common/scheduled-report-runs/{run.pk}/retry/",
                          {}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_access_other_users_run(self):
        other_sr_report = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category", name="Mgr only",
            filters={})
        sr = ScheduledReport.objects.create(
            saved_report=other_sr_report, schedule="daily",
            recipients=["x@example.com"], format="csv", enabled=True)
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="succeeded", success=True)
        auth(self.c, self.emp)
        res = self.c.get(f"/api/common/scheduled-report-runs/{run.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_modify_other_users_schedule(self):
        sr = self._schedule()
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/common/scheduled-reports/{sr.pk}/",
                           {"enabled": False}, format="json")
        self.assertIn(res.status_code, (403, 404))

    def test_duplicate_recipients_deduped(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/scheduled-reports/", {
            "saved_report": self.sr.pk, "schedule": "weekly",
            "recipients": ["ops@example.com", "OPS@example.com"],
            "format": "csv", "enabled": True,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        sr = ScheduledReport.objects.get(pk=res.data["id"])
        self.assertEqual(sr.recipients, ["ops@example.com"])

class ScheduledReportLeaseTaskTests(TestCase):
    """Isolated lease tests that assert on delivery outcomes."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        tcat = TicketCategory.objects.create(name="HW")
        self.saved = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category", name="Lease report",
            filters={"category": tcat.pk})

    def _due_schedule(self):
        sr = ScheduledReport.objects.create(
            saved_report=self.saved, schedule="weekly",
            recipients=["ops@example.com"], format="csv", enabled=True,
            next_run_at=timezone.now() - timezone.timedelta(hours=1))
        return sr

    def test_successful_run_records_token_and_advanced_schedule(self):
        sr = self._due_schedule()
        before = sr.next_run_at
        results = run_scheduled_reports()
        self.assertEqual(results["sent"], 1)
        run = ScheduledReportRun.objects.get(scheduled_report=sr)
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(run.execution_token)
        self.assertIsNotNone(run.lease_expires_at)
        sr.refresh_from_db()
        self.assertGreater(sr.next_run_at, before)

    def test_recovered_schedule_does_not_double_deliver(self):
        sr = self._due_schedule()
        crashed = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            started_at=timezone.now() - timezone.timedelta(minutes=6),
            execution_token="dead",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1))
        results = run_scheduled_reports()
        self.assertEqual(results["sent"], 1)
        self.assertGreaterEqual(results["recovered"], 1)
        crashed.refresh_from_db()
        self.assertEqual(crashed.status, "failed")
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="running").count(), 0)

    def test_disabled_report_not_run(self):
        sr = self._due_schedule()
        ScheduledReport.objects.filter(pk=sr.pk).update(enabled=False)
        results = run_scheduled_reports()
        self.assertEqual(results["checked"], 0)
        self.assertEqual(
            ScheduledReportRun.objects.filter(scheduled_report=sr).count(), 0)


@override_settings(
    **{"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"})
class ScheduledReportExecutionAuthorizationTests(TestCase):
    """Direct-call report execution is authorized independently of DRF views."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = TicketCategory.objects.create(name="Authz category")
        self.staff_report = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category", name="Staff report",
            filters={})
        self.emp_report = SavedReport.objects.create(
            user=self.emp, report_type="ticket_category", name="Employee report",
            filters={})
        self.emp_sla_report = SavedReport.objects.create(
            user=self.emp, report_type="ticket_sla", name="Employee SLA",
            filters={})

    def _schedule(self, saved_report, **over):
        defaults = {
            "saved_report": saved_report, "schedule": "weekly",
            "recipients": ["ops@example.com"], "format": "csv",
            "enabled": True,
            "next_run_at": timezone.now() - timezone.timedelta(hours=1),
        }
        defaults.update(over)
        return ScheduledReport.objects.create(**defaults)

    def test_staff_owned_due_report_executes_and_delivers(self):
        sr = self._schedule(self.staff_report)
        results = run_scheduled_reports()
        self.assertEqual(results["sent"], 1, results)
        run = ScheduledReportRun.objects.get(scheduled_report=sr)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(len(mail.outbox), 1)

    def test_employee_owned_due_report_is_skipped_without_rendering(self):
        sr = self._schedule(self.emp_report)
        from unittest.mock import patch
        with patch("tickets.views.category_report") as report:
            results = run_scheduled_reports()
        report.assert_not_called()
        self.assertEqual(results["sent"], 0, results)
        self.assertEqual(results["failed"], 1, results)
        self.assertEqual(
            ScheduledReportRun.objects.filter(scheduled_report=sr).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_employee_owned_sla_report_cannot_expose_staff_data(self):
        sr = self._schedule(self.emp_sla_report)
        from unittest.mock import patch
        with patch("tickets.views.sla_report") as report:
            results = run_scheduled_reports()
        report.assert_not_called()
        self.assertEqual(results["sent"], 0, results)
        self.assertEqual(
            ScheduledReportRun.objects.filter(scheduled_report=sr).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_retry_of_employee_owned_report_fails_closed(self):
        sr = self._schedule(self.emp_report)
        old_run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="failed", success=False,
            error_summary="previous failure")
        from unittest.mock import patch
        auth(self.c, self.mgr)
        with patch("tickets.views.category_report") as report:
            res = self.c.post(
                f"/api/common/scheduled-report-runs/{old_run.pk}/retry/",
                {}, format="json")
        report.assert_not_called()
        self.assertEqual(res.status_code, 500, res.data)
        self.assertFalse(res.data["retried"])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            ScheduledReportRun.objects.filter(
                scheduled_report=sr, status="succeeded").count(), 0)

    def test_error_response_from_report_view_is_not_delivered(self):
        sr = self._schedule(self.staff_report)
        from unittest.mock import patch
        from rest_framework.response import Response
        with patch("tickets.views.category_report") as report:
            report.return_value = Response(
                {"detail": "Forbidden."}, status=403)
            results = run_scheduled_reports()
        self.assertEqual(results["sent"], 0, results)
        self.assertEqual(len(mail.outbox), 0)
        run = ScheduledReportRun.objects.get(scheduled_report=sr)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_summary, "PermissionDenied")

    def test_helper_rejects_missing_deleted_inactive_and_non_staff_owners(self):
        from rest_framework.exceptions import PermissionDenied
        from common.report_security import validate_scheduled_report_owner

        class FakeReport:
            def __init__(self, user=None, is_deleted=False):
                self.user = user
                self.is_deleted = is_deleted

        for bad in (None, FakeReport(is_deleted=True), FakeReport(),
                    FakeReport(self.emp)):
            with self.assertRaises(PermissionDenied):
                validate_scheduled_report_owner(bad)

        self.mgr.is_active = False
        with self.assertRaises(PermissionDenied):
            validate_scheduled_report_owner(FakeReport(self.mgr))
        self.mgr.is_active = True
        self.assertEqual(validate_scheduled_report_owner(self.staff_report),
                         self.mgr)

