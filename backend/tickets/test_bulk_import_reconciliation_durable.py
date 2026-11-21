"""Durable regression tests for Phase 46 bulk-import reconciliation integration scenarios.

These tests preserve the real API-level scenarios that were previously exercised
only by a temporary script: staff workflow, employee/anonymous denial, assessment,
exact-digest finalization, counter reconstruction, stale digest rejection,
missing-ticket ineligibility, idempotent duplicate finalization, and audit
persistence. They run on SQLite by default and are PostgreSQL-compatible.
"""

from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from common.models import AuditLog
from tickets.models import Ticket, TicketBulkImportOperation, TicketBulkImportRowOutcome, TicketCategory
from tickets.views import _ticket_bulk_import_fingerprint, _ticket_bulk_import_row_fingerprint


def _make_rows(dep, cat, count=1, prefix="r"):
    return [{"title": f"{prefix}-{i}", "description": "d", "category": cat.pk,
             "department": dep.pk} for i in range(count)]


def _create_tracked_op(user, dep, cat, *, token, rows, specs, status_value, result_json=None,
                       result_format="", result_csv="", result_status_code=200,
                       error_detail="", total_rows=None, processed_count=None,
                       successful_count=None, failed_count=None, started_at=None, completed_at=None):
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
        user=user, token=token, status=status_value,
        request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
        total_rows=total_rows, processed_count=processed_count,
        successful_count=successful_count, failed_count=failed_count,
        started_at=started_at, completed_at=completed_at,
        result_format=result_format, result_json=result_json, result_csv=result_csv,
        result_status_code=result_status_code, error_detail=error_detail,
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


class BulkImportReconciliationDurableAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="Hardware")
        self.staff = APIClient()
        self.employee = APIClient()
        self.anon = APIClient()
        auth(self.staff, self.mgr)
        auth(self.employee, self.emp)

    def _ticket(self, title="t"):
        return Ticket.objects.create(title=title, description="d", category=self.cat,
                                     requester=self.mgr, department=self.dep)

    def _eligible_failed_op(self, token="durable-ok"):
        rows = _make_rows(self.dep, self.cat, 2, prefix=token)
        t1 = self._ticket(f"{token}-ok")
        op = _create_tracked_op(
            self.mgr, self.dep, self.cat, token=token, rows=rows,
            status_value=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=2, processed_count=2, successful_count=2, failed_count=0,  # intentional counter drift
            specs=[
                {"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1},
                {"outcome": TicketBulkImportRowOutcome.OUTCOME_FAILED, "ticket": None, "error": "bad row"},
            ],
        )
        return op

    def test_staff_list_detail_assessment_no_sensitive_fields(self):
        op = self._eligible_failed_op("list-detail")
        r = self.staff.get("/api/tickets/bulk-imports/")
        self.assertEqual(r.status_code, 200)
        ids = [i["id"] for i in r.json().get("results", [])]
        self.assertIn(op.id, ids)

        r = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for k in ("token_hash", "payload_fingerprint", "result", "preview_payload"):
            self.assertNotIn(k, d)

        r = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/")
        self.assertEqual(r.status_code, 200)
        a = r.json()
        self.assertTrue(a["eligible_for_finalization"])
        self.assertTrue(a["evidence_digest"])
        self.assertEqual(a["succeeded_outcome_count"], 1)
        self.assertEqual(a["failed_outcome_count"], 1)
        self.assertGreater(len(a["counter_inconsistencies"]), 0)

    def test_employee_and_anonymous_denied(self):
        op = self._eligible_failed_op("authz")
        a = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/").json()
        for client in (self.employee, self.anon):
            self.assertIn(client.get("/api/tickets/bulk-imports/").status_code, (401, 403))
            self.assertIn(client.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/").status_code, (401, 403))
            self.assertIn(client.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
                "reason": "x", "evidence_digest": a["evidence_digest"],
                "expected_status": a["current_status"],
            }, format="json").status_code, (401, 403))
            self.assertIn(client.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/audit/").status_code, (401, 403))

    def test_finalize_stale_digest_then_success_audit_idempotent(self):
        op = self._eligible_failed_op("finalize-flow")
        a = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/").json()
        stale = a["evidence_digest"]

        # Digest-relevant mutation (updated_at included in digest); eligibility preserved.
        TicketBulkImportRowOutcome.objects.filter(operation=op, row_index=1).update(
            updated_at=timezone.now() + timedelta(seconds=5))

        r = self.staff.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
            "reason": "stale", "evidence_digest": stale, "expected_status": a["current_status"],
        }, format="json")
        self.assertEqual(r.status_code, 409)
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
        self.assertEqual(AuditLog.objects.filter(object_id=str(op.id), details__action_type="finalize").count(), 0)

        a2 = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/").json()
        self.assertNotEqual(a2["evidence_digest"], stale)
        r = self.staff.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
            "reason": "Integration acceptance finalize",
            "evidence_digest": a2["evidence_digest"],
            "expected_status": a2["current_status"],
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json().get("idempotent"))
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(op.successful_count, 1)
        self.assertEqual(op.failed_count, 1)
        self.assertEqual(op.processed_count, 2)
        self.assertIsNotNone(op.completed_at)

        audits = AuditLog.objects.filter(object_id=str(op.id), details__action_type="finalize")
        self.assertEqual(audits.count(), 1)
        audit = audits.first()
        self.assertEqual(audit.actor_id, self.mgr.id)
        details = audit.details or {}
        self.assertIn("Integration acceptance finalize", (details.get("reason") or audit.reason or ""))

        r = self.staff.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
            "reason": "second", "evidence_digest": a2["evidence_digest"], "expected_status": "completed",
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("idempotent"))
        self.assertEqual(AuditLog.objects.filter(object_id=str(op.id), details__action_type="finalize").count(), 1)

        r = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/audit/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json().get("audit") or []), 1)

    def test_missing_ticket_reference_ineligible_and_blocked(self):
        rows = _make_rows(self.dep, self.cat, 1, prefix="missing-ref")
        op = _create_tracked_op(
            self.mgr, self.dep, self.cat, token="missing-ref", rows=rows,
            status_value=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=1, processed_count=1, successful_count=1, failed_count=0,
            specs=[{"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": None}],
        )
        r = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/")
        self.assertEqual(r.status_code, 200)
        a = r.json()
        self.assertFalse(a["eligible_for_finalization"])
        self.assertIn("missing_ticket_reference", a.get("reasons", []))
        r = self.staff.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
            "reason": "no", "evidence_digest": a["evidence_digest"], "expected_status": a["current_status"],
        }, format="json")
        self.assertEqual(r.status_code, 409)
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
        self.assertEqual(AuditLog.objects.filter(object_id=str(op.id), details__action_type="finalize").count(), 0)


    def test_expected_status_conflict_rejected_without_mutation(self):
        op = self._eligible_failed_op("expected-status")
        a = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/").json()
        r = self.staff.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
            "reason": "stale status",
            "evidence_digest": a["evidence_digest"],
            "expected_status": "processing",  # stale
        }, format="json")
        self.assertEqual(r.status_code, 409)
        body = r.json()
        self.assertEqual(body.get("code"), "stale_evidence")
        op.refresh_from_db()
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_FAILED)
        self.assertEqual(AuditLog.objects.filter(object_id=str(op.id), details__action_type="finalize").count(), 0)


class BulkImportReconciliationDurableRollbackTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="Hardware")
        self.staff = APIClient()
        auth(self.staff, self.mgr)

    def test_audit_persistence_failure_rolls_back_finalization(self):
        rows = _make_rows(self.dep, self.cat, 1, prefix="rollback")
        t1 = Ticket.objects.create(title="rollback-ok", description="d", category=self.cat,
                                   requester=self.mgr, department=self.dep)
        op = _create_tracked_op(
            self.mgr, self.dep, self.cat, token="rollback", rows=rows,
            status_value=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=1, processed_count=1, successful_count=1, failed_count=0,
            specs=[{"outcome": TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED, "ticket": t1}],
        )
        before = {
            "status": op.status,
            "processed_count": op.processed_count,
            "successful_count": op.successful_count,
            "failed_count": op.failed_count,
            "completed_at": op.completed_at,
            "result_json": op.result_json,
            "result_format": op.result_format,
        }
        a = self.staff.get(f"/api/tickets/bulk-imports/{op.id}/reconciliation/").json()
        self.assertTrue(a["eligible_for_finalization"])

        with mock.patch("common.audit.log_action", side_effect=RuntimeError("audit boom")):
            old = self.staff.raise_request_exception
            self.staff.raise_request_exception = False
            try:
                r = self.staff.post(f"/api/tickets/bulk-imports/{op.id}/reconciliation/finalize/", {
                    "reason": "rollback test",
                    "evidence_digest": a["evidence_digest"],
                    "expected_status": a["current_status"],
                }, format="json")
            finally:
                self.staff.raise_request_exception = old

        self.assertEqual(r.status_code, 500)
        op.refresh_from_db()
        self.assertEqual(op.status, before["status"])
        self.assertEqual(op.processed_count, before["processed_count"])
        self.assertEqual(op.successful_count, before["successful_count"])
        self.assertEqual(op.failed_count, before["failed_count"])
        self.assertEqual(op.completed_at, before["completed_at"])
        self.assertEqual(op.result_json, before["result_json"])
        self.assertEqual(op.result_format, before["result_format"])
        self.assertEqual(AuditLog.objects.filter(object_id=str(op.id), details__action_type="finalize").count(), 0)
