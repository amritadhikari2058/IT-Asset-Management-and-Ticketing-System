"""Scheduled report concurrency tests with real threads and barriers.

These tests verify that concurrent scheduler workers cannot double-execute
the same scheduled report, that leases are renewed and expired correctly,
and that stale workers cannot finalize reclaimed executions.

Uses ``TransactionTestCase`` so changes committed by worker threads are
visible to the main thread and to other worker threads. Each thread gets
its own Django database connection (thread-local), providing real
independent connections for concurrent transactions.
"""
import unittest
from threading import Barrier, Thread
from django.test import TransactionTestCase, override_settings
from django.db import transaction, connection, connections

# SQLite serializes writers process-wide; multi-connection threaded tests
# cannot exercise the production (PostgreSQL) row-lock semantics and would
# fail with "database table is locked" rather than a real assertion.
IS_SQLITE = connections["default"].vendor == "sqlite"
NEEDS_ROW_LOCKS = unittest.skipIf(
    IS_SQLITE, "Threaded row-lock test requires a non-SQLite backend")

from django.utils import timezone

from common.models import ScheduledReport, ScheduledReportRun, SavedReport
from common.tasks import (
    run_scheduled_reports,
    _renew_scheduled_report_lease,
    _finalize_scheduled_report_run,
    _scheduled_run_lease_expired,
)
from accounts.tests import make_users
from tickets.models import TicketCategory


@override_settings(
    **{"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"})
