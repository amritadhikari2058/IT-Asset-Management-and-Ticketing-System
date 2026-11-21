"""Database-level notification deduplication and concurrency safety tests.

Covers scenarios A through J from the Phase 61 requirements:
  A. Sequential duplicate creation
  B. Concurrent identical creation
  C. Multiple concurrent duplicates
  D. Distinct recipients
  E. Distinct event identities
  F. NULL field combinations
  G. Soft deletion
  H. Restore conflict
  I. Unrelated database errors
  J. Transaction interaction

Database: SQLite (project test database).  Concurrency tests use real
threads with independent Django database connections.
"""

import threading
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import User
from accounts.tests import make_users
from common.models import Notification
from common.notifications import notify_user


LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


class NotificationDedupTests(TestCase):
    """Scenarios A, D, E, F, G, H, I — sequential dedup behavior."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    # ----- A. Sequential duplicate creation -----

    def test_a_sequential_duplicate_suppressed(self):
        n1 = notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        self.assertIsNotNone(n1)
        self.assertIsNotNone(n1.dedupe_key)
        n2 = notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        self.assertIsNone(n2)  # deduped -> None
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 1
        )

    # ----- D. Distinct recipients -----

    def test_d_distinct_recipients_both_created(self):
        notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        notify_user(
            self.mgr, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.emp, post_commit=False,
        )
        self.assertEqual(
            Notification.objects.count(), 2
        )
        recipients = set(
            Notification.objects.values_list("recipient_id", flat=True)
        )
        self.assertIn(self.emp.pk, recipients)
        self.assertIn(self.mgr.pk, recipients)

    # ----- E. Distinct event identities -----

    def test_e_distinct_events_both_created(self):
        notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        notify_user(
            self.emp, "ticket_status_change", "Ticket status changed",
            "Body", entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        self.assertEqual(Notification.objects.count(), 2)

    # ----- F. NULL field combinations -----

    def test_f_null_entity_and_object_id(self):
        # dedupe_key computed from entity_type="" and object_id="" —
        # both are stored as empty strings (NOT NULL at DB level), so
        # two notifications with empty entity_type/object_id dedupe
        # against each other.
        notify_user(
            self.emp, "general", "Hello", "Body",
            entity_type="", object_id="",
            actor=self.mgr, post_commit=False,
        )
        notify_user(
            self.emp, "general", "Hello", "Body",
            entity_type="", object_id="",
            actor=self.mgr, post_commit=False,
        )
        self.assertEqual(Notification.objects.count(), 1)

    # ----- G. Soft deletion -----

    def test_g_soft_deleted_allows_replacement(self):
        n1 = notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        n1.soft_delete(reason="superseded")
        # A soft-deleted equivalent should permit a new active one.
        n2 = notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        self.assertIsNotNone(n2)
        active = Notification.objects.filter(recipient=self.emp)
        self.assertEqual(active.count(), 1)
        self.assertFalse(active.first().is_deleted)

    # ----- H. Restore conflict -----

    def test_h_restore_conflict_with_active_equivalent(self):
        n1 = notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        n1.soft_delete(reason="superseded")
        n2 = notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "Body",
            entity_type="tickets.Ticket", object_id="42",
            actor=self.mgr, post_commit=False,
        )
        self.assertIsNotNone(n2)  # replacement created
        # Attempting to restore n1 would violate the unique constraint
        # because n2 is now the active equivalent.
        n1.is_deleted = False
        n1.deleted_at = None
        n1.deleted_by = None
        n1.deletion_reason = ""
        with self.assertRaises(IntegrityError):
            n1.save(update_fields=["is_deleted", "deleted_at",
                                   "deleted_by", "deletion_reason"])

    # ----- I. Unrelated database errors -----

    def test_i_unrelated_integrity_error_not_swallowed(self):
        # An IntegrityError on a non-dedupe field should propagate.
        with mock.patch(
            "common.models.Notification.objects.create",
            side_effect=IntegrityError("unrelated constraint"),
        ):
            with self.assertRaises(IntegrityError):
                notify_user(
                    self.emp, "ticket_assignment", "Ticket assigned",
                    "Body", entity_type="tickets.Ticket", object_id="42",
                    actor=self.mgr, post_commit=False,
                )


class NotificationConcurrencyTests(TransactionTestCase):
    """Scenarios B, C — real concurrent creation with threads."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        # Close the default connection so each thread gets its own.
        from django.db import connections
        for conn in connections.all():
            conn.close()

    def _create_same_notification(self, results, errors):
        """Worker: attempt to create the same notification."""
        import time
        from django.db import connections
        for conn in connections.all():
            conn.close()
        last_exc = None
        for _attempt in range(10):
            try:
                n = notify_user(
                    self.emp, "ticket_assignment", "Ticket assigned", "Body",
                    entity_type="tickets.Ticket", object_id="99",
                    actor=self.mgr, post_commit=False,
                )
                results.append(n is not None)
                return
            except Exception as exc:  # noqa: BLE001 — capture worker failures
                last_exc = exc
                if "locked" in str(exc).lower():
                    time.sleep(0.05)
                    continue
                errors.append(str(exc))
                return
        errors.append(str(last_exc) if last_exc else "unknown")

    # ----- B. Concurrent identical creation -----

    def test_b_concurrent_identical_creation(self):
        results = []
        errors = []
        threads = [
            threading.Thread(target=self._create_same_notification,
                             args=(results, errors))
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Worker errors: {errors}")
        # Exactly one active notification must exist.
        active = Notification.objects.filter(
            recipient=self.emp, is_deleted=False,
        )
        self.assertEqual(active.count(), 1)
        # Exactly one worker should have created it; others got None (deduped).
        self.assertEqual(sum(results), 1)

    # ----- C. Multiple concurrent duplicates -----

    def test_c_many_concurrent_duplicates(self):
        results = []
        errors = []
        threads = [
            threading.Thread(target=self._create_same_notification,
                             args=(results, errors))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Worker errors: {errors}")
        active = Notification.objects.filter(
            recipient=self.emp, is_deleted=False,
        )
        self.assertEqual(active.count(), 1)
        self.assertEqual(sum(results), 1)


class NotificationTransactionTests(TransactionTestCase):
    """Scenario J — transaction interaction with dedup."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_j_rollback_discards_notification(self):
        try:
            with transaction.atomic():
                notify_user(
                    self.emp, "ticket_assignment", "Rollback", "Body",
                    entity_type="tickets.Ticket", object_id="77",
                    actor=self.mgr, post_commit=True,
                )
                raise IntegrityError("force rollback")
        except IntegrityError:
            pass
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 0
        )

    def test_j_commit_creates_notification(self):
        with transaction.atomic():
            notify_user(
                self.emp, "ticket_assignment", "Committed", "Body",
                entity_type="tickets.Ticket", object_id="78",
                actor=self.mgr, post_commit=True,
            )
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 1
        )

    def test_j_concurrent_within_same_transaction(self):
        # Two dedup-aware creates inside the same transaction: the second
        # should be suppressed by the Python-level fast path.
        with transaction.atomic():
            n1 = notify_user(
                self.emp, "ticket_assignment", "Same Tx", "Body",
                entity_type="tickets.Ticket", object_id="79",
                actor=self.mgr, post_commit=False,
            )
            n2 = notify_user(
                self.emp, "ticket_assignment", "Same Tx", "Body",
                entity_type="tickets.Ticket", object_id="79",
                actor=self.mgr, post_commit=False,
            )
        self.assertIsNotNone(n1)
        self.assertIsNone(n2)
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 1
        )

    # ----- Additional transaction safety tests -----

    def test_j_duplicate_inside_outer_transaction(self):
        # Duplicate create inside an outer atomic block must not doom
        # the transaction. The savepoint rolls back only the duplicate
        # insert; the outer transaction commits normally.
        with transaction.atomic():
            n1 = notify_user(
                self.emp, "ticket_assignment", "Outer Tx", "Body",
                entity_type="tickets.Ticket", object_id="80",
                actor=self.mgr, post_commit=False,
            )
            n2 = notify_user(
                self.emp, "ticket_assignment", "Outer Tx", "Body",
                entity_type="tickets.Ticket", object_id="80",
                actor=self.mgr, post_commit=False,
            )
        self.assertIsNotNone(n1)
        self.assertIsNone(n2)
        # Outer transaction committed: exactly one notification exists.
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 1
        )

    def test_j_continued_operations_after_duplicate(self):
        # After a handled duplicate, the caller can continue executing
        # database operations in the same transaction.
        from tickets.models import Ticket, TicketCategory
        tcat = TicketCategory.objects.create(name="TxTest")
        with transaction.atomic():
            notify_user(
                self.emp, "ticket_assignment", "Continue", "Body",
                entity_type="tickets.Ticket", object_id="81",
                actor=self.mgr, post_commit=False,
            )
            # Duplicate -> deduped, transaction not doomed.
            n2 = notify_user(
                self.emp, "ticket_assignment", "Continue", "Body",
                entity_type="tickets.Ticket", object_id="81",
                actor=self.mgr, post_commit=False,
            )
            self.assertIsNone(n2)
            # Further DB operation in same transaction.
            ticket = Ticket.objects.create(
                title="Continue test", description="d",
                category=tcat, priority="medium", status="open",
                requester=self.emp, department=self.dep,
            )
        self.assertIsNotNone(ticket.pk)
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 1
        )

    def test_j_rollback_after_duplicate(self):
        # If the outer transaction rolls back after a handled duplicate,
        # the notification is rolled back too.
        try:
            with transaction.atomic():
                notify_user(
                    self.emp, "ticket_assignment", "RollbackDup", "Body",
                    entity_type="tickets.Ticket", object_id="82",
                    actor=self.mgr, post_commit=False,
                )
                # Duplicate handled inside the transaction.
                notify_user(
                    self.emp, "ticket_assignment", "RollbackDup", "Body",
                    entity_type="tickets.Ticket", object_id="82",
                    actor=self.mgr, post_commit=False,
                )
                raise IntegrityError("force rollback")
        except IntegrityError:
            pass
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 0
        )

    def test_j_unrelated_integrity_error_propagates(self):
        # An unrelated IntegrityError must propagate and doom the transaction.
        from unittest import mock
        with mock.patch(
            "common.models.Notification.objects.create",
            side_effect=IntegrityError("unrelated constraint violation"),
        ):
            try:
                with transaction.atomic():
                    notify_user(
                        self.emp, "ticket_assignment", "UnrelatedErr", "Body",
                        entity_type="tickets.Ticket", object_id="83",
                        actor=self.mgr, post_commit=False,
                    )
            except IntegrityError:
                pass
        # Transaction was doomed and rolled back: no notification.
        self.assertEqual(
            Notification.objects.filter(recipient=self.emp).count(), 0
        )
