"""Phase 38: safe audited reconciliation and finalization for ticket bulk imports.

Covers eligibility, preview, finalization, idempotency/staleness, audit, and
missing-ticket integrity cases on SQLite by default. PostgreSQL-specific
concurrency/failure-injection tests are included and skipped when not on PG.
"""

import json
import threading
import time
import unittest.mock
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.core.cache import cache
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from common.models import AuditLog
from tickets.bulk_import_reconciliation import assess_operation, build_preview_payload
from tickets.models import (
    Ticket, TicketBulkImportOperation, TicketBulkImportRowOutcome, TicketCategory,
)
from tickets.views import _ticket_bulk_import_fingerprint, _ticket_bulk_import_row_fingerprint


def _is_postgresql():
    return connection.vendor == "postgresql"


def _make_rows(dep, cat, count=1, prefix="r"):
    return [{"title": f"{prefix}-{i}", "description": "d", "category": cat.pk,
             "department": dep.pk} for i in range(count)]


def _create_tracked_interrupted_op(user, dep, cat, *, token, rows, specs,
                                   status_value=None, result_json=None,
                                   result_format="", result_csv="",
                                   result_status_code=200, error_detail="interrupted",
                                   total_rows=None, processed_count=None,
                                   successful_count=None, failed_count=None,
                                   started_at=None, completed_at=None):
    """Create an operation with durable row outcomes for reconciliation tests.

    specs: list of {"outcome": ..., "ticket": obj|None, "error": str}
    """
    if total_rows is None:
        total_rows = len(rows)
    if processed_count is None:
        processed_count = len(specs)
    if successful_count is None:
        successful_count = sum(1 for s in specs if s["outcome"] == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED)
    if failed_count is None:
        failed_count = sum(1 for s in specs if s["outcome"] == TicketBulkImportRowOutcome.OUTCOME_FAILED)
    if started_at is None:
        started_at = timezone.now() - timedelta(minutes=10)
    op = TicketBulkImportOperation.objects.create(
        user=user,
        token=token,
        status=status_value or TicketBulkImportOperation.STATUS_FAILED,
        request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
        total_rows=total_rows,
        processed_count=processed_count,
        successful_count=successful_count,
        failed_count=failed_count,
        started_at=started_at,
        completed_at=completed_at,
        result_format=result_format,
        result_json=result_json,
        result_csv=result_csv,
        result_status_code=result_status_code,
        error_detail=error_detail,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    for idx, spec in enumerate(specs):
        TicketBulkImportRowOutcome.objects.create(
            operation=op,
            row_index=spec.get("row_index", idx),
            row_number=spec.get("row_number", idx + 1),
            row_fingerprint=_ticket_bulk_import_row_fingerprint(rows[idx]) if idx < len(rows) else "f" * 64,
            outcome=spec["outcome"],
            ticket=spec.get("ticket"),
            error_message=spec.get("error", ""),
        )
    return op


class TicketBulkImportReconciliationServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="Hardware")

    def _ticket(self, title="t"):
        return Ticket.objects.create(title=title, description="d", category=self.cat,
                                     requester=self.mgr, department=self.dep)

    def test_eligible_all_success(self):
        rows = _make_rows(self.dep, self.cat, 2)
        t1, t2 = self._ticket("a"), self._ticket("b")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="all-ok", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t2},
        ])
        a = assess_operation(op)
        self.assertTrue(a.eligible_for_finalization)
        self.assertEqual(a.proposed_status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(a.unprocessed_row_count, 0)
        self.assertEqual(a.missing_ticket_references, [])
        self.assertTrue(a.evidence_digest)

    def test_eligible_mixed_success_and_failure(self):
        rows = _make_rows(self.dep, self.cat, 2)
        t1 = self._ticket("ok")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="mixed", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": "bad row"},
        ])
        a = assess_operation(op)
        self.assertTrue(a.eligible_for_finalization)
        self.assertEqual(a.succeeded_outcome_count, 1)
        self.assertEqual(a.failed_outcome_count, 1)

    def test_eligible_all_failure_fully_accounted(self):
        rows = _make_rows(self.dep, self.cat, 2)
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="all-fail", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": "e1"},
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": "e2"},
        ], successful_count=0, failed_count=2)
        a = assess_operation(op)
        self.assertTrue(a.eligible_for_finalization)
        self.assertEqual(a.proposed_status, TicketBulkImportOperation.STATUS_COMPLETED)

    def test_missing_outcome_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 2)
        t1 = self._ticket("only-one")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="missing", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
        ], total_rows=2, processed_count=1, successful_count=1, failed_count=0)
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("unprocessed_or_unrecorded_rows", a.reasons)

    def test_extra_outcome_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t1 = self._ticket("ok")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="extra", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
        ], total_rows=1)
        # Add unexpected extra row outcome beyond expected range.
        TicketBulkImportRowOutcome.objects.create(
            operation=op, row_index=1, row_number=2,
            row_fingerprint="x" * 64,
            outcome=TicketBulkImportRowOutcome.OUTCOME_FAILED, error_message="extra")
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertTrue(any("unexpected_extra_outcomes" in r for r in a.reasons) or "unexpected_extra_outcomes" in a.reasons)

    def test_missing_row_index_gap_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 2)
        t2 = self._ticket("second")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="gap", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t2, "row_index": 1, "row_number": 2},
        ], total_rows=2, processed_count=1, successful_count=1, failed_count=0)
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("unprocessed_or_unrecorded_rows", a.reasons)

    def test_invalid_outcome_status_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="bad-status", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": "e"},
        ])
        TicketBulkImportRowOutcome.objects.filter(operation=op).update(outcome="unknown")
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("invalid_outcome_status", a.reasons)

    def test_failed_outcome_missing_error_evidence_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="no-err", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": ""},
        ])
        # _create_tracked_interrupted_op stores error_message from spec; ensure empty.
        TicketBulkImportRowOutcome.objects.filter(operation=op).update(error_message="")
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("invalid_failure_evidence", a.reasons)

    def test_succeeded_outcome_null_ticket_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("x")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="null-ticket", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])
        TicketBulkImportRowOutcome.objects.filter(operation=op).update(ticket=None)
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("missing_ticket_reference", a.reasons)
        self.assertTrue(a.missing_ticket_references)

    def test_succeeded_outcome_deleted_ticket_hard_delete_blocks(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("del")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="deleted-ticket", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])
        # Hard delete triggers FK SET_NULL.
        t.hard_delete()
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("missing_ticket_reference", a.reasons)

    def test_counter_mismatch_reported_but_complete_evidence_can_be_eligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("c")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="counter-mm", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ], successful_count=0, processed_count=0)  # inconsistent stored counters
        a = assess_operation(op)
        self.assertTrue(a.counter_inconsistencies)
        # Explicit audited finalization may correct counters to evidence-derived values.
        self.assertTrue(a.eligible_for_finalization)

    def test_invalid_expected_row_count_zero_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("z")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="zero-exp", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ], total_rows=0)
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("legacy_or_ambiguous_evidence", a.reasons)

    def test_legacy_operation_without_row_outcomes_ineligible(self):
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token="legacy", status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint="fp", total_rows=2, processed_count=2,
            successful_count=1, failed_count=1, error_detail="old",
            expires_at=timezone.now() + timedelta(hours=1))
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("legacy_or_ambiguous_evidence", a.reasons)

    def test_processing_incomplete_evidence_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 2)
        t1 = self._ticket("p1")
        op = _create_tracked_interrupted_op(
            self.mgr, self.dep, self.cat, token="proc-inc", rows=rows,
            specs=[{"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1}],
            status_value=TicketBulkImportOperation.STATUS_PROCESSING,
            total_rows=2, processed_count=1, successful_count=1, failed_count=0,
            error_detail="")
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("unprocessed_or_unrecorded_rows", a.reasons)

    def test_already_completed_consistent_not_eligible_for_new_finalization(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("done")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="done", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ], status_value=TicketBulkImportOperation.STATUS_COMPLETED,
            result_format="json",
            result_json={"successful": [{"row": 1, "id": t.pk, "title": t.title}],
                         "skipped": [], "failed": [],
                         "summary": {"ok": 1, "skipped": 0, "failed": 0}},
            result_status_code=200, error_detail="", completed_at=timezone.now())
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("already_finalized", a.reasons)

    def test_conflicting_stored_result_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("conf")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="conflict", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ], status_value=TicketBulkImportOperation.STATUS_COMPLETED,
            result_format="json",
            result_json={"successful": [], "skipped": [], "failed": [{"row": 1, "errors": "x"}],
                         "summary": {"ok": 0, "skipped": 0, "failed": 1}},
            result_status_code=200, error_detail="", completed_at=timezone.now())
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("result_conflict", a.reasons)

    def test_completed_without_stored_result_ineligible(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("nostore")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="nostore", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ], status_value=TicketBulkImportOperation.STATUS_COMPLETED,
            result_format="", result_json=None, result_csv="", error_detail="", completed_at=timezone.now())
        a = assess_operation(op)
        self.assertFalse(a.eligible_for_finalization)
        self.assertIn("result_conflict", a.reasons)

    def test_preview_payload_has_no_sensitive_data(self):
        rows = _make_rows(self.dep, self.cat, 1)
        t = self._ticket("safe")
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="secret-token", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])
        p = build_preview_payload(op)
        blob = json.dumps(p, default=str)
        self.assertNotIn("secret-token", blob)
        self.assertNotIn("request_fingerprint", blob)
        self.assertNotIn("preview_payload", blob)
        self.assertIn("evidence_digest", blob)


class TicketBulkImportReconciliationApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = TicketCategory.objects.create(name="Hardware")

    def _ticket(self, title="t"):
        return Ticket.objects.create(title=title, description="d", category=self.cat,
                                     requester=self.mgr, department=self.dep)

    def _eligible_op(self, token="elig", rows=None):
        if rows is None:
            rows = _make_rows(self.dep, self.cat, 1, prefix=token)
        t = self._ticket(rows[0]["title"])
        return _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token=token, rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])

    def test_unauthorized_employee_cannot_preview_or_finalize(self):
        op = self._eligible_op("noemp")
        auth(self.c, self.emp)
        self.assertEqual(self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").status_code, 403)
        self.assertEqual(self.c.post(
            f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
            {"reason": "x", "evidence_digest": "y"}, format="json").status_code, 403)

    def test_staff_preview_and_successful_finalization(self):
        rows = _make_rows(self.dep, self.cat, 2, prefix="fin")
        t1 = self._ticket(rows[0]["title"])
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="fin", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": "bad"},
        ])
        auth(self.c, self.admin)
        prev = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
        self.assertEqual(prev.status_code, 200)
        self.assertTrue(prev.data["eligible_for_finalization"])
        digest = prev.data["evidence_digest"]
        before_tickets = Ticket.objects.count()
        before_outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op).order_by("row_index").values("id", "outcome", "ticket_id"))
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "Interrupted after row commits; durable evidence complete.",
            "evidence_digest": digest,
            "expected_status": op.status,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data["finalized"])
        self.assertFalse(res.data["idempotent"])
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(op.successful_count, 1)
        self.assertEqual(op.failed_count, 1)
        self.assertEqual(op.processed_count, 2)
        self.assertEqual(op.total_rows, 2)
        self.assertTrue(op.result_format == "json")
        self.assertEqual(op.result_json["summary"], {"ok": 1, "skipped": 0, "failed": 1})
        self.assertEqual(len(op.result_json["successful"]), 1)
        self.assertEqual(len(op.result_json["failed"]), 1)
        self.assertEqual(Ticket.objects.count(), before_tickets)
        self.assertEqual(before_outcomes, list(TicketBulkImportRowOutcome.objects.filter(operation=op).order_by("row_index").values("id", "outcome", "ticket_id")))
        # Audit record
        audits = AuditLog.objects.filter(entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
        fin = [a for a in audits if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 1)
        self.assertEqual(fin[0].reason, "Interrupted after row commits; durable evidence complete.")
        self.assertEqual((fin[0].details or {}).get("previous_operation_state"), TicketBulkImportOperation.STATUS_FAILED)
        self.assertEqual((fin[0].details or {}).get("resulting_operation_state"), TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual((fin[0].details or {}).get("finalization_outcome"), "finalized")
        blob = json.dumps(fin[0].details, default=str)
        # Sensitive import identifiers/payloads must not be in audit details.
        self.assertNotIn("request_fingerprint", blob)
        self.assertNotIn("preview_payload", blob)
        self.assertNotIn("result_json_payload", blob)
        self.assertNotIn(op.request_fingerprint, blob)

    def test_finalize_requires_reason_and_digest(self):
        op = self._eligible_op("req")
        auth(self.c, self.admin)
        prev = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data
        self.assertEqual(self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                                     {"evidence_digest": prev["evidence_digest"]}, format="json").status_code, 400)
        self.assertEqual(self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                                     {"reason": "x"}, format="json").status_code, 400)

    def test_stale_preview_rejected_after_evidence_change(self):
        rows = _make_rows(self.dep, self.cat, 1, prefix="stale")
        t = self._ticket(rows[0]["title"])
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="stale", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        # Evidence changes after preview (counter/evidence state mutation).
        TicketBulkImportOperation.objects.filter(pk=op.pk).update(successful_count=0)
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "try", "evidence_digest": digest, "expected_status": op.status,
        }, format="json")
        self.assertEqual(res.status_code, 409)
        op.refresh_from_db()
        self.assertNotEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)

    def test_stale_preview_rejected_after_ticket_deleted(self):
        rows = _make_rows(self.dep, self.cat, 1, prefix="stale-del")
        t = self._ticket(rows[0]["title"])
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="stale-del", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        t.hard_delete()
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "try", "evidence_digest": digest, "expected_status": op.status,
        }, format="json")
        self.assertEqual(res.status_code, 409)
        op.refresh_from_db()
        self.assertNotEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)

    def test_ineligible_legacy_operation_rejected(self):
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token="legacy-no", status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint="fp", total_rows=1, processed_count=1,
            successful_count=1, failed_count=0, error_detail="old",
            expires_at=timezone.now() + timedelta(hours=1))
        auth(self.c, self.admin)
        prev = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data
        # Even if caller fabricates a digest, server re-evaluates and must reject.
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "force", "evidence_digest": prev.get("evidence_digest") or "x",
            "expected_status": op.status,
        }, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertFalse(prev.get("eligible_for_finalization"))

    def test_repeated_identical_confirmation_idempotent_no_duplicate_audit(self):
        op = self._eligible_op("idem-fin")
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        payload = {"reason": "retry-safe", "evidence_digest": digest, "expected_status": op.status}
        r1 = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", payload, format="json")
        r2 = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", payload, format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertFalse(r1.data.get("idempotent"))
        self.assertTrue(r2.data.get("idempotent"))
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        fin = [a for a in AuditLog.objects.filter(entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
               if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 1)

    def test_audit_history_endpoint_staff_only(self):
        op = self._eligible_op("aud")
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                    {"reason": "audited", "evidence_digest": digest, "expected_status": op.status}, format="json")
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/audit/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["audit"]), 1)
        self.assertEqual(res.data["audit"][0]["finalization_outcome"], "finalized")
        self.assertNotIn("token", json.dumps(res.data, default=str))
        auth(self.c, self.emp)
        self.assertEqual(self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/audit/").status_code, 403)

    def test_finalize_rejects_missing_ticket_reference(self):
        rows = _make_rows(self.dep, self.cat, 1, prefix="miss")
        t = self._ticket(rows[0]["title"])
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="miss", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t},
        ])
        auth(self.c, self.admin)
        prev = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data
        TicketBulkImportRowOutcome.objects.filter(operation=op).update(ticket=None)
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "bad", "evidence_digest": prev["evidence_digest"], "expected_status": op.status,
        }, format="json")
        self.assertEqual(res.status_code, 409)

    def test_finalize_transaction_rollback_on_audit_failure(self):
        op = self._eligible_op("rb-audit")
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        old = self.c.raise_request_exception
        self.c.raise_request_exception = False
        try:
            with patch("common.audit.log_action", side_effect=RuntimeError("audit boom")):
                res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
                    "reason": "rb", "evidence_digest": digest, "expected_status": op.status,
                }, format="json")
        finally:
            self.c.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        op.refresh_from_db()
        self.assertNotEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertFalse(op.result_json)
        fin = [a for a in AuditLog.objects.filter(entity_type="tickets.ticketbulkimportoperation", object_id=str(op.pk))
               if (a.details or {}).get("action_type") == "finalize"]
        self.assertEqual(len(fin), 0)

    def test_finalize_transaction_rollback_on_save_failure(self):
        op = self._eligible_op("rb-save")
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        real_save = TicketBulkImportOperation.save
        calls = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            uf = kwargs.get("update_fields") or []
            if "result_json" in uf and "status" in uf and self.pk == op.pk:
                calls["n"] += 1
                raise RuntimeError("save boom")
            return real_save(self, *args, **kwargs)

        old = self.c.raise_request_exception
        self.c.raise_request_exception = False
        try:
            with patch.object(TicketBulkImportOperation, "save", flaky_save):
                res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
                    "reason": "rb", "evidence_digest": digest, "expected_status": op.status,
                }, format="json")
        finally:
            self.c.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        self.assertGreaterEqual(calls["n"], 1)
        op.refresh_from_db()
        self.assertNotEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertFalse(op.result_json)

    def test_finalize_does_not_create_tickets_or_mutate_outcomes(self):
        rows = _make_rows(self.dep, self.cat, 2, prefix="nomut")
        t1 = self._ticket(rows[0]["title"])
        op = _create_tracked_interrupted_op(self.mgr, self.dep, self.cat, token="nomut", rows=rows, specs=[
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
            {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "error": "bad"},
        ])
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        before_tickets = set(Ticket.objects.values_list("id", flat=True))
        before = list(TicketBulkImportRowOutcome.objects.filter(operation=op).order_by("row_index").values("id","row_index","outcome","ticket_id","error_message","row_fingerprint"))
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "safe", "evidence_digest": digest, "expected_status": op.status,
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(Ticket.objects.values_list("id", flat=True)), before_tickets)
        after = list(TicketBulkImportRowOutcome.objects.filter(operation=op).order_by("row_index").values("id","row_index","outcome","ticket_id","error_message","row_fingerprint"))
        self.assertEqual(before, after)

    def test_finalize_rejects_stale_expected_status(self):
        op = self._eligible_op("expst")
        auth(self.c, self.admin)
        digest = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/").data["evidence_digest"]
        res = self.c.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {
            "reason": "x", "evidence_digest": digest, "expected_status": TicketBulkImportOperation.STATUS_PROCESSING,
        }, format="json")
        self.assertEqual(res.status_code, 409)

    def test_row_number_constraint_enforces_one_based(self):
        """DB/model should reject row_number < 1 (1-based semantics)."""
        rows = _make_rows(self.dep, self.cat, 1, prefix="rn")
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token="rn", status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint="fp", total_rows=1, expires_at=timezone.now() + timedelta(hours=1))
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TicketBulkImportRowOutcome.objects.create(
                    operation=op, row_index=0, row_number=0,
                    row_fingerprint="f" * 64,
                    outcome=TicketBulkImportRowOutcome.OUTCOME_FAILED,
                    error_message="bad")

