"""Additional PostgreSQL-only outbox concurrency tests.

Covers stale worker finalization, cancellation race, and retry exhaustion.
Skipped on SQLite.
"""

import threading
from unittest import mock, skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from accounts.tests import make_users
from common.models import NotificationOutboxEvent
from common.outbox import cancel_event, claim_event, deliver_event_core, enqueue_email

LOCMEM = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def _is_postgresql():
    return connection.vendor == "postgresql"


@skipUnless(_is_postgresql(), "PostgreSQL-only: requires real row locks/constraints (SQLite skipped)")
@override_settings(**LOCMEM)
class NotificationOutboxConcurrencyExtraPostgresTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def _enqueue(self, **kw):
        kw.setdefault("wakeup", False)
        kw.setdefault("event_type", "test.email")
        kw.setdefault("to_email", self.emp.email)
        kw.setdefault("subject", "S")
        kw.setdefault("recipient", self.emp)
        return enqueue_email(**kw)

    def test_stale_worker_cannot_finalize_after_reclaim(self):
        ev = self._enqueue()
        self.assertTrue(claim_event(ev.id, worker_id="worker-a"))
        # Expire lease and let worker-b reclaim.
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            status="retry",
            lease_expires_at=None,
            claimed_by="",
            next_attempt_at=timezone.now(),
        )
        self.assertTrue(claim_event(ev.id, worker_id="worker-b"))

        # Stale worker-a tries to finalize - should not own the row.
        from common.outbox import finalize_event
        result = finalize_event(ev.id, worker_id="worker-a", outcome="delivered", error="")
        self.assertIsNone(result)

        ev.refresh_from_db()
        self.assertEqual(ev.status, "processing")
        self.assertEqual(ev.claimed_by, "worker-b")

    def test_cancellation_race_prevents_late_delivery(self):
        ev = self._enqueue()
        self.assertTrue(claim_event(ev.id, worker_id="worker-a"))

        barrier = threading.Barrier(2)
        outcomes = [None, None]
        errors = [None, None]

        def do_cancel():
            try:
                close_old_connections()
                barrier.wait(timeout=15)
                ok, _ = cancel_event(ev.id, reason="race")
                outcomes[0] = ok
            except Exception as exc:  # noqa: BLE001
                errors[0] = exc
            finally:
                connections.close_all()

        def do_finalize():
            try:
                close_old_connections()
                barrier.wait(timeout=15)
                from common.outbox import finalize_event
                outcomes[1] = finalize_event(ev.id, worker_id="worker-a", outcome="delivered", error="")
            except Exception as exc:  # noqa: BLE001
                errors[1] = exc
            finally:
                connections.close_all()

        t1 = threading.Thread(target=do_cancel)
        t2 = threading.Thread(target=do_finalize)
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)
        for e in errors:
            if e is not None:
                raise e

        ev.refresh_from_db()
        self.assertIn(ev.status, ("cancelled", "delivered"))
        # No invalid state; if cancelled, it must not be delivered later without explicit retry.
        if ev.status == "cancelled":
            self.assertEqual(deliver_event_core(ev.id), "skipped")

    def test_retry_exhaustion_becomes_terminal(self):
        ev = self._enqueue(max_attempts=2)
        # First attempt fails -> retry
        with mock.patch("accounts.email_utils.send_mail", side_effect=RuntimeError("down")):
            r1 = deliver_event_core(ev.id)
        self.assertEqual(r1, "retry")
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(next_attempt_at=timezone.now())
        with mock.patch("accounts.email_utils.send_mail", side_effect=RuntimeError("down")):
            r2 = deliver_event_core(ev.id)
        self.assertEqual(r2, "failed")
        ev.refresh_from_db()
        self.assertEqual(ev.status, "failed")
        self.assertFalse(claim_event(ev.id))