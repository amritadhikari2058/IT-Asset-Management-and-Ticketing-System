"""PostgreSQL-only concurrency tests for the notification outbox.

These require real PostgreSQL row locking / constraints and independent
connections. They are skipped on SQLite, so the PostgreSQL CI job must run
them (``.github/workflows/backend.yml``) for the concurrency guarantees to be
verified.
"""
import threading
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from accounts.tests import make_users
from common.models import NotificationOutboxEvent
from common.outbox import (
    claim_batch, claim_event, deliver_event_core, enqueue_email,
    recover_expired_claims,
)

LOCMEM = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def _is_postgresql():
    return connection.vendor == "postgresql"


@skipUnless(_is_postgresql(),
            "PostgreSQL-only: requires real row locks/constraints "
            "(SQLite skipped)")
@override_settings(**LOCMEM)
class NotificationOutboxConcurrencyPostgresTests(TransactionTestCase):
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

    def _run_concurrent(self, fn1, fn2):
        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(idx, fn):
            try:
                close_old_connections()
                barrier.wait(timeout=15)
                results[idx] = fn()
            except Exception as exc:  # noqa: BLE001
                errors[idx] = exc
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, fn1))
        t2 = threading.Thread(target=worker, args=(1, fn2))
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)
        self.assertFalse(t1.is_alive() or t2.is_alive(),
                         "Concurrent workers did not complete in time")
        for e in errors:
            if e is not None:
                raise e
        return results[0], results[1]

    def test_two_workers_claim_same_event_only_one_wins(self):
        ev = self._enqueue()
        r1, r2 = self._run_concurrent(
            lambda: claim_event(ev.id, worker_id="w1"),
            lambda: claim_event(ev.id, worker_id="w2"))
        self.assertEqual(sorted([r1, r2]), [False, True])
        ev.refresh_from_db()
        self.assertEqual(ev.status, "processing")
        self.assertEqual(ev.attempts, 1)

    def test_workers_claim_separate_events(self):
        e1 = self._enqueue(subject="1")
        e2 = self._enqueue(subject="2")
        a = claim_batch(10, worker_id="batchA")
        b = claim_batch(10, worker_id="batchB")
        # The two batches never overlap.
        self.assertEqual(set(a) & set(b), set())
        claimed = set(a) | set(b)
        self.assertEqual(claimed, {e1.id, e2.id})

    def test_concurrent_duplicate_registration_yields_one_row(self):
        before = NotificationOutboxEvent.objects.count()

        def reg():
            close_old_connections()
            try:
                enqueue_email(event_type="dup.email", to_email=self.emp.email,
                              subject="Same", body="B", ticket_id=99,
                              recipient=self.emp, wakeup=False)
                return "ok"
            except Exception as exc:  # noqa: BLE001
                return type(exc).__name__
            finally:
                connections.close_all()

        r1, r2 = self._run_concurrent(reg, reg)
        self.assertEqual(sorted([r1, r2]), ["ok", "ok"])
        created = NotificationOutboxEvent.objects.filter(
            event_type="dup.email").count()
        # Exactly one logical delivery row despite the race.
        self.assertEqual(created, 1)
        self.assertEqual(
            NotificationOutboxEvent.objects.count(), before + 1)

    def test_concurrent_single_delivery_of_same_event(self):
        ev = self._enqueue()
        r1, r2 = self._run_concurrent(
            lambda: deliver_event_core(ev.id),
            lambda: deliver_event_core(ev.id))
        # Exactly one worker performed the delivery; the other skipped.
        self.assertEqual(sorted([r1, r2]), ["delivered", "skipped"])
        ev.refresh_from_db()
        self.assertEqual(ev.status, "delivered")
        self.assertEqual(ev.attempts, 1)

    def test_expired_lease_recovered_and_reclaimed(self):
        ev = self._enqueue()
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            status="processing", attempts=1, claimed_by="dead",
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=30))
        recovered = recover_expired_claims()
        self.assertEqual(recovered, 1)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "retry")
        # A worker can now reclaim it.
        self.assertTrue(claim_event(ev.id, worker_id="after-recovery"))
        ev.refresh_from_db()
        self.assertEqual(ev.status, "processing")

    def test_transaction_rollback_removes_event_pg(self):
        from django.db import transaction
        before = NotificationOutboxEvent.objects.count()
        try:
            with transaction.atomic():
                self._enqueue()
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        self.assertEqual(NotificationOutboxEvent.objects.count(), before)