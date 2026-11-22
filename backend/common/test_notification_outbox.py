"""Phase 66 — transactional notification outbox tests.

Coverage:
  * Transaction tests: business change and outbox event commit together, roll
    back together, nested savepoints, wake-up independence, dedupe, unrelated
    IntegrityError propagation, payload size validation.
  * Worker tests: success, temporary failure + retry scheduling, permanent
    failure, exponential backoff, expired-lease recovery, invalid/inactive
    recipient, preference opt-out, duplicate task execution, malformed payload,
    manual retry, cancellation.
  * API tests: authorization for inspect/retry/cancel and operations status.

External SMTP is mocked/faked via the locmem backend and ``send_mail`` patches;
these are unit-level checks, not real SMTP verification. PostgreSQL concurrency
lives in ``test_notification_outbox_postgres.py`` and is exercised by the CI
PostgreSQL job (``.github/workflows/backend.yml``).
"""
import random
from unittest import mock

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.tests import auth, make_users
from common.models import NotificationOutboxEvent, UserNotificationPreference
from common.outbox import (
    _backoff_seconds, cancel_event, claim_event, cleanup_outbox_events,
    deliver_event_core, enqueue_email, get_outbox_stats,
    process_pending_batch, recover_expired_claims, retry_event,
)

LOCMEM = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def _enqueue(recipient, **kw):
    """Enqueue without the on_commit wake-up (worker tests drive delivery)."""
    kw.setdefault("wakeup", False)
    kw.setdefault("event_type", "test.email")
    kw.setdefault("to_email", getattr(recipient, "email", "r@x"))
    kw.setdefault("subject", "Subject")
    kw.setdefault("body", "Body")
    kw.setdefault("recipient", recipient)
    return enqueue_email(**kw)