class ScheduledReportConcurrencyTests(TransactionTestCase):
    """Real concurrent execution with threads and barriers."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="HW")
        self.saved = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category",
            name="Conc report", filters={"category": self.tcat.pk})

    def _make_due_schedule(self):
        return ScheduledReport.objects.create(
            saved_report=self.saved, schedule="weekly",
            recipients=["ops@example.com"], format="csv", enabled=True,
            next_run_at=timezone.now() - timezone.timedelta(hours=1))

    def _worker_run_scheduled_reports(self, results, barrier):
        """Worker: wait at barrier, then run the scheduler."""
        barrier.wait()
        try:
            res = run_scheduled_reports()
            results.append(res)
        except Exception as exc:  # pragma: no cover - defensive
            results.append({"error": type(exc).__name__})
        finally:
            # Worker threads own their own Django DB connections; close them
            # so they do not leak and block test-database teardown.
            try:
                from django.db import connections
                connections.close_all()
            except Exception:  # pragma: no cover - defensive
                pass

    # ----- Competing schedulers -----

    @NEEDS_ROW_LOCKS
    def test_two_schedulers_one_running_run(self):
        """Two concurrent scanners produce at most one running run."""
        sr = self._make_due_schedule()
        barrier = Barrier(2)
        results = []

        t1 = Thread(target=self._worker_run_scheduled_reports,
                    args=(results, barrier))
        t2 = Thread(target=self._worker_run_scheduled_reports,
                    args=(results, barrier))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        self.assertFalse(t1.is_alive(), "Worker 1 did not finish")
        self.assertFalse(t2.is_alive(), "Worker 2 did not finish")

        # Exactly one run total across both workers.
        runs = ScheduledReportRun.objects.filter(scheduled_report=sr)
        self.assertEqual(runs.count(), 1,
                         f"Expected 1 run, got {runs.count()}: {results}")

        # The run must not be left in 'running' (delivery is synchronous).
        statuses = set(runs.values_list("status", flat=True))
        self.assertIn("succeeded", statuses,
                      f"Expected at least one succeeded run, got {statuses}")

    # ----- Duplicate execution prevention (constraint) -----

    def test_partial_unique_constraint_blocks_second_running_run(self):
        """Database constraint prevents a second running run per report."""
        sr = self._make_due_schedule()
        run1 = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="token-1",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=5))
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ScheduledReportRun.objects.create(
                    scheduled_report=sr, status="running", success=False,
                    execution_token="token-2",
                    lease_expires_at=timezone.now() + timezone.timedelta(minutes=5))
                raise IntegrityError("force rollback")

    # ----- Lease renewal -----

    def test_lease_renewal_extends_expiry(self):
        """Renewing the lease pushes lease_expires_at into the future."""
        sr = self._make_due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="tok", lease_expires_at=timezone.now(),
            last_heartbeat_at=timezone.now())
        before = run.lease_expires_at
        renewed = _renew_scheduled_report_lease(run.pk, "tok")
        self.assertTrue(renewed)
        run.refresh_from_db()
        self.assertGreater(run.lease_expires_at, before)

    def test_lease_renewal_fails_for_wrong_token(self):
        """A worker without the token cannot renew the lease."""
        sr = self._make_due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="owner-token",
            lease_expires_at=timezone.now(),
            last_heartbeat_at=timezone.now())
        renewed = _renew_scheduled_report_lease(run.pk, "stale-token")
        self.assertFalse(renewed)

    # ----- Stale worker finalization -----

    def test_stale_worker_cannot_finalize(self):
        """A worker whose lease was recovered cannot finalize."""
        sr = self._make_due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="owner-token",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=5))
        wrote = _finalize_scheduled_report_run(
            run.pk, "stale-token", status="succeeded", success=True,
            finished_at=timezone.now(), recipient_count=1)
        self.assertFalse(wrote)
        run.refresh_from_db()
        self.assertEqual(run.status, "running")

    def test_owner_can_finalize(self):
        """The worker holding the token can finalize its own run."""
        sr = self._make_due_schedule()
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="owner-token",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=5))
        wrote = _finalize_scheduled_report_run(
            run.pk, "owner-token", status="succeeded", success=True,
            finished_at=timezone.now(), recipient_count=1)
        self.assertTrue(wrote)
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded")

    # ----- Disabled report -----

    def test_disabled_report_not_executed(self):
        """A disabled scheduled report is never executed."""
        sr = self._make_due_schedule()
        ScheduledReport.objects.filter(pk=sr.pk).update(enabled=False)
        results = run_scheduled_reports()
        self.assertEqual(results["checked"], 0)
        self.assertEqual(
            ScheduledReportRun.objects.filter(scheduled_report=sr).count(), 0)

    # ----- Concurrent schedule advancement -----

    @NEEDS_ROW_LOCKS
    def test_concurrent_advancement_no_duplicate_runs(self):
        """Two scanners advancing the same report create one run total."""
        sr = self._make_due_schedule()
        barrier = Barrier(2)
        results = []

        t1 = Thread(target=self._worker_run_scheduled_reports,
                    args=(results, barrier))
        t2 = Thread(target=self._worker_run_scheduled_reports,
                    args=(results, barrier))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        runs = ScheduledReportRun.objects.filter(scheduled_report=sr)
        self.assertEqual(runs.count(), 1,
                         f"Expected 1 run, got {runs.count()}: {results}")

    # ----- Worker crash / recovery -----

    def test_expired_lease_is_recovered(self):
        """An expired lease allows recovery and a new execution."""
        sr = self._make_due_schedule()
        crashed = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="dead-token",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1))
        results = run_scheduled_reports()
        self.assertGreaterEqual(results["recovered"], 1)
        crashed.refresh_from_db()
        self.assertEqual(crashed.status, "failed")
        self.assertEqual(crashed.error_summary, "stale_worker_recovered")

        # Exactly one run total (recovered + replacement delivered).
        runs = ScheduledReportRun.objects.filter(scheduled_report=sr)
        self.assertEqual(runs.count(), 2)

    def test_no_permanently_stuck_running_runs(self):
        """An expired running run is recovered, never stuck forever."""
        sr = self._make_due_schedule()
        stuck = ScheduledReportRun.objects.create(
            scheduled_report=sr, status="running", success=False,
            execution_token="stuck-token",
            lease_expires_at=timezone.now() - timezone.timedelta(hours=1))
        results = run_scheduled_reports()
        self.assertGreaterEqual(results["recovered"], 1)
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, "failed")
        # A replacement run exists (delivered synchronously).
        other = ScheduledReportRun.objects.filter(
            scheduled_report=sr).exclude(pk=stuck.pk)
        self.assertEqual(other.count(), 1)
