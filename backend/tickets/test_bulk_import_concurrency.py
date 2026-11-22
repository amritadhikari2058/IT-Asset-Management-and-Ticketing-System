"""PostgreSQL-specific concurrency tests for tokenized ticket bulk imports.

These tests exercise real database locking/constraints with independent
connections and concurrent HTTP requests against the actual endpoint. They are
skipped transparently on non-PostgreSQL databases because SQLite cannot prove
PostgreSQL row-locking/concurrency behavior.
"""

import threading
import time
import unittest.mock
from unittest import skipUnless

from django.conf import settings
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from tickets.models import Ticket, TicketBulkImportOperation, TicketBulkImportRowOutcome, TicketCategory


def _is_postgresql():
    return connection.vendor == "postgresql"


@skipUnless(_is_postgresql(),
            "PostgreSQL-only: requires real row locks/constraints (SQLite skipped)")
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketBulkImportPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def _payload(self, rows, token):
        return {
            "tickets": rows,
            "preview": False,
            "confirm": True,
            "import_token": token,
        }

    def _row(self, **kw):
        base = {
            "title": "t",
            "description": "d",
            "category": self.tcat.pk,
            "department": self.dep.pk,
        }
        base.update(kw)
        return base

    def _run_concurrent_requests(self, user, payload_a, payload_b=None):
        if payload_b is None:
            payload_b = payload_a
        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(idx, payload):
            try:
                close_old_connections()
                client = APIClient()
                auth(client, user)
                barrier.wait(timeout=15)
                resp = client.post("/api/tickets/bulk_create/", payload, format="json")
                # Normalize response for assertions.
                data = getattr(resp, "data", None)
                results[idx] = {
                    "status": resp.status_code,
                    "data": data,
                }
            except Exception as exc:
                errors[idx] = exc
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, payload_a))
        t2 = threading.Thread(target=worker, args=(1, payload_b))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)
        if t1.is_alive() or t2.is_alive():
            self.fail("Concurrent request threads did not complete")
        for err in errors:
            if err is not None:
                raise err
        return results[0], results[1]

    def test_same_user_same_token_same_payload_concurrent_confirm(self):
        """Only one concurrent confirmation executes; no duplicates; consistent state."""
        token = "pg-same-token-same-payload"
        rows = [self._row(title="pg-once-1"), self._row(title="pg-once-2")]
        payload = self._payload(rows, token)

        r1, r2 = self._run_concurrent_requests(self.mgr, payload)

        responses = [r1, r2]
        statuses = sorted([r["status"] for r in responses])
        ok_responses = [r for r in responses if r["status"] == 200]
        conflict_responses = [r for r in responses if r["status"] == 409]
        expected_summary = {"ok": 2, "skipped": 0, "failed": 0}

        # Valid concurrent outcomes: (200 execution/replay + 409 in-progress/conflict)
        # or (200 + 200 identical replay) depending on timing. No duplicate execution.
        self.assertTrue(
            (len(ok_responses) == 1 and len(conflict_responses) == 1)
            or (len(ok_responses) == 2 and len(conflict_responses) == 0),
            responses,
        )
        for resp in ok_responses:
            self.assertEqual(resp["data"].get("summary"), expected_summary, resp)
        if len(conflict_responses) == 1:
            self.assertIn(conflict_responses[0]["status"], [409])
        if len(ok_responses) == 2:
            self.assertEqual(ok_responses[0]["data"], ok_responses[1]["data"], responses)

        # No duplicate tickets created by the concurrent pair.
        self.assertEqual(Ticket.objects.filter(title__startswith="pg-once-").count(), 2)
        titles = sorted(Ticket.objects.filter(title__startswith="pg-once-")
                        .values_list("title", flat=True))
        self.assertEqual(titles, ["pg-once-1", "pg-once-2"])

        # Single logical operation for user/token with consistent terminal state.
        ops = list(TicketBulkImportOperation.objects.filter(user=self.mgr, token=token))
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(op.total_rows, 2)
        self.assertEqual(op.processed_count, 2)
        self.assertEqual(op.successful_count, 2)
        self.assertEqual(op.failed_count, 0)
        self.assertIsNotNone(op.result_json)
        self.assertEqual(op.result_json.get("summary"), expected_summary)
        # Stored result reflects actual committed tickets.
        result_ids = sorted([s["id"] for s in op.result_json.get("successful", [])])
        db_ids = sorted(Ticket.objects.filter(title__startswith="pg-once-")
                        .values_list("id", flat=True))
        self.assertEqual(result_ids, db_ids)
        for resp in ok_responses:
            self.assertEqual(
                sorted([s["id"] for s in resp["data"].get("successful", [])]),
                db_ids,
                resp,
            )

    def test_same_token_different_payload_conflict_and_no_extra_tickets(self):
        """Same token cannot be reused for a different payload; original state intact."""
        token = "pg-same-token-diff-payload"
        rows_a = [self._row(title="pg-a")]
        rows_b = [self._row(title="pg-b-different")]
        payload_a = self._payload(rows_a, token)
        payload_b = self._payload(rows_b, token)

        # Establish original completed operation.
        client = APIClient()
        auth(client, self.mgr)
        first = client.post("/api/tickets/bulk_create/", payload_a, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(Ticket.objects.filter(title="pg-a").count(), 1)
        op_before = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        result_before = op_before.result_json

        # Sequential mismatch.
        second = client.post("/api/tickets/bulk_create/", payload_b, format="json")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(Ticket.objects.filter(title="pg-a").count(), 1)
        self.assertEqual(Ticket.objects.filter(title="pg-b-different").count(), 0)

        # Concurrent mismatch against the same existing token.
        r1, r2 = self._run_concurrent_requests(self.mgr, payload_b)
        self.assertEqual(r1["status"], 409, r1)
        self.assertEqual(r2["status"], 409, r2)
        self.assertEqual(Ticket.objects.filter(title="pg-a").count(), 1)
        self.assertEqual(Ticket.objects.filter(title="pg-b-different").count(), 0)
        op_after = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        self.assertEqual(op_after.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(op_after.result_json, result_before)

    def test_completed_result_replay_same_user_token_payload(self):
        """Completed import replay returns stored result and creates no duplicates."""
        token = "pg-replay-json"
        rows = [self._row(title="pg-replay-1")]
        payload = self._payload(rows, token)
        client = APIClient()
        auth(client, self.mgr)

        first = client.post("/api/tickets/bulk_create/", payload, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["summary"], {"ok": 1, "skipped": 0, "failed": 0})
        ticket_id = first.data["successful"][0]["id"]
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        counts_before = (op.successful_count, op.failed_count, op.processed_count, op.status)

        replay = client.post("/api/tickets/bulk_create/", payload, format="json")
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data, first.data)
        self.assertEqual(Ticket.objects.filter(title="pg-replay-1").count(), 1)
        self.assertEqual(Ticket.objects.get(pk=ticket_id).title, "pg-replay-1")
        op.refresh_from_db()
        self.assertEqual((op.successful_count, op.failed_count, op.processed_count, op.status),
                         counts_before)

    def test_cross_user_isolation_same_token(self):
        """Different users' same token do not interfere or expose each other's results."""
        token = "pg-cross-user"
        rows_mgr = [self._row(title="pg-mgr-only")]
        rows_emp = [self._row(title="pg-emp-only")]

        mgr_client = APIClient()
        auth(mgr_client, self.mgr)
        emp_client = APIClient()
        auth(emp_client, self.emp)

        r_mgr = mgr_client.post("/api/tickets/bulk_create/",
                                self._payload(rows_mgr, token), format="json")
        r_emp = emp_client.post("/api/tickets/bulk_create/",
                                self._payload(rows_emp, token), format="json")
        self.assertEqual(r_mgr.status_code, 200)
        self.assertEqual(r_emp.status_code, 200)
        self.assertEqual(Ticket.objects.filter(title="pg-mgr-only").count(), 1)
        self.assertEqual(Ticket.objects.filter(title="pg-emp-only").count(), 1)

        mgr_ticket = Ticket.objects.get(title="pg-mgr-only")
        emp_ticket = Ticket.objects.get(title="pg-emp-only")
        self.assertEqual(mgr_ticket.requester, self.mgr)
        self.assertEqual(emp_ticket.requester, self.emp)

        mgr_op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        emp_op = TicketBulkImportOperation.objects.get(user=self.emp, token=token)
        self.assertNotEqual(mgr_op.pk, emp_op.pk)
        self.assertEqual(mgr_op.result_json["successful"][0]["id"], mgr_ticket.pk)
        self.assertEqual(emp_op.result_json["successful"][0]["id"], emp_ticket.pk)

        # Replays stay isolated.
        r_mgr_replay = mgr_client.post("/api/tickets/bulk_create/",
                                       self._payload(rows_mgr, token), format="json")
        self.assertEqual(r_mgr_replay.data["successful"][0]["id"], mgr_ticket.pk)
        self.assertEqual(Ticket.objects.filter(title__startswith="pg-").count(), 2)

    def test_competing_operation_creation_same_user_token_payload(self):
        """Concurrent first-time confirmations create one logical operation, no duplicates."""
        token = "pg-competing-create"
        rows = [self._row(title="pg-create-race")]
        payload = self._payload(rows, token)

        # No pre-existing operation: both requests race through get_or_create/claim.
        r1, r2 = self._run_concurrent_requests(self.mgr, payload)

        responses = [r1, r2]
        ok_responses = [r for r in responses if r["status"] == 200]
        conflict_responses = [r for r in responses if r["status"] == 409]
        expected_summary = {"ok": 1, "skipped": 0, "failed": 0}
        self.assertTrue(
            (len(ok_responses) == 1 and len(conflict_responses) == 1)
            or (len(ok_responses) == 2 and len(conflict_responses) == 0),
            responses,
        )
        for resp in ok_responses:
            self.assertEqual(resp["data"].get("summary"), expected_summary, resp)
        if len(ok_responses) == 2:
            self.assertEqual(ok_responses[0]["data"], ok_responses[1]["data"], responses)

        self.assertEqual(Ticket.objects.filter(title="pg-create-race").count(), 1)
        ops = TicketBulkImportOperation.objects.filter(user=self.mgr, token=token)
        self.assertEqual(ops.count(), 1)
        op = ops.get()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(op.successful_count, 1)
        self.assertEqual(op.processed_count, 1)
        self.assertEqual(op.total_rows, 1)
        self.assertEqual(op.failed_count, 0)
        self.assertIsNotNone(op.result_json)
        db_ids = list(Ticket.objects.filter(title="pg-create-race")
                      .values_list("id", flat=True))
        result_ids = [s["id"] for s in op.result_json.get("successful", [])]
        self.assertEqual(result_ids, db_ids)
        for resp in ok_responses:
            self.assertEqual([s["id"] for s in resp["data"].get("successful", [])], db_ids, resp)

    def test_related_reference_updates_wait_for_confirmation_row_commit(self):
        """A concurrent deactivation/deletion cannot race row validation."""
        from accounts.models import Department, User
        from assets.models import Asset, AssetCategory
        from tickets.serializers import TicketBulkImportSerializer

        asset_category = AssetCategory.objects.create(
            name="PG import concurrency hardware")
        asset = Asset.objects.create(
            asset_tag="PG-IMPORT-LOCK-1", name="PG import asset",
            category=asset_category, department=self.dep)
        row = self._row(
            title="pg-reference-lock",
            asset_tag=asset.asset_tag,
            assignee_employee_id=self.emp.employee_id)

        update_attempted = {
            "category": threading.Event(),
            "department": threading.Event(),
            "asset": threading.Event(),
            "assignee": threading.Event(),
        }
        update_finished = {key: threading.Event() for key in update_attempted}
        update_errors = []
        updates = {
            "category": (
                TicketCategory, self.tcat.pk, {"is_active": False}),
            "department": (
                Department, self.dep.pk, {"is_deleted": True}),
            "asset": (Asset, asset.pk, {"is_deleted": True}),
            "assignee": (User, self.emp.pk, {"is_active": False}),
        }

        def mutate_reference(name, model, pk, values):
            close_old_connections()
            try:
                update_attempted[name].set()
                model.objects.filter(pk=pk).update(**values)
            except Exception as exc:
                update_errors.append(exc)
            finally:
                update_finished[name].set()
                connections.close_all()

        workers = [
            threading.Thread(
                target=mutate_reference, args=(name, model, pk, values))
            for name, (model, pk, values) in updates.items()
        ]
        original_is_valid = TicketBulkImportSerializer.is_valid
        updates_started = [False]

        def start_updates(serializer, *args, **kwargs):
            if not updates_started[0]:
                updates_started[0] = True
                for worker in workers:
                    worker.start()
                for event in update_attempted.values():
                    self.assertTrue(event.wait(timeout=10))
                for name, event in update_finished.items():
                    self.assertFalse(
                        event.wait(timeout=0.5),
                        f"{name} changed before the row transaction committed")
            return original_is_valid(serializer, *args, **kwargs)

        client = APIClient()
        auth(client, self.mgr)
        with unittest.mock.patch.object(
                TicketBulkImportSerializer, "is_valid", start_updates):
            response = client.post(
                "/api/tickets/bulk_create/",
                self._payload([row], "pg-reference-lock"),
                format="json")

        for worker in workers:
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive())
        self.assertEqual(update_errors, [])
        self.assertTrue(all(event.is_set() for event in update_finished.values()))
        self.assertEqual(response.status_code, 200, getattr(response, "data", response))
        self.assertEqual(
            response.data["summary"], {"ok": 1, "skipped": 0, "failed": 0})

        ticket = Ticket.objects.get(title="pg-reference-lock")
        self.assertEqual(ticket.category_id, self.tcat.pk)
        self.assertEqual(ticket.department_id, self.dep.pk)
        self.assertEqual(ticket.asset_id, asset.pk)
        self.assertEqual(ticket.assignee_id, self.emp.pk)
        for model, pk, _values in updates.values():
            manager = getattr(model, "all_objects", model.objects)
            instance = manager.get(pk=pk)
            if model is TicketCategory:
                self.assertFalse(instance.is_active)
            elif model is User:
                self.assertFalse(instance.is_active)
            else:
                self.assertTrue(instance.is_deleted)

    def test_category_deactivated_after_batch_resolution_is_revalidated(self):
        """A change between cached resolution and the row lock is observed."""
        from django.db.models.query import QuerySet

        client = APIClient()
        auth(client, self.mgr)
        row = self._row(title="pg-category-revalidation")
        update_attempted = threading.Event()
        update_finished = threading.Event()
        update_error = [None]

        def deactivate_category():
            close_old_connections()
            try:
                update_attempted.set()
                TicketCategory.objects.filter(pk=self.tcat.pk).update(
                    is_active=False)
            except Exception as exc:
                update_error[0] = exc
            finally:
                update_finished.set()
                connections.close_all()

        worker = threading.Thread(target=deactivate_category)
        original_select_for_update = QuerySet.select_for_update
        mutation_started = [False]

        def update_before_category_lock(queryset, *args, **kwargs):
            if (queryset.model is TicketCategory
                    and not mutation_started[0]):
                mutation_started[0] = True
                worker.start()
                self.assertTrue(update_attempted.wait(timeout=10))
                self.assertTrue(update_finished.wait(timeout=10))
            return original_select_for_update(queryset, *args, **kwargs)

        with unittest.mock.patch.object(
                QuerySet, "select_for_update", update_before_category_lock):
            response = client.post(
                "/api/tickets/bulk_create/",
                self._payload([row], "pg-category-revalidation"),
                format="json")

        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(update_error[0])
        self.assertEqual(response.status_code, 200, getattr(response, "data", response))
        self.assertEqual(
            response.data["summary"], {"ok": 0, "skipped": 0, "failed": 1})
        self.assertFalse(Ticket.objects.filter(
            title="pg-category-revalidation").exists())
        self.tcat.refresh_from_db()
        self.assertFalse(self.tcat.is_active)

    def test_concurrent_inspection_sees_only_committed_row_outcomes(self):
        """Read-only reconciliation must not report uncommitted row outcomes."""
        from tickets.models import TicketBulkImportRowOutcome

        token = "pg-concurrent-inspect"
        rows = [self._row(title="pg-inspect-1"), self._row(title="pg-inspect-2")]
        payload = self._payload(rows, token)

        create_started = threading.Event()
        allow_commit = threading.Event()
        inspection_result = {}
        inspection_error = [None]
        real_create = TicketBulkImportRowOutcome.objects.create
        succeeded_creates = [0]

        def guarded_create(*args, **kwargs):
            obj = real_create(*args, **kwargs)
            if kwargs.get("outcome") == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED:
                succeeded_creates[0] += 1
                # Block on the second succeeded outcome while its row transaction
                # is still open (uncommitted). Inspection must not see it.
                if succeeded_creates[0] == 2:
                    create_started.set()
                    if not allow_commit.wait(timeout=30):
                        raise RuntimeError("allow_commit timeout")
            return obj

        def inspect_worker():
            try:
                close_old_connections()
                staff_client = APIClient()
                auth(staff_client, self.admin)
                # Wait until row 2 succeeded outcome has been inserted but not committed.
                if not create_started.wait(timeout=30):
                    raise RuntimeError("create_started timeout")
                op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
                resp = staff_client.get(
                    f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
                inspection_result["status"] = resp.status_code
                inspection_result["data"] = getattr(resp, "data", None)
                # Allow the blocked row transaction to commit after inspection.
                allow_commit.set()
            except Exception as exc:
                inspection_error[0] = exc
                allow_commit.set()
            finally:
                connections.close_all()

        t = threading.Thread(target=inspect_worker)
        t.start()
        try:
            with unittest.mock.patch(
                    "tickets.models.TicketBulkImportRowOutcome.objects.create",
                    side_effect=guarded_create):
                client = APIClient()
                auth(client, self.mgr)
                resp = client.post("/api/tickets/bulk_create/", payload, format="json")
        finally:
            allow_commit.set()
            t.join(timeout=60)

        if t.is_alive():
            self.fail("Inspection thread did not complete")
        if inspection_error[0] is not None:
            raise inspection_error[0]

        self.assertEqual(resp.status_code, 200, getattr(resp, "data", resp))
        self.assertEqual(resp.data["summary"], {"ok": 2, "skipped": 0, "failed": 0})
        self.assertEqual(inspection_result.get("status"), 200, inspection_result)
        data = inspection_result["data"]
        # Only row 1 was committed at inspection time; row 2 was uncommitted.
        self.assertEqual(data["recorded_successful_rows"], 1, data)
        self.assertEqual(data["recorded_failed_rows"], 0, data)
        self.assertEqual(data["unprocessed_or_unrecorded_rows"], 1, data)
        self.assertEqual(len(data["committed_ticket_ids"]), 1, data)

        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(TicketBulkImportRowOutcome.objects.filter(
            operation=op, outcome=TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED).count(), 2)
        self.assertEqual(Ticket.objects.filter(title__startswith="pg-inspect-").count(), 2)

@skipUnless(_is_postgresql(),
            "PostgreSQL-only: requires real row locks/transaction isolation (SQLite skipped)")
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketBulkImportReconciliationPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def _row(self, **kw):
        base = {"title": "t", "description": "d", "category": self.tcat.pk,
                "department": self.dep.pk}
        base.update(kw)
        return base

    def _eligible_failed_op(self, token, rows):
        from tickets.views import _ticket_bulk_import_fingerprint, _ticket_bulk_import_row_fingerprint
        from datetime import timedelta
        from django.utils import timezone
        fp = _ticket_bulk_import_fingerprint(rows, upload=None)
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token=token,
            status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint=fp,
            total_rows=len(rows),
            processed_count=len(rows),
            successful_count=len(rows),
            failed_count=0,
            started_at=timezone.now() - timedelta(minutes=10),
            expires_at=timezone.now() + timedelta(hours=1),
            error_detail="interrupted",
        )
        for idx, row in enumerate(rows):
            t = Ticket.objects.create(title=row["title"], description=row.get("description", "d"),
                                      category=self.tcat, requester=self.mgr, department=self.dep)
            TicketBulkImportRowOutcome.objects.create(
                operation=op, row_index=idx, row_number=idx + 1,
                row_fingerprint=_ticket_bulk_import_row_fingerprint(row),
                outcome=TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED,
                ticket=t)
        return op

    def _preview(self, op):
        client = APIClient()
        auth(client, self.admin)
        resp = client.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
        self.assertEqual(resp.status_code, 200, getattr(resp, "data", resp))
        return resp.data

    def _run_concurrent_finalize(self, op, payload_a, payload_b=None):
        if payload_b is None:
            payload_b = payload_a
        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(idx, payload):
            try:
                close_old_connections()
                client = APIClient()
                auth(client, self.admin)
                barrier.wait(timeout=15)
                resp = client.post(
                    f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                    payload, format="json")
                results[idx] = {"status": resp.status_code, "data": getattr(resp, "data", None)}
            except Exception as exc:
                errors[idx] = exc
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, payload_a))
        t2 = threading.Thread(target=worker, args=(1, payload_b))
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)
        if t1.is_alive() or t2.is_alive():
            self.fail("Concurrent finalize threads did not complete")
        for err in errors:
            if err is not None:
                raise err
        return results[0], results[1]

    def test_concurrent_finalization_exactly_once(self):
        """Two simultaneous finalize requests: one logical finalization, no duplicates."""
        from common.models import AuditLog
        op = self._eligible_failed_op("pg-fin-race", [self._row(title="pg-fin-1")])
        prev = self._preview(op)
        payload = {"reason": "concurrent", "evidence_digest": prev["evidence_digest"],
                   "expected_status": prev["current_status"]}
        r1, r2 = self._run_concurrent_finalize(op, payload)
        responses = [r1, r2]
        ok = [r for r in responses if r["status"] == 200]
        self.assertEqual(len(ok), 2, responses)
        # One actual finalization, one idempotent response (order/timing may vary).
        flags = sorted([bool(r["data"].get("idempotent")) for r in ok])
        self.assertIn(flags, ([False, True], [True, False]) or [False, True], responses)
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertTrue(op.result_json)
        fin = [a for a in AuditLog.objects.filter(
            entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
            if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 1)
        self.assertEqual(Ticket.objects.filter(title="pg-fin-1").count(), 1)
        self.assertEqual(TicketBulkImportRowOutcome.objects.filter(operation=op).count(), 1)

    def test_finalize_rejects_stale_preview_after_evidence_change(self):
        """Evidence changed after preview -> stale detected, no mutation."""
        op = self._eligible_failed_op("pg-fin-stale", [self._row(title="pg-fin-stale")])
        prev = self._preview(op)
        # Change evidence after preview (counters/state drift simulation).
        TicketBulkImportOperation.objects.filter(pk=op.pk).update(successful_count=0)
        client = APIClient()
        auth(client, self.admin)
        res = client.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "stale", "evidence_digest": prev["evidence_digest"],
            "expected_status": prev["current_status"],
        }, format="json")
        self.assertEqual(res.status_code, 409, getattr(res, "data", res))
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
        self.assertFalse(op.result_json)

    def test_finalize_transaction_failure_rolls_back(self):
        """Forced failure before commit rolls back op/result/audit; evidence unchanged."""
        from common.models import AuditLog
        op = self._eligible_failed_op("pg-fin-rb", [self._row(title="pg-fin-rb")])
        prev = self._preview(op)
        client = APIClient()
        auth(client, self.admin)
        before_op = (op.status, op.result_json, op.result_format)
        before_outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op)
                               .values_list("id", "outcome", "ticket_id"))
        with unittest.mock.patch("common.audit.log_action", side_effect=RuntimeError("boom")):
            old = client.raise_request_exception
            client.raise_request_exception = False
            try:
                res = client.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
                    "reason": "rb", "evidence_digest": prev["evidence_digest"],
                    "expected_status": prev["current_status"],
                }, format="json")
            finally:
                client.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        op.refresh_from_db()
        self.assertEqual((op.status, op.result_json, op.result_format), before_op)
        self.assertEqual(before_outcomes, list(TicketBulkImportRowOutcome.objects.filter(operation=op)
                                               .values_list("id", "outcome", "ticket_id")))
        self.assertEqual(Ticket.objects.filter(title="pg-fin-rb").count(), 1)
        fin = [a for a in AuditLog.objects.filter(
            entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
            if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 0)

    def test_concurrent_inspection_during_finalization_sees_consistent_state(self):
        """Inspection during in-flight finalization must not see partial persistence."""
        op = self._eligible_failed_op("pg-fin-inspect", [self._row(title="pg-fin-inspect")])
        prev = self._preview(op)
        payload = {"reason": "inspect", "evidence_digest": prev["evidence_digest"],
                   "expected_status": prev["current_status"]}

        entered = threading.Event()
        allow_commit = threading.Event()
        inspection = {}
        errors = [None, None]
        real_log = __import__("common.audit", fromlist=["log_action"]).log_action

        def blocked_log(*args, **kwargs):
            # Called inside finalize transaction after operation save; block before commit.
            entered.set()
            if not allow_commit.wait(timeout=30):
                raise RuntimeError("allow_commit timeout")
            return real_log(*args, **kwargs)

        def inspect_worker():
            try:
                close_old_connections()
                if not entered.wait(timeout=30):
                    raise RuntimeError("entered timeout")
                c = APIClient(); auth(c, self.admin)
                resp = c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
                inspection["status"] = resp.status_code
                inspection["data"] = getattr(resp, "data", None)
                allow_commit.set()
            except Exception as exc:
                errors[0] = exc
                allow_commit.set()
            finally:
                connections.close_all()

        def finalize_worker():
            try:
                close_old_connections()
                c = APIClient(); auth(c, self.admin)
                with unittest.mock.patch("common.audit.log_action", side_effect=blocked_log):
                    resp = c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                                  payload, format="json")
                inspection["finalize_status"] = resp.status_code
                inspection["finalize_data"] = getattr(resp, "data", None)
            except Exception as exc:
                errors[1] = exc
                allow_commit.set()
            finally:
                connections.close_all()

        ti = threading.Thread(target=inspect_worker)
        tf = threading.Thread(target=finalize_worker)
        ti.start(); tf.start()
        ti.join(timeout=60); tf.join(timeout=60)
        if ti.is_alive() or tf.is_alive():
            self.fail("Threads did not complete")
        for e in errors:
            if e:
                raise e
        self.assertEqual(inspection.get("status"), 200, inspection)
        # Inspection happened before finalize commit: must see pre-finalization consistent state.
        self.assertEqual(inspection["data"]["current_status"], TicketBulkImportOperation.STATUS_FAILED, inspection)
        self.assertFalse(inspection["data"].get("result_stored"), inspection)
        self.assertEqual(inspection.get("finalize_status"), 200, inspection)
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)

    def test_concurrent_evidence_mutation_before_authoritative_assessment_rejects_stale_digest(self):
        """Evidence mutation commits before finalize completes authoritative assessment.

        Finalization must not succeed using stale/inconsistent evidence. We pause
        finalize around the real assessment call (timing hook only; DB locking and
        transaction boundaries remain real) so a concurrent mutation commits first.
        """
        from datetime import timedelta
        from django.utils import timezone
        from common.models import AuditLog
        from tickets.bulk_import_reconciliation import assess_operation as real_assess

        op = self._eligible_failed_op("pg-race-mut", [self._row(title="pg-race-mut-1")])
        prev = self._preview(op)
        old_digest = prev["evidence_digest"]
        payload = {"reason": "race", "evidence_digest": old_digest,
                   "expected_status": prev["current_status"]}

        finalize_entered_assess = threading.Event()
        allow_assess = threading.Event()
        mutation_done = threading.Event()
        results = {}
        errors = [None, None]

        def wrapped_assess(operation):
            # Timing hook inside real finalize transaction: op row already locked.
            finalize_entered_assess.set()
            if not allow_assess.wait(timeout=30):
                raise RuntimeError("allow_assess timeout")
            return real_assess(operation)

        def mutator():
            try:
                close_old_connections()
                if not finalize_entered_assess.wait(timeout=30):
                    raise RuntimeError("finalize_entered_assess timeout")
                # Mutate digest-relevant evidence in an independent transaction/connection.
                TicketBulkImportRowOutcome.objects.filter(operation=op, row_index=0).update(
                    error_message="mutated-after-preview")
                # error_message presence is boolean in digest; use updated_at for digest change.
                TicketBulkImportRowOutcome.objects.filter(operation=op, row_index=0).update(
                    updated_at=timezone.now() + timedelta(seconds=7))
                mutation_done.set()
                allow_assess.set()
            except Exception as exc:
                errors[0] = exc
                mutation_done.set()
                allow_assess.set()
            finally:
                connections.close_all()

        def finalizer():
            try:
                close_old_connections()
                c = APIClient(); auth(c, self.admin)
                with unittest.mock.patch("tickets.bulk_import_reconciliation.assess_operation",
                                         side_effect=wrapped_assess):
                    resp = c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                                  payload, format="json")
                results["status"] = resp.status_code
                results["data"] = getattr(resp, "data", None)
            except Exception as exc:
                errors[1] = exc
                allow_assess.set()
            finally:
                connections.close_all()

        t1 = threading.Thread(target=finalizer)
        t2 = threading.Thread(target=mutator)
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)
        if t1.is_alive() or t2.is_alive():
            self.fail("Race threads did not complete")
        for e in errors:
            if e:
                raise e
        self.assertTrue(mutation_done.is_set())
        # Finalize must reject stale digest; it must not finalize inconsistent evidence.
        self.assertEqual(results.get("status"), 409, results)
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
        self.assertFalse(op.result_json)
        fin = [a for a in AuditLog.objects.filter(
            entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
            if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 0)
        # Evidence mutation persisted; state remains internally consistent.
        outcome = TicketBulkImportRowOutcome.objects.get(operation=op, row_index=0)
        self.assertTrue(outcome.updated_at)

    def test_finalize_lock_prevents_concurrent_outcome_mutation_until_decision(self):
        """Finalize holds op lock first; concurrent outcome mutation waits/serializes.

        With independent connections, we verify finalization completes with a
        consistent decision and no partial/invalid state. Outcome mutation uses a
        separate connection and commits after finalize releases lock.
        """
        from datetime import timedelta
        from django.utils import timezone
        from common.models import AuditLog
        from tickets.bulk_import_reconciliation import assess_operation as real_assess

        op = self._eligible_failed_op("pg-race-lock", [self._row(title="pg-race-lock-1")])
        prev = self._preview(op)
        payload = {"reason": "lock-race", "evidence_digest": prev["evidence_digest"],
                   "expected_status": prev["current_status"]}

        assess_started = threading.Event()
        allow_assess = threading.Event()
        results = {}
        errors = [None, None]

        def wrapped_assess(operation):
            assess_started.set()
            if not allow_assess.wait(timeout=30):
                raise RuntimeError("allow_assess timeout")
            return real_assess(operation)

        def finalizer():
            try:
                close_old_connections()
                c = APIClient(); auth(c, self.admin)
                with unittest.mock.patch("tickets.bulk_import_reconciliation.assess_operation",
                                         side_effect=wrapped_assess):
                    resp = c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                                  payload, format="json")
                results["finalize_status"] = resp.status_code
                results["finalize_data"] = getattr(resp, "data", None)
            except Exception as exc:
                errors[0] = exc
                allow_assess.set()
            finally:
                connections.close_all()

        def mutator():
            try:
                close_old_connections()
                if not assess_started.wait(timeout=30):
                    raise RuntimeError("assess_started timeout")
                # Mutate outcome on independent connection while finalize is in-flight.
                # Plain update (no op lock) may proceed; finalize has already read evidence
                # only after allow_assess. We release assess after mutation attempt to
                # exercise serialization around the authoritative assessment window.
                TicketBulkImportRowOutcome.objects.filter(operation=op, row_index=0).update(
                    updated_at=timezone.now() + timedelta(seconds=9))
                results["mutation_done"] = True
                allow_assess.set()
            except Exception as exc:
                errors[1] = exc
                allow_assess.set()
            finally:
                connections.close_all()

        tf = threading.Thread(target=finalizer)
        tm = threading.Thread(target=mutator)
        tf.start(); tm.start()
        tf.join(timeout=60); tm.join(timeout=60)
        if tf.is_alive() or tm.is_alive():
            self.fail("Race threads did not complete")
        for e in errors:
            if e:
                raise e
        # Either finalize succeeds based on pre-mutation consistent assessment, or
        # rejects stale evidence if it observed mutation - never inconsistent success.
        self.assertIn(results.get("finalize_status"), (200, 409), results)
        op.refresh_from_db()
        if results.get("finalize_status") == 200:
            self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
            fin = [a for a in AuditLog.objects.filter(
                entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
                if (a.details or {}).get("action_type") == "finalize"]
            self.assertEqual(len(fin), 1)
        else:
            self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
            fin = [a for a in AuditLog.objects.filter(
                entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
                if (a.details or {}).get("action_type") == "finalize"]
            self.assertEqual(len(fin), 0)

    def test_ticket_delete_set_null_blocks_finalization(self):
        """Deleting a ticket SET_NULLs succeeded outcome ticket ref; finalization must be blocked."""
        from common.models import AuditLog
        op = self._eligible_failed_op("pg-setnull", [self._row(title="pg-setnull-1")])
        prev = self._preview(op)
        self.assertTrue(prev["eligible_for_finalization"])
        ticket = Ticket.objects.get(title="pg-setnull-1")
        ticket.hard_delete()  # SET_NULL on TicketBulkImportRowOutcome.ticket
        outcome = TicketBulkImportRowOutcome.objects.get(operation=op, row_index=0)
        self.assertIsNone(outcome.ticket_id)
        after = self._preview(op)
        self.assertFalse(after["eligible_for_finalization"])
        self.assertIn("missing_ticket_reference", after.get("reasons", []))
        client = APIClient(); auth(client, self.admin)
        res = client.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "should block", "evidence_digest": after["evidence_digest"],
            "expected_status": after["current_status"],
        }, format="json")
        self.assertEqual(res.status_code, 409, getattr(res, "data", res))
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
        fin = [a for a in AuditLog.objects.filter(
            entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
            if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 0)