class OutboxTransactionTests(TransactionTestCase):
    """Business change and outbox event share one transaction fate."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_enqueue_and_business_change_commit_together(self):
        with transaction.atomic():
            ev = _enqueue(self.emp, event_type="ticket.email.created")
            self.assertIsNotNone(ev)
            self.assertEqual(
                NotificationOutboxEvent.objects.filter(pk=ev.pk).count(), 1)
        # Committed: survives independently of any callback.
        self.assertTrue(
            NotificationOutboxEvent.objects.filter(pk=ev.pk).exists())

    def test_business_rollback_removes_outbox_event(self):
        before = NotificationOutboxEvent.objects.count()
        try:
            with transaction.atomic():
                _enqueue(self.emp, event_type="ticket.email.created")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        self.assertEqual(NotificationOutboxEvent.objects.count(), before)

    def test_outer_rollback_removes_events_from_inner_savepoints(self):
        before = NotificationOutboxEvent.objects.count()
        try:
            with transaction.atomic():
                # Inner savepoint "succeeds"...
                with transaction.atomic():
                    _enqueue(self.emp, event_type="ticket.email.created")
                # ...but the outer transaction rolls back.
                raise RuntimeError("outer rollback")
        except RuntimeError:
            pass
        self.assertEqual(NotificationOutboxEvent.objects.count(), before)

    def test_event_survives_commit_without_wakeup(self):
        ev = _enqueue(self.emp, wakeup=False,
                      event_type="ticket.email.created")
        self.assertTrue(
            NotificationOutboxEvent.objects.filter(pk=ev.pk).exists())
        self.assertEqual(
            NotificationOutboxEvent.objects.get(pk=ev.pk).status, "pending")

    def test_duplicate_registration_collapses(self):
        e1 = _enqueue(self.emp, event_type="ticket.email.created",
                      subject="Same", body="B", ticket_id=1)
        e2 = _enqueue(self.emp, event_type="ticket.email.created",
                      subject="Same", body="B", ticket_id=1)
        self.assertEqual(e1.pk, e2.pk)
        self.assertEqual(
            NotificationOutboxEvent.objects.filter(
                event_type="ticket.email.created").count(), 1)

    def test_distinct_events_not_collapsed(self):
        e1 = _enqueue(self.emp, event_type="ticket.email.created", subject="A",
                      ticket_id=1)
        e2 = _enqueue(self.emp, event_type="ticket.email.created", subject="B",
                      ticket_id=1)
        self.assertNotEqual(e1.pk, e2.pk)

    def test_unrelated_integrity_error_propagates(self):
        with mock.patch(
            "common.models.NotificationOutboxEvent.objects.create",
                side_effect=IntegrityError("unrelated")):
            with self.assertRaises(IntegrityError):
                _enqueue(self.emp, event_type="ticket.email.created")

    def test_oversized_payload_rejected(self):
        with self.assertRaises(ValueError):
            _enqueue(self.emp, event_type="ticket.email.created",
                     body="x" * (NotificationOutboxEvent.MAX_PAYLOAD_BYTES + 10))

    def test_missing_recipient_returns_none(self):
        self.assertIsNone(
            enqueue_email(event_type="x", to_email="", subject="s", wakeup=False))


class OutboxWorkerTests(TestCase):
    """Claim + deliver + retry + recovery (SMTP faked via locmem / patches)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    @override_settings(**LOCMEM)
    def test_pending_event_delivered(self):
        ev = _enqueue(self.emp)
        outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "delivered")
        ev.refresh_from_db()
        self.assertEqual(ev.status, "delivered")
        self.assertIsNotNone(ev.delivered_at)
        self.assertEqual(ev.attempts, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to[0], self.emp.email)

    @override_settings(**LOCMEM)
    def test_temporary_failure_schedules_retry(self):
        ev = _enqueue(self.emp)
        with mock.patch("accounts.email_utils.send_mail",
                        side_effect=RuntimeError("smtp down")):
            outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "retry")
        ev.refresh_from_db()
        self.assertEqual(ev.status, "retry")
        self.assertEqual(ev.attempts, 1)
        self.assertIsNotNone(ev.next_attempt_at)
        self.assertGreater(ev.next_attempt_at, timezone.now())
        self.assertEqual(ev.last_error, "smtp_send_failed")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(**LOCMEM, NOTIFICATION_OUTBOX_MAX_ATTEMPTS=2)
    def test_permanent_failure_after_max_attempts(self):
        ev = _enqueue(self.emp, max_attempts=2)
        with mock.patch("accounts.email_utils.send_mail",
                        side_effect=RuntimeError("smtp down")):
            deliver_event_core(ev.id)  # attempt 1 -> retry
            ev.refresh_from_db()
            self.assertEqual(ev.status, "retry")
            # Force the retry to be due immediately.
            NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
                next_attempt_at=timezone.now())
            deliver_event_core(ev.id)  # attempt 2 -> failed
        ev.refresh_from_db()
        self.assertEqual(ev.status, "failed")
        self.assertEqual(ev.attempts, 2)

    @override_settings(**LOCMEM)
    def test_max_attempts_one_fails_immediately(self):
        ev = _enqueue(self.emp, max_attempts=1)
        with mock.patch("accounts.email_utils.send_mail",
                        side_effect=RuntimeError("down")):
            outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "failed")
        ev.refresh_from_db()
        self.assertEqual(ev.status, "failed")

    def test_exponential_backoff_increases_and_is_bounded(self):
        rng = random.Random(1234)
        with override_settings(NOTIFICATION_OUTBOX_RETRY_BASE_SECONDS=30,
                               NOTIFICATION_OUTBOX_RETRY_MAX_SECONDS=3600):
            b1 = _backoff_seconds(1, rng=rng)
            b2 = _backoff_seconds(2, rng=rng)
            b3 = _backoff_seconds(3, rng=rng)
            b_big = _backoff_seconds(50, rng=rng)
        self.assertGreater(b2, b1)
        self.assertGreater(b3, b2)
        self.assertLessEqual(b_big, 3600)

    @override_settings(**LOCMEM)
    def test_expired_lease_recovered_then_delivered(self):
        ev = _enqueue(self.emp)
        # Simulate a worker that claimed then crashed.
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            status="processing", attempts=1,
            claimed_by="dead-worker",
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=10))
        recovered = recover_expired_claims()
        self.assertEqual(recovered, 1)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "retry")
        # And the retry then delivers.
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            next_attempt_at=timezone.now())
        outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "delivered")

    @override_settings(**LOCMEM)
    def test_expired_lease_max_attempts_marks_failed(self):
        ev = _enqueue(self.emp, max_attempts=1)
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            status="processing", attempts=1, claimed_by="dead",
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=5))
        recover_expired_claims()
        ev.refresh_from_db()
        self.assertEqual(ev.status, "failed")

    @override_settings(**LOCMEM)
    def test_inactive_recipient_cancelled(self):
        ev = _enqueue(self.emp)
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "cancelled")
        ev.refresh_from_db()
        self.assertEqual(ev.status, "cancelled")
        self.assertEqual(ev.cancel_reason, "recipient_inactive_or_deleted")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(**LOCMEM)
    def test_preference_opt_out_at_delivery(self):
        prefs, _ = UserNotificationPreference.objects.get_or_create(
            user=self.emp)
        prefs.email_enabled = False
        prefs.save()
        ev = _enqueue(self.emp, category="ticket_assignment")
        outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "cancelled")
        ev.refresh_from_db()
        self.assertEqual(ev.cancel_reason, "recipient_opted_out")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(**LOCMEM)
    def test_category_opt_out_only_affects_that_category(self):
        prefs, _ = UserNotificationPreference.objects.get_or_create(
            user=self.emp)
        prefs.email_enabled = True
        prefs.categories = {"ticket_assignment": False}
        prefs.save()
        ev = _enqueue(self.emp, category="ticket_status_change")
        outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "delivered")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**LOCMEM)
    def test_duplicate_task_execution_is_idempotent(self):
        ev = _enqueue(self.emp)
        self.assertEqual(deliver_event_core(ev.id), "delivered")
        # A second delivery attempt must be a no-op (already delivered).
        self.assertEqual(deliver_event_core(ev.id), "skipped")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**LOCMEM)
    def test_malformed_payload_still_delivers(self):
        ev = _enqueue(self.emp)
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            payload=["not", "a", "dict"])
        outcome = deliver_event_core(ev.id)
        self.assertEqual(outcome, "delivered")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**LOCMEM)
    def test_cancel_pending_event_prevents_delivery(self):
        ev = _enqueue(self.emp)
        ok, result = cancel_event(ev.id, reason="test cancel")
        self.assertTrue(ok)
        self.assertEqual(result.status, "cancelled")
        # Worker can no longer claim it.
        self.assertFalse(claim_event(ev.id))
        self.assertEqual(deliver_event_core(ev.id), "skipped")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(**LOCMEM)
    def test_manual_retry_of_failed_event(self):
        ev = _enqueue(self.emp, max_attempts=1)
        with mock.patch("accounts.email_utils.send_mail",
                        side_effect=RuntimeError("down")):
            deliver_event_core(ev.id)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "failed")
        ok, result = retry_event(ev.id)
        self.assertTrue(ok)
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.attempts, 0)
        # Now delivers.
        self.assertEqual(deliver_event_core(ev.id), "delivered")
        ev.refresh_from_db()
        self.assertEqual(ev.status, "delivered")

    def test_retry_rejects_delivered_event(self):
        ev = _enqueue(self.emp)
        with override_settings(**LOCMEM):
            deliver_event_core(ev.id)
        ok, reason = retry_event(ev.id)
        self.assertFalse(ok)
        self.assertIn("not_retryable", reason)

    @override_settings(**LOCMEM)
    def test_process_pending_batch_delivers_due_events(self):
        e1 = _enqueue(self.emp, event_type="a.one", subject="1")
        e2 = _enqueue(self.emp, event_type="a.two", subject="2")
        # A third event scheduled for the future must not be delivered.
        future = _enqueue(self.emp, event_type="a.future", subject="3")
        NotificationOutboxEvent.objects.filter(pk=future.pk).update(
            status="retry",
            next_attempt_at=timezone.now() + timezone.timedelta(hours=1))
        results = process_pending_batch(batch_size=10)
        self.assertEqual(results["delivered"], 2)
        e1.refresh_from_db(); e2.refresh_from_db(); future.refresh_from_db()
        self.assertEqual(e1.status, "delivered")
        self.assertEqual(e2.status, "delivered")
        self.assertEqual(future.status, "retry")
        self.assertEqual(len(mail.outbox), 2)

    def test_stats_aggregation(self):
        _enqueue(self.emp, event_type="s.one", subject="1")
        _enqueue(self.emp, event_type="s.two", subject="2")
        stats = get_outbox_stats()
        self.assertEqual(stats["pending"], 2)
        self.assertIn("oldest_pending_age_seconds", stats)
        self.assertIn("recent_failures", stats)

    def test_cleanup_removes_only_old_terminal_rows(self):
        from datetime import timedelta
        old_done = _enqueue(self.emp, event_type="old.done", subject="x")
        NotificationOutboxEvent.objects.filter(pk=old_done.pk).update(
            status="delivered", updated_at=timezone.now() - timedelta(days=40))
        recent_done = _enqueue(self.emp, event_type="recent.done", subject="y")
        NotificationOutboxEvent.objects.filter(pk=recent_done.pk).update(
            status="delivered", updated_at=timezone.now())
        active_old = _enqueue(self.emp, event_type="active.old", subject="z")
        NotificationOutboxEvent.objects.filter(pk=active_old.pk).update(
            status="pending", updated_at=timezone.now() - timedelta(days=40))
        deleted = cleanup_outbox_events(retention_days=30)
        self.assertEqual(deleted, 1)
        self.assertFalse(
            NotificationOutboxEvent.objects.filter(pk=old_done.pk).exists())
        self.assertTrue(
            NotificationOutboxEvent.objects.filter(pk=recent_done.pk).exists())
        self.assertTrue(
            NotificationOutboxEvent.objects.filter(pk=active_old.pk).exists())


class OutboxAPITests(TestCase):
    """Authorization and recovery endpoints (IT staff read, admin mutate)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def _make_failed_event(self):
        ev = _enqueue(self.emp, event_type="ticket.email.created")
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            status="failed", attempts=5, last_error="smtp_send_failed")
        ev.refresh_from_db()
        return ev

    def test_list_requires_it_staff(self):
        # Anonymous -> 401/403.
        from rest_framework.test import APIClient
        c = APIClient()
        res = c.get("/api/common/notification-outbox/")
        self.assertIn(res.status_code, (401, 403))

    def test_list_allowed_for_it_staff(self):
        from rest_framework.test import APIClient
        c = APIClient()
        auth(c, self.mgr)  # it_manager
        self._make_failed_event()
        res = c.get("/api/common/notification-outbox/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("stats", res.data)
        self.assertIn("events", res.data)

    def test_inspect_payload_requires_system_admin(self):
        from rest_framework.test import APIClient
        c = APIClient()
        ev = _enqueue(self.emp)
        auth(c, self.mgr)  # it_manager, not system admin
        res = c.get(f"/api/common/notification-outbox/{ev.id}/inspect/")
        self.assertEqual(res.status_code, 403)

    def test_inspect_payload_allowed_for_admin(self):
        from rest_framework.test import APIClient
        c = APIClient()
        ev = _enqueue(self.emp, subject="Secret-ish")
        auth(c, self.admin)
        res = c.get(f"/api/common/notification-outbox/{ev.id}/inspect/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("payload", res.data)

    def test_retry_requires_system_admin(self):
        from rest_framework.test import APIClient
        c = APIClient()
        ev = self._make_failed_event()
        auth(c, self.mgr)
        res = c.post(f"/api/common/notification-outbox/{ev.id}/retry/")
        self.assertEqual(res.status_code, 403)
        # Admin succeeds.
        auth(c, self.admin)
        res = c.post(f"/api/common/notification-outbox/{ev.id}/retry/")
        self.assertEqual(res.status_code, 200)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "pending")

    def test_cancel_requires_system_admin_and_works(self):
        from rest_framework.test import APIClient
        c = APIClient()
        ev = _enqueue(self.emp)
        auth(c, self.mgr)
        res = c.post(f"/api/common/notification-outbox/{ev.id}/cancel/",
                     {"reason": "nope"}, format="json")
        self.assertEqual(res.status_code, 403)
        auth(c, self.admin)
        res = c.post(f"/api/common/notification-outbox/{ev.id}/cancel/",
                     {"reason": "duplicate"}, format="json")
        self.assertEqual(res.status_code, 200)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "cancelled")

    def test_operations_status_includes_outbox(self):
        from rest_framework.test import APIClient
        c = APIClient()
        auth(c, self.mgr)
        _enqueue(self.emp)
        res = c.get("/api/common/operations/status/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("notification_outbox", res.data)
        self.assertEqual(res.data["notification_outbox"]["pending"], 1)


class TicketOutboxIntegrationTests(TransactionTestCase):
    """The migrated ticket flow persists outbox events atomically."""

    def setUp(self):
        from rest_framework.test import APIClient
        from tickets.models import TicketCategory
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="General")
        self.client = APIClient()

    def _create(self, **over):
        self.client.force_authenticate(user=self.mgr)
        payload = {"title": "T", "description": "d", "priority": "medium",
                   "category": self.cat.pk}
        payload.update(over)
        return self.client.post("/api/tickets/", payload, format="json")

    @override_settings(**LOCMEM)
    def test_ticket_create_enqueues_outbox_events(self):
        res = self._create(assignee=self.admin.pk)
        self.assertEqual(res.status_code, 201)
        types = set(NotificationOutboxEvent.objects.values_list(
            "event_type", flat=True))
        self.assertIn("ticket.email.created", types)
        self.assertIn("ticket.email.assigned", types)

    @override_settings(**LOCMEM)
    def test_ticket_create_rollback_removes_outbox_events(self):
        before = NotificationOutboxEvent.objects.count()
        try:
            with transaction.atomic():
                self._create(assignee=self.admin.pk)
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        self.assertEqual(NotificationOutboxEvent.objects.count(), before)

    @override_settings(**LOCMEM)
    def test_ticket_status_change_enqueues_outbox_event(self):
        res = self._create()  # requester = mgr
        ticket_id = res.data["id"]
        NotificationOutboxEvent.objects.all().delete()
        self.client.force_authenticate(user=self.admin)  # staff
        upd = self.client.patch(f"/api/tickets/{ticket_id}/",
                                {"status": "in_progress"}, format="json")
        self.assertEqual(upd.status_code, 200)
        types = set(NotificationOutboxEvent.objects.values_list(
            "event_type", flat=True))
        self.assertIn("ticket.email.status_change", types)