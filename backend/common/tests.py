"""Email, privacy-erasure, and attachment-storage tests."""
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from common.models import Notification, PrivacyErasureRequest
from tickets.models import Ticket, TicketCategory

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


class PrivacyErasureDualApprovalTests(TestCase):
    """Dual-approval, impact assessment, safe execution, and audit traceability."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        # Independent reviewer: second system admin (not the requester).
        self.reviewer = User.objects.create_user(
            username="r@x", email="r@example.com", employee_id="R1",
            password="pw12345678", role="system_admin",
            home_department=self.dep)

    def _create(self, user, target=None, status="pending_review"):
        auth(self.c, user)
        target = target or self.emp
        return self.c.post("/api/common/privacy-erasures/",
                           {"entity_type": "accounts.User",
                            "object_id": str(target.pk),
                            "scope": "email, name, phone",
                            "reason": "privacy request",
                            "confirm": str(target.pk)}, format="json")

    def _approve(self, user, rid, decision="approve", reason="ok"):
        auth(self.c, user)
        return self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                           {"decision": decision, "reason": reason},
                           format="json")

    def _reject(self, user, rid, decision="reject", reason="bad"):
        auth(self.c, user)
        return self.c.post(f"/api/common/privacy-erasures/{rid}/reject/",
                           {"decision": decision, "reason": reason},
                           format="json")

    def _execute(self, user, rid, target=None):
        auth(self.c, user)
        return self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                           {"confirm": str(target.pk if target else self.emp.pk)},
                           format="json")

    # ----- creation & listing -----
    def test_create_pending_review(self):
        res = self._create(self.admin)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "pending_review")
        self.assertIn("impact_assessment", res.data)
        req = __import__("common.models", fromlist=["PrivacyErasureRequest"]).PrivacyErasureRequest.objects.get(pk=res.data["id"])
        self.assertIsNotNone(req.impact_assessed_at)

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/privacy-erasures/",
                          {"entity_type": "accounts.User",
                           "object_id": str(self.emp.pk),
                           "scope": "email", "reason": "x",
                           "confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_list_filters_by_status(self):
        self._create(self.admin)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/privacy-erasures/?status=pending_review")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)

    # ----- self-approval prevention -----
    def test_requester_cannot_approve_own(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        ap = self._approve(self.admin, rid)
        self.assertEqual(ap.status_code, 409)

    def test_requester_cannot_reject_own(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        auth(self.c, self.admin)
        rej = self.c.post(f"/api/common/privacy-erasures/{rid}/reject/",
                          {"decision": "reject", "reason": "no"},
                          format="json")
        self.assertEqual(rej.status_code, 409)

    def test_independent_approver_can_approve(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        ap = self._approve(self.reviewer, rid)
        self.assertEqual(ap.status_code, 200)
        self.assertEqual(ap.data["status"], "approved")

    # ----- execution requires approval -----
    def test_execute_blocked_without_approval(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        ex = self._execute(self.admin, rid)
        self.assertEqual(ex.status_code, 409)
        self.assertIn("approved", ex.data["detail"])

    def test_execute_blocked_after_rejection(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._reject(self.reviewer, rid, decision="reject", reason="bad")
        ex = self._execute(self.reviewer, rid)
        self.assertEqual(ex.status_code, 409)

    def test_execute_requires_approved(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        # Rejected -> cannot execute.
        self._reject(self.reviewer, rid, decision="reject", reason="bad")
        ex = self._execute(self.reviewer, rid)
        self.assertEqual(ex.status_code, 409)

    # ----- full dual-approval flow -----
    def test_approve_then_execute_anonymizes(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        ex = self._execute(self.reviewer, rid)
        self.assertEqual(ex.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)
        self.assertEqual(self.emp.email, f"erased_{self.emp.pk}@erased.local")

    def test_review_recorded(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid, reason="looks fine")
        from common.models import PrivacyErasureRequest
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.reviewed_by_id, self.reviewer.pk)
        self.assertEqual(req.review_decision, "approved")
        self.assertEqual(req.review_reason, "looks fine")
        self.assertIsNotNone(req.reviewed_at)
        self.assertIsNotNone(req.decided_at)

    # ----- impact assessment changes after approval invalidate approval -----
    def test_material_change_invalidates_approval(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        # Change the target to a user WITH linked records -> assessment
        # changes -> approval invalidated on execute.
        other = User.objects.create_user(
            username="o@x", email="o@example.com", employee_id="O1",
            password="pw12345678", role="employee", home_department=self.dep)
        from tickets.models import Ticket, TicketCategory
        cat = TicketCategory.objects.create(name="MC")
        Ticket.objects.create(title="t", description="d", category=cat,
                              requester=other, department=self.dep)
        req = __import__("common.models", fromlist=["PrivacyErasureRequest"]).PrivacyErasureRequest.objects.get(pk=rid)
        req.object_id = str(other.pk)
        req.save(update_fields=["object_id"])
        ex = self._execute(self.reviewer, rid, target=other)
        self.assertEqual(ex.status_code, 409)
        self.assertIn("assessment", ex.data["detail"].lower())
        req.refresh_from_db()
        self.assertEqual(req.status, "pending_review")

    # ----- retention / legal hold -----
    def test_retention_restrictions_shown(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        auth(self.c, self.admin)
        det = self.c.get(f"/api/common/privacy-erasures/{rid}/")
        self.assertEqual(det.status_code, 200)
        self.assertIn("dependency_check", det.data)
        self.assertIn("retention", det.data["dependency_check"])

    def test_legal_hold_not_implemented_limitation(self):
        """Project has no legal-hold model; document the extension point."""
        self.assertFalse(hasattr(User, "legal_hold"))
        # No legal-hold functionality is implemented; assessment notes this.

    # ----- duplicate & concurrent execution -----
    def test_duplicate_execution_is_idempotent(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        ex1 = self._execute(self.reviewer, rid)
        self.assertEqual(ex1.status_code, 200)
        # Second execution of a completed request -> idempotent success.
        ex2 = self._execute(self.reviewer, rid)
        self.assertEqual(ex2.status_code, 200)
        self.assertTrue(ex2.data["result"].get("already_completed"))

    def test_concurrent_execution_blocked_by_lock(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        from common.models import PrivacyErasureRequest
        req = PrivacyErasureRequest.objects.get(pk=rid)
        req.execution_lock = True
        req.save(update_fields=["execution_lock"])
        ex = self._execute(self.reviewer, rid)
        self.assertEqual(ex.status_code, 409)
        self.assertIn("in progress", ex.data["detail"])

    # ----- inactive administrator authorization -----
    def test_inactive_system_admin_cannot_approve(self):
        from common.models import PrivacyErasureRequest
        from common.privacy_service import approve_erasure
        res = self._create(self.admin)
        rid = res.data["id"]
        self.reviewer.is_active = False
        self.reviewer.save(update_fields=["is_active"])
        ok, error = approve_erasure(
            PrivacyErasureRequest.objects.get(pk=rid), self.reviewer)
        self.assertFalse(ok)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "pending_review")

    def test_inactive_system_admin_cannot_execute(self):
        from common.models import PrivacyErasureRequest
        from common.privacy_service import execute_erasure
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        ok, error, result = execute_erasure(
            PrivacyErasureRequest.objects.get(pk=rid), self.admin)
        self.assertFalse(ok)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "approved")

    # ----- failed execution cleanup -----
    def test_failed_execution_releases_lock(self):
        from unittest.mock import patch
        from common.models import PrivacyErasureRequest
        from common.privacy_service import execute_erasure
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        # Force an exception during anonymization to test failure cleanup.
        with patch("common.privacy_service._anonymize_user",
                   side_effect=Exception("boom")):
            ok, error, result = execute_erasure(req, self.reviewer)
        self.assertFalse(ok)
        self.assertEqual(error, "Execution failed.")
        req.refresh_from_db()
        self.assertEqual(req.status, "failed")
        self.assertFalse(req.execution_lock)
        self.assertEqual(req.execution_outcome, "failed")
        self.assertEqual(req.execution_error, "execution_failed")


    # ----- audit history -----
    def test_audit_history_records_lifecycle(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        auth(self.c, self.admin)
        self._approve(self.reviewer, rid, reason="approved")
        self._execute(self.reviewer, rid)
        from common.models import AuditLog
        logs = AuditLog.objects.filter(
            entity_type="common.PrivacyErasureRequest", object_id=str(rid))
        actions = [l.action for l in logs.order_by("timestamp")]
        self.assertIn("create", actions)
        self.assertIn("update", actions)
        self.assertIn("hard_delete", actions)
        # No PII in audit records.
        original_email = self.emp.email
        for l in logs:
            blob = f"{l.details}{l.reason}{l.object_repr}"
            self.assertNotIn(original_email, blob)

    # ----- cancellation -----
    def test_cancel_pending_review(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        auth(self.c, self.admin)
        canc = self.c.post(f"/api/common/privacy-erasures/{rid}/cancel/",
                           {"reason": "no longer needed"}, format="json")
        self.assertEqual(canc.status_code, 200)
        self.assertEqual(canc.data["status"], "cancelled")

    def test_cannot_cancel_completed(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        self._approve(self.reviewer, rid)
        self._execute(self.reviewer, rid)
        auth(self.c, self.admin)
        canc = self.c.post(f"/api/common/privacy-erasures/{rid}/cancel/",
                           {"reason": "x"}, format="json")
        self.assertEqual(canc.status_code, 409)

    # ----- history endpoint -----
    def test_history_endpoint(self):
        res = self._create(self.admin)
        rid = res.data["id"]
        auth(self.c, self.admin)
        hist = self.c.get(f"/api/common/privacy-erasures/{rid}/history/")
        self.assertEqual(hist.status_code, 200)
        self.assertGreaterEqual(len(hist.data["results"]), 1)


@override_settings(**LOC)
class EmailFlowTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_reset_request_generic_for_unknown(self):
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "nobody@nowhere"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("If an account exists", res.data["detail"])
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_request_sends_for_known(self):
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["detail"],
                         "If an account exists for that email, a reset link "
                         "has been sent.")
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_confirm_invalid_then_valid(self):
        from accounts.email_utils import (
            decode_uid,  # noqa (ensures helpers import cleanly)
        )
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.emp.pk))
        bad = self.c.post("/api/accounts/password-reset/confirm/",
                          {"uid": uid, "token": "bad",
                           "new_password": "newpass123"}, format="json")
        self.assertEqual(bad.status_code, 400)
        token = PasswordResetTokenGenerator().make_token(self.emp)
        ok = self.c.post("/api/accounts/password-reset/confirm/",
                         {"uid": uid, "token": token,
                          "new_password": "newpass123"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("newpass123"))

    def test_verification_flow(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        import re
        m = re.search(r"uid=(\S+)&token=(\S+)", body)
        uid, token = m.group(1), m.group(2)
        res = self.c.get(
            f"/api/accounts/verify-email/confirm/?uid={uid}&token={token}")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.email_verified)
        bad = self.c.get(
            "/api/accounts/verify-email/confirm/?uid=x&token=y")
        self.assertEqual(bad.status_code, 400)

    def test_ticket_create_sends_notification_but_never_blocks(self):
        auth(self.c, self.mgr)
        tcat = TicketCategory.objects.create(name="EM")
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": tcat.pk,
                               "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(len(mail.outbox) >= 1)


class PrivacyErasureTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.admin2 = User.objects.create_user(
            username="a2@x", email="a2@x", employee_id="A2",
            password="pw12345678", role="system_admin", home_department=self.dep)
        self.c = APIClient()

    def _create(self, user, target, scope="email", reason="r"):
        return self.c.post("/api/common/privacy-erasures/",
                           {"entity_type": "accounts.User",
                            "object_id": str(target.pk),
                            "scope": scope, "reason": reason,
                            "confirm": str(target.pk)}, format="json")

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self._create(self.mgr, self.emp)
        self.assertEqual(res.status_code, 403)

    def test_create_requires_confirm_reason_scope(self):
        auth(self.c, self.admin)
        base = {"entity_type": "accounts.User",
                "object_id": str(self.emp.pk)}
        r1 = self.c.post("/api/common/privacy-erasures/",
                         {**base, "scope": "email", "reason": "r"},
                         format="json")
        self.assertEqual(r1.status_code, 400)
        r2 = self.c.post("/api/common/privacy-erasures/",
                         {**base, "scope": "", "reason": "r",
                          "confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(r2.status_code, 400)

    def test_create_sets_pending_review_and_validates_target(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "pending_review")
        req = PrivacyErasureRequest.objects.get(pk=res.data["id"])
        self.assertEqual(req.requested_by_id, self.admin.pk)
        self.assertIsNone(req.reviewed_by_id)
        self.assertEqual(req.review_decision, "")
        # Unknown target -> 404
        bad = self.c.post("/api/common/privacy-erasures/",
                          {"entity_type": "accounts.User",
                           "object_id": "999999", "scope": "email",
                           "reason": "r", "confirm": "999999"}, format="json")
        self.assertEqual(bad.status_code, 404)
        # Unsupported entity type -> 400
        bad2 = self.c.post("/api/common/privacy-erasures/",
                           {"entity_type": "tickets.Ticket",
                            "object_id": "1", "scope": "all",
                            "reason": "r", "confirm": "1"}, format="json")
        self.assertEqual(bad2.status_code, 400)

    def test_requester_cannot_approve_own_request(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        # Requester approving their own request must be rejected.
        rep = self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                          {"decision": "approve"}, format="json")
        self.assertEqual(rep.status_code, 409)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "pending_review")
        self.assertIsNone(req.reviewed_by_id)

    def test_reviewer_must_be_authorized_admin(self):
        # IT Manager is not a system administrator -> cannot review.
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        auth(self.c, self.mgr)
        rep = self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                          {"decision": "approve"}, format="json")
        # IT Manager is not a system administrator -> forbidden at the gate.
        self.assertEqual(rep.status_code, 403)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "pending_review")
        self.assertIsNone(req.reviewed_by_id)

    def test_reject_requires_reason(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        auth(self.c, self.admin2)
        rep = self.c.post(f"/api/common/privacy-erasures/{rid}/reject/",
                          {"decision": "reject"}, format="json")
        self.assertEqual(rep.status_code, 400)
        self.assertIn("reason", rep.data)

    def test_independent_approve_then_execute_flow(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        # Independent reviewer approves.
        auth(self.c, self.admin2)
        rep = self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                          {"decision": "approve",
                           "reason": "Looks legitimate."}, format="json")
        self.assertEqual(rep.status_code, 200)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "approved")
        self.assertEqual(req.reviewed_by_id, self.admin2.pk)
        self.assertEqual(req.review_decision, "approved")

        # Execution without confirm -> 400.
        ex = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                         {}, format="json")
        self.assertEqual(ex.status_code, 400)

        # Execution with confirm by the executor (may be same as reviewer/admin).
        auth(self.c, self.admin2)
        ex = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                         {"confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(ex.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, "completed")
        self.assertEqual(req.executed_by_id, self.admin2.pk)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.email, f"erased_{self.emp.pk}@erased.local")
        self.assertFalse(self.emp.is_active)

    def test_execute_without_approval_rejected(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        auth(self.c, self.admin2)
        ex = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                         {"confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(ex.status_code, 409)
        self.assertIn("approved", ex.data["detail"].lower())

    def test_duplicate_execution_is_idempotent(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        auth(self.c, self.admin2)
        self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                    {"decision": "approve", "reason": "ok"}, format="json")
        self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                    {"confirm": str(self.emp.pk)}, format="json")
        # Second execution of a completed request -> idempotent success.
        ex2 = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                          {"confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(ex2.status_code, 200)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.email, f"erased_{self.emp.pk}@erased.local")

    def test_full_privacy_audit_trail_excludes_pii(self):
        from common.models import AuditLog
        auth(self.c, self.admin)
        original_email = self.emp.email
        res = self._create(self.admin, self.emp, reason="privacy request #1")
        rid = res.data["id"]
        auth(self.c, self.admin2)
        self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                    {"decision": "approve", "reason": "ok"}, format="json")
        self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                    {"confirm": str(self.emp.pk)}, format="json")
        logs = AuditLog.objects.filter(
            entity_type="common.PrivacyErasureRequest")
        self.assertTrue(logs.exists())
        for log in logs:
            blob = f"{log.details}{log.reason}{log.object_repr}"
            self.assertNotIn(original_email, blob)
        self.emp.refresh_from_db()
        self.assertNotEqual(self.emp.email, original_email)

    def test_reject_flow(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        auth(self.c, self.admin2)
        rep = self.c.post(f"/api/common/privacy-erasures/{rid}/reject/",
                          {"decision": "reject",
                           "reason": "Not eligible."}, format="json")
        self.assertEqual(rep.status_code, 200)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "rejected")
        self.assertEqual(req.review_decision, "rejected")
        self.assertEqual(req.review_reason, "Not eligible.")
        # Rejected request cannot be executed.
        ex = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                         {"confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(ex.status_code, 409)

    def test_invalid_state_transitions(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        # Approving an already-approved request -> 409.
        auth(self.c, self.admin2)
        self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                    {"decision": "approve", "reason": "ok"}, format="json")
        rep2 = self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                           {"decision": "approve"}, format="json")
        self.assertEqual(rep2.status_code, 409)
        # Rejecting an approved request -> 409.
        rej = self.c.post(f"/api/common/privacy-erasures/{rid}/reject/",
                          {"decision": "reject", "reason": "x"},
                          format="json")
        self.assertEqual(rej.status_code, 409)

    def test_cancel_before_approval(self):
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        auth(self.c, self.admin2)
        can = self.c.post(f"/api/common/privacy-erasures/{rid}/cancel/",
                          {"reason": "superseded"}, format="json")
        self.assertEqual(can.status_code, 200)
        req = PrivacyErasureRequest.objects.get(pk=rid)
        self.assertEqual(req.status, "cancelled")

    def test_dependency_analysis_includes_counts_and_retention(self):
        from common.models import AuditLog
        auth(self.c, self.admin)
        res = self._create(self.admin, self.emp)
        rid = res.data["id"]
        detail = self.c.get(f"/api/common/privacy-erasures/{rid}/")
        self.assertEqual(detail.status_code, 200)
        dc = detail.data["dependency_check"]
        self.assertTrue(dc["exists"])
        self.assertIn("related", dc)
        self.assertIn("retention", dc)
        self.assertTrue(any("Audit log" in n for n in dc["retention"]))
        # Audit log row present in audit_history.
        self.assertGreaterEqual(len(detail.data["audit_history"]), 1)

    def test_execute_anonymizes_without_logging_pii(self):
        from common.models import AuditLog
        auth(self.c, self.admin)
        original_email = self.emp.email
        res = self._create(self.admin, self.emp,
                           scope="email, name, phone", reason="privacy request #1")
        self.assertEqual(res.status_code, 201)
        rid = res.data["id"]
        detail = self.c.get(f"/api/common/privacy-erasures/{rid}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("dependency_check", detail.data)
        # Approve independently, then execute.
        auth(self.c, self.admin2)
        self.c.post(f"/api/common/privacy-erasures/{rid}/approve/",
                    {"decision": "approve", "reason": "ok"}, format="json")
        ex = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                         {"confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(ex.status_code, 200)
        self.emp.refresh_from_db()
        self.assertNotEqual(self.emp.email, original_email)
        self.assertFalse(self.emp.is_active)
        logs = AuditLog.objects.filter(
            entity_type="common.PrivacyErasureRequest")
        self.assertTrue(logs.exists())
        for log in logs:
            blob = f"{log.details}{log.reason}{log.object_repr}"
            self.assertNotIn(original_email, blob)


class DataRetentionTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def _policy(self, **kwargs):
        data = {
            "name": "Old notifications",
            "data_category": "notifications",
            "retention_duration": 30,
            "enabled": True,
            "description": "test policy",
            "responsible_admin": self.admin.pk,
        }
        data.update(kwargs)
        return self.c.post("/api/common/retention-policies/", data, format="json")

    def test_non_admin_cannot_manage_retention_policies(self):
        auth(self.c, self.mgr)
        res = self._policy()
        self.assertEqual(res.status_code, 403)

    def test_create_and_list_retention_policy(self):
        auth(self.c, self.admin)
        res = self._policy()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["data_category"], "notifications")
        self.assertTrue(res.data["enabled"])
        auth(self.c, self.admin)
        res = self.c.get("/api/common/retention-policies/")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)

    def test_preview_security_events_excluded(self):
        auth(self.c, self.admin)
        res = self._policy(data_category="security_events", retention_duration=1)
        self.assertEqual(res.status_code, 201)
        pid = res.data["id"]
        from common.models import AuditLog
        AuditLog.objects.create(
            actor=self.admin, action="create",
            entity_type="accounts.User", object_id=str(self.emp.pk),
            object_repr="x")
        prev = self.c.get(f"/api/common/retention-policies/{pid}/preview/")
        self.assertEqual(prev.status_code, 200)
        self.assertEqual(prev.data["total_eligible"], 0)
        self.assertTrue(any("AuditLog" in e.get("model", "")
                            for e in prev.data["excluded"]))

    def test_preview_notifications_excludes_unread(self):
        auth(self.c, self.admin)
        res = self._policy(data_category="notifications", retention_duration=0)
        self.assertEqual(res.status_code, 201)
        pid = res.data["id"]
        from common.models import Notification
        Notification.objects.create(
            recipient=self.emp, title="Unread", body="b", is_read=False)
        Notification.objects.create(
            recipient=self.emp, title="Read", body="b", is_read=True)
        prev = self.c.get(f"/api/common/retention-policies/{pid}/preview/")
        self.assertEqual(prev.status_code, 200)
        self.assertEqual(prev.data["total_eligible"], 1)
        self.assertEqual(prev.data["eligible"]["common.Notification"], 1)

    def test_preview_background_task_runs_excludes_running(self):
        auth(self.c, self.admin)
        res = self._policy(data_category="background_task_runs",
                           retention_duration=0)
        self.assertEqual(res.status_code, 201)
        pid = res.data["id"]
        from common.models import BackgroundTaskRun
        BackgroundTaskRun.objects.create(
            task_name="x", status="running", success=False)
        BackgroundTaskRun.objects.create(
            task_name="y", status="succeeded", success=True)
        prev = self.c.get(f"/api/common/retention-policies/{pid}/preview/")
        self.assertEqual(prev.status_code, 200)
        self.assertEqual(prev.data["total_eligible"], 1)

    def test_execute_notifications_retention(self):
        auth(self.c, self.admin)
        res = self._policy(data_category="notifications", retention_duration=0)
        self.assertEqual(res.status_code, 201)
        pid = res.data["id"]
        from common.models import Notification
        Notification.objects.create(
            recipient=self.emp, title="Read", body="b", is_read=True)
        Notification.objects.create(
            recipient=self.emp, title="Unread", body="b", is_read=False)
        exec_res = self.c.post(
            f"/api/common/retention-policies/{pid}/execute/", {}, format="json")
        self.assertEqual(exec_res.status_code, 200)
        self.assertEqual(exec_res.data["records_affected"], 1)
        self.assertTrue(
            Notification.objects.filter(is_read=False).exists())
        from common.models import DataRetentionExecution
        self.assertTrue(DataRetentionExecution.objects.filter(
            policy_id=pid, status="succeeded").exists())

    def test_disabled_policy_cannot_execute(self):
        auth(self.c, self.admin)
        res = self._policy(enabled=False, data_category="notifications",
                           retention_duration=0)
        self.assertEqual(res.status_code, 201)
        pid = res.data["id"]
        exec_res = self.c.post(
            f"/api/common/retention-policies/{pid}/execute/", {}, format="json")
        self.assertEqual(exec_res.status_code, 409)

    def test_execution_history_list(self):
        auth(self.c, self.admin)
        res = self.c.get("/api/common/retention-executions/")
        self.assertEqual(res.status_code, 200)


@override_settings(**LOC)
class AttachmentStorageTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=self.mgr, department=self.dep)

    def tearDown(self):
        # Remove backing files uploaded during the test. This only touches
        # files referenced by rows in the *test* database, never real user
        # uploads in the dev/prod media directory. gc + retries handle
        # Windows file locks from just-closed download responses.
        import gc
        import time
        gc.collect()
        from tickets.models import TicketAttachment
        for att in TicketAttachment.all_objects.all():
            try:
                if att.file:
                    name = att.file.name
                    try:
                        att.file.close()
                    except Exception:
                        pass
                    for _ in range(5):
                        try:
                            att.file.storage.delete(name)
                        except Exception:
                            time.sleep(0.05)
                            continue
                        break
            except Exception:
                pass

    def test_executable_and_bad_extension_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        auth(self.c, self.mgr)
        t = self._ticket()
        bad = SimpleUploadedFile("evil.exe", b"data",
                                 content_type="application/octet-stream")
        res = self.c.post("/api/tickets/attachments/",
                          {"ticket": t.pk, "file": bad}, format="multipart")
        self.assertEqual(res.status_code, 400)

    def test_safe_filename_and_private_download(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        auth(self.c, self.mgr)
        t = self._ticket()
        up = SimpleUploadedFile("../../note.txt", b"hello",
                                content_type="text/plain")
        res = self.c.post("/api/tickets/attachments/",
                          {"ticket": t.pk, "file": up}, format="multipart")
        self.assertEqual(res.status_code, 201)
        aid = res.data["id"]
        from tickets.models import TicketAttachment
        att = TicketAttachment.objects.get(pk=aid)
        # No traversal, uuid name under ticket_attachments/. (Browsers and
        # Django strip client paths, so the stored name is what matters.)
        self.assertTrue(att.file.name.startswith("ticket_attachments/"))
        self.assertNotIn("..", att.file.name)
        self.assertTrue(att.original_filename.endswith("note.txt"))
        # Owner-side download works with permission check.
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        dl.close()  # release the file handle (Windows locks open files)
        # Employee from another scope cannot list/download it.
        from accounts.models import Department
        other = Department.objects.create(name="Other", code="OTH")
        self.emp.home_department = other
        self.emp.save()
        auth(self.c, self.emp)
        dl2 = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl2.status_code, 404)
        # Soft delete keeps the physical file.
        auth(self.c, self.mgr)
        self.c.delete(f"/api/tickets/attachments/{aid}/")
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)
        self.assertTrue(att.file.storage.exists(att.file.name))


class NotificationReadTests(TestCase):
    """mark_all_read: own notifications only, idempotent, no dismissal."""

    def setUp(self):
        from common.models import Notification
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        for i in range(2):
            Notification.objects.create(recipient=self.emp, title=f"e{i}")
        Notification.objects.create(recipient=self.emp, title="read",
                                    is_read=True)
        Notification.objects.create(recipient=self.mgr, title="m0")
        dismissed = Notification.objects.create(recipient=self.emp,
                                                title="gone")
        dismissed.soft_delete(by_user=self.emp, reason="dismissed")

    def _unread(self, user):
        from common.models import Notification
        return Notification.objects.filter(recipient=user,
                                           is_read=False).count()

    def test_mark_all_read_updates_own_unread(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notifications/mark_all_read/",
                          {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {"updated": 2})
        self.assertEqual(self._unread(self.emp), 0)
        # Another user's notifications untouched.
        self.assertEqual(self._unread(self.mgr), 1)

    def test_mark_all_read_idempotent(self):
        auth(self.c, self.emp)
        self.c.post("/api/common/notifications/mark_all_read/",
                    {}, format="json")
        res = self.c.post("/api/common/notifications/mark_all_read/",
                          {}, format="json")
        self.assertEqual(res.data, {"updated": 0})

    def test_mark_all_read_is_not_dismissal(self):
        from common.models import Notification
        auth(self.c, self.emp)
        self.c.post("/api/common/notifications/mark_all_read/",
                    {}, format="json")
        mine = Notification.objects.filter(recipient=self.emp)
        self.assertEqual(mine.count(), 3)  # dismissed row stays deleted
        self.assertTrue(all(n.is_read for n in mine))

    def test_mark_all_read_requires_auth(self):
        res = self.c.post("/api/common/notifications/mark_all_read/",
                          {}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_single_mark_read_still_works(self):
        from common.models import Notification
        auth(self.c, self.emp)
        n = Notification.objects.filter(recipient=self.emp,
                                        is_read=False).first()
        res = self.c.patch(f"/api/common/notifications/{n.pk}/",
                           {"is_read": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._unread(self.emp), 1)


class NotificationFilterTests(TestCase):
    """Notification list filters and the unread-count badge endpoint."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        Notification.objects.create(
            recipient=self.emp, title="Ticket assigned", body="You own #12",
            entity_type="tickets.Ticket", object_id="12")
        Notification.objects.create(
            recipient=self.emp, title="Asset returned", body="Laptop PR-1",
            entity_type="assets.Asset", object_id="1", is_read=True)
        Notification.objects.create(
            recipient=self.emp, title="Maintenance scheduled",
            body="Server fan replacement",
            entity_type="assets.Maintenance", object_id="7")
        Notification.objects.create(recipient=self.mgr, title="Other user")
        gone = Notification.objects.create(
            recipient=self.emp, title="Dismissed unread")
        gone.soft_delete(by_user=self.emp, reason="dismissed")

    def _list(self, query=""):
        res = self.c.get(f"/api/common/notifications/{query}")
        self.assertEqual(res.status_code, 200)
        return res.data["results"]

    def test_is_read_filter(self):
        auth(self.c, self.emp)
        unread = self._list("?is_read=false")
        self.assertEqual(len(unread), 2)
        self.assertTrue(all(not n["is_read"] for n in unread))
        read = self._list("?is_read=true")
        self.assertEqual([n["title"] for n in read], ["Asset returned"])

    def test_entity_type_filter(self):
        auth(self.c, self.emp)
        assets = self._list("?entity_type=assets.Asset")
        self.assertEqual([n["title"] for n in assets], ["Asset returned"])
        tickets = self._list("?entity_type=tickets.Ticket")
        self.assertEqual([n["title"] for n in tickets], ["Ticket assigned"])

    def test_search_filter_matches_title_or_body(self):
        auth(self.c, self.emp)
        self.assertEqual(
            [n["title"] for n in self._list("?q=maintenance")],
            ["Maintenance scheduled"])
        self.assertEqual(
            [n["title"] for n in self._list("?q=You%20own")],
            ["Ticket assigned"])

    def test_unread_count_is_recipient_scoped(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/notifications/unread_count/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {"count": 2})
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/notifications/unread_count/")
        self.assertEqual(res.data, {"count": 1})

    def test_unread_count_drops_after_mark_all_read(self):
        auth(self.c, self.emp)
        self.c.post("/api/common/notifications/mark_all_read/", {},
                    format="json")
        res = self.c.get("/api/common/notifications/unread_count/")
        self.assertEqual(res.data, {"count": 0})

    def test_unread_count_requires_auth(self):
        res = self.c.get("/api/common/notifications/unread_count/")
        self.assertEqual(res.status_code, 401)


@override_settings(**LOC)
class TicketEmailPreferenceTests(TestCase):
    """Opt out of ticket-event emails only; nothing else changes."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self, requester=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep)

    def test_default_enabled_for_new_and_existing(self):
        self.assertTrue(User._meta.get_field(
            "receive_ticket_emails").default)
        for u in (self.admin, self.mgr, self.emp):
            u.refresh_from_db()
            self.assertTrue(u.receive_ticket_emails)
        fresh = User.objects.create_user(
            username="n@x", email="n@example.com", employee_id="N1",
            password="pw12345678")
        self.assertTrue(fresh.receive_ticket_emails)

    def test_opted_in_assignee_gets_create_email(self):
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_opted_out_assignee_skips_email_only(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(len(mail.outbox), 1)  # requester only
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])
        # In-app notification still created for the assignee.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_opted_out_requester_skips_status_email(self):
        t = self._ticket()
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_bulk_update_sends_no_email_but_notifies(self):
        t1 = self._ticket()
        e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        t2 = Ticket.objects.create(
            title="u", description="d", category=self.tcat,
            requester=e2, department=self.dep)
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t1.pk, t2.pk],
                           "changes": {"status": "in_progress"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t1.pk)).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=e2, object_id=str(t2.pk)).exists())

    def test_self_service_only_and_no_mass_assignment(self):
        auth(self.c, self.emp)
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["receive_ticket_emails"])
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)
        self.mgr.refresh_from_db()
        self.assertTrue(self.mgr.receive_ticket_emails)
        # Protected fields cannot ride along; invalid values rejected.
        res = self.c.patch("/api/accounts/me/", {"role": "system_admin"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.role, "employee")
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": "maybe"},
                           format="json")
        self.assertEqual(res.status_code, 400)

    def test_other_flows_do_not_reset_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.admin)
        res = self.c.post(f"/api/accounts/users/{self.emp.pk}/change_role/",
                          {"role": "employee",
                           "can_create_tickets": True}, format="json")
        self.assertEqual(res.status_code, 200)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/accounts/users/{self.emp.pk}/",
                           {"phone": "111"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_update/",
                          {"rows": [{"employee_id": "E1", "phone": "222"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_import/",
                          {"rows": [{"employee_id": "E1",
                                      "email": "newmail@example.com",
                                      "phone": "333"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)

    def test_verification_and_reset_ignore_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)


class AuditLogFilterTests(TestCase):
    def setUp(self):
        from common.models import AuditLog

        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        AuditLog.objects.create(actor=self.admin, action="create",
                                entity_type="tickets.Ticket", object_id="1")
        AuditLog.objects.create(actor=self.mgr, action="update",
                                entity_type="assets.Asset", object_id="2")

    def _rows(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        return data["results"] if isinstance(data, dict) else data

    def test_admin_sees_all(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get("/api/common/audit-logs/"))
        self.assertEqual(len(rows), 2)

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)

    def test_filter_action(self):
        auth(self.c, self.admin)
        rows = self._rows(
            self.c.get("/api/common/audit-logs/", {"action": "create"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "create")

    def test_filter_action_rejects_unknown(self):
        auth(self.c, self.admin)
        res = self.c.get("/api/common/audit-logs/",
                         {"action": "drop table"})
        self.assertEqual(res.status_code, 400)

    def test_filter_entity_type(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"entity_type": "assets.Asset"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "assets.Asset")

    def test_filter_dates(self):
        from django.utils import timezone

        auth(self.c, self.admin)
        today = timezone.now().date().isoformat()
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": today}))
        self.assertEqual(len(rows), 2)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": "2999-01-01"}))
        self.assertEqual(rows, [])
        res = self.c.get("/api/common/audit-logs/",
                         {"date_from": "not-a-date"})
        self.assertEqual(res.status_code, 400)



class DataIntegrityReportTests(TestCase):
    """READ-ONLY data-integrity report: identifies inconsistent records."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_manager_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_admin_reports_holder_without_open_assignment(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-9", name="n", category=cat,
                             status="assigned", assigned_to=self.emp)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        codes = [i["code"] for i in res.data["issues"]]
        self.assertIn("holder_without_open_assignment", codes)

    def test_clean_state_has_no_issues(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-8", name="n", category=cat)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["issues"], [])


class ExportDatasetTests(TestCase):
    """Read-only multi-format exports (CSV / XLSX / PDF / DOCX)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def test_employees_csv(self):
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("employees_", res["Content-Disposition"])
        self.assertTrue(res.content)

    def test_assets_xlsx(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="A1", name="n", category=cat)
        res = self.c.get("/api/common/exports/assets/?format=xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet", res["Content-Type"])

    def test_tickets_pdf(self):
        res = self.c.get("/api/common/exports/tickets/?format=pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res["Content-Type"])

    def test_departments_docx(self):
        res = self.c.get("/api/common/exports/departments/?format=docx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document", res["Content-Type"])

    def test_unknown_dataset_404(self):
        res = self.c.get("/api/common/exports/nope/?format=csv")
        self.assertEqual(res.status_code, 404)

    def test_unsupported_format_is_rejected(self):
        res = self.c.get("/api/common/exports/assets/?format=exe")
        self.assertNotEqual(res.status_code, 200)

    def test_employee_forbidden_on_employees_export(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_selected_scope_returns_only_requested_rows(self):
        from accounts.models import User
        extra = User.objects.create_user(
            username="e9@x", email="e9@example.com", employee_id="E9",
            password="pw12345678", home_department=self.dep)
        res = self.c.get(
            f"/api/common/exports/employees/?format=csv&scope=selected&ids={extra.pk},{self.emp.pk}")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("e9@example.com", blob)
        self.assertIn("E9", blob)

    def test_export_writes_audit_log(self):
        from common.models import AuditLog
        before = AuditLog.objects.filter(action="export").count()
        res = self.c.get("/api/common/exports/tickets/?format=csv")
        self.assertEqual(res.status_code, 200)
        after = AuditLog.objects.filter(action="export").count()
        self.assertEqual(after, before + 1)

    def test_employee_forbidden_on_assignments_export(self):
        """Assignments carry employee_email/assigned_by_email (PII); export
        must require IT staff, matching the employees dataset."""
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_it_staff_can_export_assignments(self):
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 200)

    def test_employee_asset_export_limited_to_visible_assets(self):
        """The assets export must not bypass the asset list API's employee
        scope (assigned to the employee or in their home department)."""
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other", code="OTHR")
        visible_cat = AssetCategory.objects.create(name="Visible")
        hidden_cat = AssetCategory.objects.create(name="Hidden")
        visible = Asset.objects.create(
            asset_tag="VISIBLE-1", name="visible", category=visible_cat,
            department=self.dep, assigned_to=self.emp, status="assigned")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-1", name="hidden", category=hidden_cat,
            department=other_dep)

        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("VISIBLE-1", blob)
        self.assertNotIn("HIDDEN-1", blob)

    def test_it_staff_asset_export_sees_all_assets(self):
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other2", code="OT2")
        hidden_cat = AssetCategory.objects.create(name="Hidden2")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-2", name="hidden", category=hidden_cat,
            department=other_dep)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("HIDDEN-2", blob)



class UserNotificationPreferenceTests(TestCase):
    """Notification preference API permissions + centralized enforcement."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    # ---------- API: own-only access ----------

    def test_employee_creates_own_preference_record(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True,
                           "categories": {"ticket_assignment": False}},
                          format="json")
        self.assertEqual(res.status_code, 201)
        from common.models import UserNotificationPreference
        self.assertTrue(UserNotificationPreference.objects.filter(
            user=self.emp).exists())

    def test_employee_cannot_read_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o@x", email="o@example.com", employee_id="O1",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.get(
            f"/api/common/notification-preferences/{prefs.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_update_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o2@x", email="o2@example.com", employee_id="O2",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.patch(
            f"/api/common/notification-preferences/{prefs.pk}/",
            {"email_enabled": True}, format="json")
        self.assertEqual(res.status_code, 404)
        prefs.refresh_from_db()
        self.assertFalse(prefs.email_enabled)

    def test_it_staff_can_view_all_preferences_for_auditing(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o3@x", email="o3@example.com", employee_id="O3",
            password="pw12345678")
        UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True, categories={})
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/notification-preferences/")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 2)

    def test_invalid_category_value_rejected(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True, "categories": {"bogus": True}},
                          format="json")
        self.assertEqual(res.status_code, 400)

    # ---------- Enforcement: enabled / disabled / missing / category ----------

    def _create_ticket(self, requester=None, assignee=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep,
            assignee=assignee)

    def test_missing_preference_record_defaults_to_enabled(self):
        # No UserNotificationPreference row exists for emp -> default opt-in.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_global_master_switch_off_suppresses_ticket_emails(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail goes to the requester (master on); the opted-out
        # assignee (emp) receives nothing.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])

    def test_category_opt_out_only_affects_that_category(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True,
            categories={"ticket_status_change": False})
        # emp creates a ticket -> creation email (master switch) flows.
        auth(self.c, self.emp)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)  # creation to emp (master) flows
        t = Ticket.objects.get(title="t")
        # Status change -> requester (emp) opted out of ticket_status_change
        # -> suppressed, while creation (master) still delivered.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.patch(f"/api/tickets/{t.pk}/",
                               {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)  # no status email

        # The opt-out did not block the unrelated ticket_assignment category:
        # a staff-created ticket assigned to emp still delivers the assignee.
        before = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t2", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), before + 2)  # creation + assignment

    def test_essential_security_emails_not_suppressed(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        mail.outbox.clear()
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_in_app_notification_independent_of_email_preferences(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail to the requester (staff) still goes out; the opted-out
        # assignee (emp) is email-suppressed ...
        self.assertEqual(len(mail.outbox), 1)
        # ... but the in-app notification for the assignee is unaffected.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp).exists())


@override_settings(**LOC)
class TicketNotificationTransactionTests(TestCase):
    """Regression coverage for accounts.email_utils._notify_user.

    The in-app notification must be created only after the surrounding
    transaction commits, so a rolled-back ticket creation or state change
    never leaves an orphaned notification pointing at a non-existent or
    reverted record.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket",
            description="existing",
            category=self.tcat,
            priority="medium",
            status="open",
            requester=self.emp,
            department=self.dep)

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_rolled_back_with_transaction(self):
        from accounts.email_utils import _notify_user
        try:
            with transaction.atomic():
                self._notify()
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_defers_until_commit(self):
        from accounts.email_utils import _notify_user
        self._notify(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_returns_none(self):
        from accounts.email_utils import _notify_user
        self.assertIsNone(self._notify())

    def test_notify_user_skips_invalid_recipients(self):
        from accounts.email_utils import _notify_user
        _notify_user(None, self.emp, "t", "b", self.ticket)
        _notify_user(self.mgr, None, "t", "b", self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

@override_settings(**LOC)
class TicketEmailPreferenceTests(TestCase):
    """Opt out of ticket-event emails only; nothing else changes."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self, requester=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep)

    def test_default_enabled_for_new_and_existing(self):
        self.assertTrue(User._meta.get_field(
            "receive_ticket_emails").default)
        for u in (self.admin, self.mgr, self.emp):
            u.refresh_from_db()
            self.assertTrue(u.receive_ticket_emails)
        fresh = User.objects.create_user(
            username="n@x", email="n@example.com", employee_id="N1",
            password="pw12345678")
        self.assertTrue(fresh.receive_ticket_emails)

    def test_opted_in_assignee_gets_create_email(self):
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_opted_out_assignee_skips_email_only(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(len(mail.outbox), 1)  # requester only
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])
        # In-app notification still created for the assignee.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_opted_out_requester_skips_status_email(self):
        t = self._ticket()
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_bulk_update_sends_no_email_but_notifies(self):
        t1 = self._ticket()
        e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        t2 = Ticket.objects.create(
            title="u", description="d", category=self.tcat,
            requester=e2, department=self.dep)
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t1.pk, t2.pk],
                           "changes": {"status": "in_progress"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t1.pk)).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=e2, object_id=str(t2.pk)).exists())

    def test_self_service_only_and_no_mass_assignment(self):
        auth(self.c, self.emp)
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["receive_ticket_emails"])
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)
        self.mgr.refresh_from_db()
        self.assertTrue(self.mgr.receive_ticket_emails)
        # Protected fields cannot ride along; invalid values rejected.
        res = self.c.patch("/api/accounts/me/", {"role": "system_admin"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.role, "employee")
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": "maybe"},
                           format="json")
        self.assertEqual(res.status_code, 400)

    def test_other_flows_do_not_reset_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.admin)
        res = self.c.post(f"/api/accounts/users/{self.emp.pk}/change_role/",
                          {"role": "employee",
                           "can_create_tickets": True}, format="json")
        self.assertEqual(res.status_code, 200)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/accounts/users/{self.emp.pk}/",
                           {"phone": "111"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_update/",
                          {"rows": [{"employee_id": "E1", "phone": "222"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_import/",
                          {"rows": [{"employee_id": "E1",
                                      "email": "newmail@example.com",
                                      "phone": "333"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)

    def test_verification_and_reset_ignore_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)


class AuditLogFilterTests(TestCase):
    def setUp(self):
        from common.models import AuditLog

        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        AuditLog.objects.create(actor=self.admin, action="create",
                                entity_type="tickets.Ticket", object_id="1")
        AuditLog.objects.create(actor=self.mgr, action="update",
                                entity_type="assets.Asset", object_id="2")

    def _rows(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        return data["results"] if isinstance(data, dict) else data

    def test_admin_sees_all(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get("/api/common/audit-logs/"))
        self.assertEqual(len(rows), 2)

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)

    def test_filter_action(self):
        auth(self.c, self.admin)
        rows = self._rows(
            self.c.get("/api/common/audit-logs/", {"action": "create"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "create")

    def test_filter_action_rejects_unknown(self):
        auth(self.c, self.admin)
        res = self.c.get("/api/common/audit-logs/",
                         {"action": "drop table"})
        self.assertEqual(res.status_code, 400)

    def test_filter_entity_type(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"entity_type": "assets.Asset"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "assets.Asset")

    def test_filter_dates(self):
        from django.utils import timezone

        auth(self.c, self.admin)
        today = timezone.now().date().isoformat()
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": today}))
        self.assertEqual(len(rows), 2)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": "2999-01-01"}))
        self.assertEqual(rows, [])
        res = self.c.get("/api/common/audit-logs/",
                         {"date_from": "not-a-date"})
        self.assertEqual(res.status_code, 400)



class DataIntegrityReportTests(TestCase):
    """READ-ONLY data-integrity report: identifies inconsistent records."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_manager_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_admin_reports_holder_without_open_assignment(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-9", name="n", category=cat,
                             status="assigned", assigned_to=self.emp)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        codes = [i["code"] for i in res.data["issues"]]
        self.assertIn("holder_without_open_assignment", codes)

    def test_clean_state_has_no_issues(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-8", name="n", category=cat)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["issues"], [])


class ExportDatasetTests(TestCase):
    """Read-only multi-format exports (CSV / XLSX / PDF / DOCX)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def test_employees_csv(self):
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("employees_", res["Content-Disposition"])
        self.assertTrue(res.content)

    def test_assets_xlsx(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="A1", name="n", category=cat)
        res = self.c.get("/api/common/exports/assets/?format=xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet", res["Content-Type"])

    def test_tickets_pdf(self):
        res = self.c.get("/api/common/exports/tickets/?format=pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res["Content-Type"])

    def test_departments_docx(self):
        res = self.c.get("/api/common/exports/departments/?format=docx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document", res["Content-Type"])

    def test_unknown_dataset_404(self):
        res = self.c.get("/api/common/exports/nope/?format=csv")
        self.assertEqual(res.status_code, 404)

    def test_unsupported_format_is_rejected(self):
        res = self.c.get("/api/common/exports/assets/?format=exe")
        self.assertNotEqual(res.status_code, 200)

    def test_employee_forbidden_on_employees_export(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_selected_scope_returns_only_requested_rows(self):
        from accounts.models import User
        extra = User.objects.create_user(
            username="e9@x", email="e9@example.com", employee_id="E9",
            password="pw12345678", home_department=self.dep)
        res = self.c.get(
            f"/api/common/exports/employees/?format=csv&scope=selected&ids={extra.pk},{self.emp.pk}")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("e9@example.com", blob)
        self.assertIn("E9", blob)

    def test_export_writes_audit_log(self):
        from common.models import AuditLog
        before = AuditLog.objects.filter(action="export").count()
        res = self.c.get("/api/common/exports/tickets/?format=csv")
        self.assertEqual(res.status_code, 200)
        after = AuditLog.objects.filter(action="export").count()
        self.assertEqual(after, before + 1)

    def test_employee_forbidden_on_assignments_export(self):
        """Assignments carry employee_email/assigned_by_email (PII); export
        must require IT staff, matching the employees dataset."""
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_it_staff_can_export_assignments(self):
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 200)

    def test_employee_asset_export_limited_to_visible_assets(self):
        """The assets export must not bypass the asset list API's employee
        scope (assigned to the employee or in their home department)."""
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other", code="OTHR")
        visible_cat = AssetCategory.objects.create(name="Visible")
        hidden_cat = AssetCategory.objects.create(name="Hidden")
        visible = Asset.objects.create(
            asset_tag="VISIBLE-1", name="visible", category=visible_cat,
            department=self.dep, assigned_to=self.emp, status="assigned")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-1", name="hidden", category=hidden_cat,
            department=other_dep)

        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("VISIBLE-1", blob)
        self.assertNotIn("HIDDEN-1", blob)

    def test_it_staff_asset_export_sees_all_assets(self):
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other2", code="OT2")
        hidden_cat = AssetCategory.objects.create(name="Hidden2")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-2", name="hidden", category=hidden_cat,
            department=other_dep)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("HIDDEN-2", blob)



class UserNotificationPreferenceTests(TestCase):
    """Notification preference API permissions + centralized enforcement."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    # ---------- API: own-only access ----------

    def test_employee_creates_own_preference_record(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True,
                           "categories": {"ticket_assignment": False}},
                          format="json")
        self.assertEqual(res.status_code, 201)
        from common.models import UserNotificationPreference
        self.assertTrue(UserNotificationPreference.objects.filter(
            user=self.emp).exists())

    def test_employee_cannot_read_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o@x", email="o@example.com", employee_id="O1",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.get(
            f"/api/common/notification-preferences/{prefs.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_update_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o2@x", email="o2@example.com", employee_id="O2",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.patch(
            f"/api/common/notification-preferences/{prefs.pk}/",
            {"email_enabled": True}, format="json")
        self.assertEqual(res.status_code, 404)
        prefs.refresh_from_db()
        self.assertFalse(prefs.email_enabled)

    def test_it_staff_can_view_all_preferences_for_auditing(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o3@x", email="o3@example.com", employee_id="O3",
            password="pw12345678")
        UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True, categories={})
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/notification-preferences/")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 2)

    def test_invalid_category_value_rejected(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True, "categories": {"bogus": True}},
                          format="json")
        self.assertEqual(res.status_code, 400)

    # ---------- Enforcement: enabled / disabled / missing / category ----------

    def _create_ticket(self, requester=None, assignee=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep,
            assignee=assignee)

    def test_missing_preference_record_defaults_to_enabled(self):
        # No UserNotificationPreference row exists for emp -> default opt-in.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_global_master_switch_off_suppresses_ticket_emails(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail goes to the requester (master on); the opted-out
        # assignee (emp) receives nothing.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])

    def test_category_opt_out_only_affects_that_category(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True,
            categories={"ticket_status_change": False})
        # emp creates a ticket -> creation email (master switch) flows.
        auth(self.c, self.emp)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)  # creation to emp (master) flows
        t = Ticket.objects.get(title="t")
        # Status change -> requester (emp) opted out of ticket_status_change
        # -> suppressed, while creation (master) still delivered.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.patch(f"/api/tickets/{t.pk}/",
                               {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)  # no status email

        # The opt-out did not block the unrelated ticket_assignment category:
        # a staff-created ticket assigned to emp still delivers the assignee.
        before = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t2", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), before + 2)  # creation + assignment

    def test_essential_security_emails_not_suppressed(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        mail.outbox.clear()
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_in_app_notification_independent_of_email_preferences(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail to the requester (staff) still goes out; the opted-out
        # assignee (emp) is email-suppressed ...
        self.assertEqual(len(mail.outbox), 1)
        # ... but the in-app notification for the assignee is unaffected.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp).exists())


@override_settings(**LOC)
class TicketNotificationTransactionTests(TransactionTestCase):
    """Regression coverage for accounts.email_utils._notify_user.

    The in-app notification must be created only after the surrounding
    transaction commits, so a rolled-back ticket creation or state change
    never leaves an orphaned notification pointing at a non-existent or
    reverted record.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket",
            description="existing",
            category=self.tcat,
            priority="medium",
            status="open",
            requester=self.emp,
            department=self.dep)

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        # Inside an atomic block: deferred, not yet visible.
        with transaction.atomic():
            self._notify()
            self.assertEqual(Notification.objects.count(), 0)
        # After the inner transaction commits: created.
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")

    def test_notify_user_rolled_back_with_transaction(self):
        from accounts.email_utils import _notify_user
        try:
            with transaction.atomic():
                self._notify()
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_defers_until_commit(self):
        from accounts.email_utils import _notify_user
        # Inside the test's atomic block: deferred, not visible yet.
        self._notify()
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_returns_none(self):
        from accounts.email_utils import _notify_user
        self.assertIsNone(self._notify())

    def test_notify_user_skips_invalid_recipients(self):
        from accounts.email_utils import _notify_user
        _notify_user(None, self.emp, "t", "b", self.ticket)
        _notify_user(self.mgr, None, "t", "b", self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

@override_settings(**LOC)
class TicketEmailPreferenceTests(TestCase):
    """Opt out of ticket-event emails only; nothing else changes."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self, requester=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep)

    def test_default_enabled_for_new_and_existing(self):
        self.assertTrue(User._meta.get_field(
            "receive_ticket_emails").default)
        for u in (self.admin, self.mgr, self.emp):
            u.refresh_from_db()
            self.assertTrue(u.receive_ticket_emails)
        fresh = User.objects.create_user(
            username="n@x", email="n@example.com", employee_id="N1",
            password="pw12345678")
        self.assertTrue(fresh.receive_ticket_emails)

    def test_opted_in_assignee_gets_create_email(self):
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_opted_out_assignee_skips_email_only(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(len(mail.outbox), 1)  # requester only
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])
        # In-app notification still created for the assignee.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_opted_out_requester_skips_status_email(self):
        t = self._ticket()
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_bulk_update_sends_no_email_but_notifies(self):
        t1 = self._ticket()
        e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        t2 = Ticket.objects.create(
            title="u", description="d", category=self.tcat,
            requester=e2, department=self.dep)
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t1.pk, t2.pk],
                           "changes": {"status": "in_progress"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t1.pk)).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=e2, object_id=str(t2.pk)).exists())

    def test_self_service_only_and_no_mass_assignment(self):
        auth(self.c, self.emp)
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["receive_ticket_emails"])
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)
        self.mgr.refresh_from_db()
        self.assertTrue(self.mgr.receive_ticket_emails)
        # Protected fields cannot ride along; invalid values rejected.
        res = self.c.patch("/api/accounts/me/", {"role": "system_admin"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.role, "employee")
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": "maybe"},
                           format="json")
        self.assertEqual(res.status_code, 400)

    def test_other_flows_do_not_reset_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.admin)
        res = self.c.post(f"/api/accounts/users/{self.emp.pk}/change_role/",
                          {"role": "employee",
                           "can_create_tickets": True}, format="json")
        self.assertEqual(res.status_code, 200)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/accounts/users/{self.emp.pk}/",
                           {"phone": "111"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_update/",
                          {"rows": [{"employee_id": "E1", "phone": "222"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_import/",
                          {"rows": [{"employee_id": "E1",
                                      "email": "newmail@example.com",
                                      "phone": "333"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)

    def test_verification_and_reset_ignore_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)


class AuditLogFilterTests(TestCase):
    def setUp(self):
        from common.models import AuditLog

        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        AuditLog.objects.create(actor=self.admin, action="create",
                                entity_type="tickets.Ticket", object_id="1")
        AuditLog.objects.create(actor=self.mgr, action="update",
                                entity_type="assets.Asset", object_id="2")

    def _rows(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        return data["results"] if isinstance(data, dict) else data

    def test_admin_sees_all(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get("/api/common/audit-logs/"))
        self.assertEqual(len(rows), 2)

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)

    def test_filter_action(self):
        auth(self.c, self.admin)
        rows = self._rows(
            self.c.get("/api/common/audit-logs/", {"action": "create"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "create")

    def test_filter_action_rejects_unknown(self):
        auth(self.c, self.admin)
        res = self.c.get("/api/common/audit-logs/",
                         {"action": "drop table"})
        self.assertEqual(res.status_code, 400)

    def test_filter_entity_type(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"entity_type": "assets.Asset"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "assets.Asset")

    def test_filter_dates(self):
        from django.utils import timezone

        auth(self.c, self.admin)
        today = timezone.now().date().isoformat()
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": today}))
        self.assertEqual(len(rows), 2)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": "2999-01-01"}))
        self.assertEqual(rows, [])
        res = self.c.get("/api/common/audit-logs/",
                         {"date_from": "not-a-date"})
        self.assertEqual(res.status_code, 400)



class DataIntegrityReportTests(TestCase):
    """READ-ONLY data-integrity report: identifies inconsistent records."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_manager_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_admin_reports_holder_without_open_assignment(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-9", name="n", category=cat,
                             status="assigned", assigned_to=self.emp)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        codes = [i["code"] for i in res.data["issues"]]
        self.assertIn("holder_without_open_assignment", codes)

    def test_clean_state_has_no_issues(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-8", name="n", category=cat)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["issues"], [])


class ExportDatasetTests(TestCase):
    """Read-only multi-format exports (CSV / XLSX / PDF / DOCX)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def test_employees_csv(self):
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("employees_", res["Content-Disposition"])
        self.assertTrue(res.content)

    def test_assets_xlsx(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="A1", name="n", category=cat)
        res = self.c.get("/api/common/exports/assets/?format=xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet", res["Content-Type"])

    def test_tickets_pdf(self):
        res = self.c.get("/api/common/exports/tickets/?format=pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res["Content-Type"])

    def test_departments_docx(self):
        res = self.c.get("/api/common/exports/departments/?format=docx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document", res["Content-Type"])

    def test_unknown_dataset_404(self):
        res = self.c.get("/api/common/exports/nope/?format=csv")
        self.assertEqual(res.status_code, 404)

    def test_unsupported_format_is_rejected(self):
        res = self.c.get("/api/common/exports/assets/?format=exe")
        self.assertNotEqual(res.status_code, 200)

    def test_employee_forbidden_on_employees_export(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_selected_scope_returns_only_requested_rows(self):
        from accounts.models import User
        extra = User.objects.create_user(
            username="e9@x", email="e9@example.com", employee_id="E9",
            password="pw12345678", home_department=self.dep)
        res = self.c.get(
            f"/api/common/exports/employees/?format=csv&scope=selected&ids={extra.pk},{self.emp.pk}")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("e9@example.com", blob)
        self.assertIn("E9", blob)

    def test_export_writes_audit_log(self):
        from common.models import AuditLog
        before = AuditLog.objects.filter(action="export").count()
        res = self.c.get("/api/common/exports/tickets/?format=csv")
        self.assertEqual(res.status_code, 200)
        after = AuditLog.objects.filter(action="export").count()
        self.assertEqual(after, before + 1)

    def test_employee_forbidden_on_assignments_export(self):
        """Assignments carry employee_email/assigned_by_email (PII); export
        must require IT staff, matching the employees dataset."""
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_it_staff_can_export_assignments(self):
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 200)

    def test_employee_asset_export_limited_to_visible_assets(self):
        """The assets export must not bypass the asset list API's employee
        scope (assigned to the employee or in their home department)."""
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other", code="OTHR")
        visible_cat = AssetCategory.objects.create(name="Visible")
        hidden_cat = AssetCategory.objects.create(name="Hidden")
        visible = Asset.objects.create(
            asset_tag="VISIBLE-1", name="visible", category=visible_cat,
            department=self.dep, assigned_to=self.emp, status="assigned")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-1", name="hidden", category=hidden_cat,
            department=other_dep)

        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("VISIBLE-1", blob)
        self.assertNotIn("HIDDEN-1", blob)

    def test_it_staff_asset_export_sees_all_assets(self):
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other2", code="OT2")
        hidden_cat = AssetCategory.objects.create(name="Hidden2")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-2", name="hidden", category=hidden_cat,
            department=other_dep)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("HIDDEN-2", blob)



class UserNotificationPreferenceTests(TestCase):
    """Notification preference API permissions + centralized enforcement."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    # ---------- API: own-only access ----------

    def test_employee_creates_own_preference_record(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True,
                           "categories": {"ticket_assignment": False}},
                          format="json")
        self.assertEqual(res.status_code, 201)
        from common.models import UserNotificationPreference
        self.assertTrue(UserNotificationPreference.objects.filter(
            user=self.emp).exists())

    def test_employee_cannot_read_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o@x", email="o@example.com", employee_id="O1",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.get(
            f"/api/common/notification-preferences/{prefs.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_update_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o2@x", email="o2@example.com", employee_id="O2",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.patch(
            f"/api/common/notification-preferences/{prefs.pk}/",
            {"email_enabled": True}, format="json")
        self.assertEqual(res.status_code, 404)
        prefs.refresh_from_db()
        self.assertFalse(prefs.email_enabled)

    def test_it_staff_can_view_all_preferences_for_auditing(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o3@x", email="o3@example.com", employee_id="O3",
            password="pw12345678")
        UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True, categories={})
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/notification-preferences/")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 2)

    def test_invalid_category_value_rejected(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True, "categories": {"bogus": True}},
                          format="json")
        self.assertEqual(res.status_code, 400)

    # ---------- Enforcement: enabled / disabled / missing / category ----------

    def _create_ticket(self, requester=None, assignee=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep,
            assignee=assignee)

    def test_missing_preference_record_defaults_to_enabled(self):
        # No UserNotificationPreference row exists for emp -> default opt-in.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_global_master_switch_off_suppresses_ticket_emails(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail goes to the requester (master on); the opted-out
        # assignee (emp) receives nothing.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])

    def test_category_opt_out_only_affects_that_category(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True,
            categories={"ticket_status_change": False})
        # emp creates a ticket -> creation email (master switch) flows.
        auth(self.c, self.emp)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)  # creation to emp (master) flows
        t = Ticket.objects.get(title="t")
        # Status change -> requester (emp) opted out of ticket_status_change
        # -> suppressed, while creation (master) still delivered.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.patch(f"/api/tickets/{t.pk}/",
                               {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)  # no status email

        # The opt-out did not block the unrelated ticket_assignment category:
        # a staff-created ticket assigned to emp still delivers the assignee.
        before = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t2", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), before + 2)  # creation + assignment

    def test_essential_security_emails_not_suppressed(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        mail.outbox.clear()
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_in_app_notification_independent_of_email_preferences(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail to the requester (staff) still goes out; the opted-out
        # assignee (emp) is email-suppressed ...
        self.assertEqual(len(mail.outbox), 1)
        # ... but the in-app notification for the assignee is unaffected.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp).exists())


@override_settings(**LOC)
class TicketNotificationTransactionTests(TestCase):
    """Regression coverage for accounts.email_utils._notify_user.

    The in-app notification must be created only after the surrounding
    transaction commits, so a rolled-back ticket creation or state change
    never leaves an orphaned notification pointing at a non-existent or
    reverted record.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket",
            description="existing",
            category=self.tcat,
            priority="medium",
            status="open",
            requester=self.emp,
            department=self.dep)

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        # The callback is registered but not executed until commit.
        with self.captureOnCommitCallbacks() as callbacks:
            _notify_user(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        # Simulate the commit: execute the captured callback.
        callbacks[0]()
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")

    def test_notify_user_rolled_back_with_transaction(self):
        from accounts.email_utils import _notify_user
        try:
            with transaction.atomic():
                _notify_user(
                    self.mgr, self.emp,
                    "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                    self.ticket)
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_outside_transaction(self):
        from accounts.email_utils import _notify_user
        self.assertEqual(Notification.objects.count(), 0)
        _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.object_id, str(self.ticket.pk))

    def test_notify_user_returns_none(self):
        from accounts.email_utils import _notify_user
        self.assertIsNone(
            _notify_user(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket))

    def test_notify_user_skips_invalid_recipients(self):
        from accounts.email_utils import _notify_user
        _notify_user(None, self.emp, "t", "b", self.ticket)
        _notify_user(self.mgr, None, "t", "b", self.ticket)
        self.assertEqual(Notification.objects.count(), 0)


@override_settings(**LOC)
class TicketEmailPreferenceTests(TestCase):
    """Opt out of ticket-event emails only; nothing else changes."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self, requester=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep)

    def test_default_enabled_for_new_and_existing(self):
        self.assertTrue(User._meta.get_field(
            "receive_ticket_emails").default)
        for u in (self.admin, self.mgr, self.emp):
            u.refresh_from_db()
            self.assertTrue(u.receive_ticket_emails)
        fresh = User.objects.create_user(
            username="n@x", email="n@example.com", employee_id="N1",
            password="pw12345678")
        self.assertTrue(fresh.receive_ticket_emails)

    def test_opted_in_assignee_gets_create_email(self):
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_opted_out_assignee_skips_email_only(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(len(mail.outbox), 1)  # requester only
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])
        # In-app notification still created for the assignee.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_opted_out_requester_skips_status_email(self):
        t = self._ticket()
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_bulk_update_sends_no_email_but_notifies(self):
        t1 = self._ticket()
        e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        t2 = Ticket.objects.create(
            title="u", description="d", category=self.tcat,
            requester=e2, department=self.dep)
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t1.pk, t2.pk],
                           "changes": {"status": "in_progress"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t1.pk)).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=e2, object_id=str(t2.pk)).exists())

    def test_self_service_only_and_no_mass_assignment(self):
        auth(self.c, self.emp)
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["receive_ticket_emails"])
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)
        self.mgr.refresh_from_db()
        self.assertTrue(self.mgr.receive_ticket_emails)
        # Protected fields cannot ride along; invalid values rejected.
        res = self.c.patch("/api/accounts/me/", {"role": "system_admin"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.role, "employee")
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": "maybe"},
                           format="json")
        self.assertEqual(res.status_code, 400)

    def test_other_flows_do_not_reset_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.admin)
        res = self.c.post(f"/api/accounts/users/{self.emp.pk}/change_role/",
                          {"role": "employee",
                           "can_create_tickets": True}, format="json")
        self.assertEqual(res.status_code, 200)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/accounts/users/{self.emp.pk}/",
                           {"phone": "111"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_update/",
                          {"rows": [{"employee_id": "E1", "phone": "222"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_import/",
                          {"rows": [{"employee_id": "E1",
                                      "email": "newmail@example.com",
                                      "phone": "333"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)

    def test_verification_and_reset_ignore_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)


class AuditLogFilterTests(TestCase):
    def setUp(self):
        from common.models import AuditLog

        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        AuditLog.objects.create(actor=self.admin, action="create",
                                entity_type="tickets.Ticket", object_id="1")
        AuditLog.objects.create(actor=self.mgr, action="update",
                                entity_type="assets.Asset", object_id="2")

    def _rows(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        return data["results"] if isinstance(data, dict) else data

    def test_admin_sees_all(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get("/api/common/audit-logs/"))
        self.assertEqual(len(rows), 2)

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)

    def test_filter_action(self):
        auth(self.c, self.admin)
        rows = self._rows(
            self.c.get("/api/common/audit-logs/", {"action": "create"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "create")

    def test_filter_action_rejects_unknown(self):
        auth(self.c, self.admin)
        res = self.c.get("/api/common/audit-logs/",
                         {"action": "drop table"})
        self.assertEqual(res.status_code, 400)

    def test_filter_entity_type(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"entity_type": "assets.Asset"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "assets.Asset")

    def test_filter_dates(self):
        from django.utils import timezone

        auth(self.c, self.admin)
        today = timezone.now().date().isoformat()
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": today}))
        self.assertEqual(len(rows), 2)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": "2999-01-01"}))
        self.assertEqual(rows, [])
        res = self.c.get("/api/common/audit-logs/",
                         {"date_from": "not-a-date"})
        self.assertEqual(res.status_code, 400)



class DataIntegrityReportTests(TestCase):
    """READ-ONLY data-integrity report: identifies inconsistent records."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_manager_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_admin_reports_holder_without_open_assignment(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-9", name="n", category=cat,
                             status="assigned", assigned_to=self.emp)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        codes = [i["code"] for i in res.data["issues"]]
        self.assertIn("holder_without_open_assignment", codes)

    def test_clean_state_has_no_issues(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-8", name="n", category=cat)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["issues"], [])


class ExportDatasetTests(TestCase):
    """Read-only multi-format exports (CSV / XLSX / PDF / DOCX)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def test_employees_csv(self):
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("employees_", res["Content-Disposition"])
        self.assertTrue(res.content)

    def test_assets_xlsx(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="A1", name="n", category=cat)
        res = self.c.get("/api/common/exports/assets/?format=xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet", res["Content-Type"])

    def test_tickets_pdf(self):
        res = self.c.get("/api/common/exports/tickets/?format=pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res["Content-Type"])

    def test_departments_docx(self):
        res = self.c.get("/api/common/exports/departments/?format=docx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document", res["Content-Type"])

    def test_unknown_dataset_404(self):
        res = self.c.get("/api/common/exports/nope/?format=csv")
        self.assertEqual(res.status_code, 404)

    def test_unsupported_format_is_rejected(self):
        res = self.c.get("/api/common/exports/assets/?format=exe")
        self.assertNotEqual(res.status_code, 200)

    def test_employee_forbidden_on_employees_export(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_selected_scope_returns_only_requested_rows(self):
        from accounts.models import User
        extra = User.objects.create_user(
            username="e9@x", email="e9@example.com", employee_id="E9",
            password="pw12345678", home_department=self.dep)
        res = self.c.get(
            f"/api/common/exports/employees/?format=csv&scope=selected&ids={extra.pk},{self.emp.pk}")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("e9@example.com", blob)
        self.assertIn("E9", blob)

    def test_export_writes_audit_log(self):
        from common.models import AuditLog
        before = AuditLog.objects.filter(action="export").count()
        res = self.c.get("/api/common/exports/tickets/?format=csv")
        self.assertEqual(res.status_code, 200)
        after = AuditLog.objects.filter(action="export").count()
        self.assertEqual(after, before + 1)

    def test_employee_forbidden_on_assignments_export(self):
        """Assignments carry employee_email/assigned_by_email (PII); export
        must require IT staff, matching the employees dataset."""
        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_it_staff_can_export_assignments(self):
        res = self.c.get("/api/common/exports/assignments/?format=csv")
        self.assertEqual(res.status_code, 200)

    def test_employee_asset_export_limited_to_visible_assets(self):
        """The assets export must not bypass the asset list API's employee
        scope (assigned to the employee or in their home department)."""
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other", code="OTHR")
        visible_cat = AssetCategory.objects.create(name="Visible")
        hidden_cat = AssetCategory.objects.create(name="Hidden")
        visible = Asset.objects.create(
            asset_tag="VISIBLE-1", name="visible", category=visible_cat,
            department=self.dep, assigned_to=self.emp, status="assigned")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-1", name="hidden", category=hidden_cat,
            department=other_dep)

        auth(self.c, self.emp)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("VISIBLE-1", blob)
        self.assertNotIn("HIDDEN-1", blob)

    def test_it_staff_asset_export_sees_all_assets(self):
        from accounts.models import Department
        from assets.models import Asset, AssetCategory
        other_dep = Department.objects.create(name="Other2", code="OT2")
        hidden_cat = AssetCategory.objects.create(name="Hidden2")
        hidden = Asset.objects.create(
            asset_tag="HIDDEN-2", name="hidden", category=hidden_cat,
            department=other_dep)
        res = self.c.get("/api/common/exports/assets/?format=csv")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("HIDDEN-2", blob)



class UserNotificationPreferenceTests(TestCase):
    """Notification preference API permissions + centralized enforcement."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    # ---------- API: own-only access ----------

    def test_employee_creates_own_preference_record(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True,
                           "categories": {"ticket_assignment": False}},
                          format="json")
        self.assertEqual(res.status_code, 201)
        from common.models import UserNotificationPreference
        self.assertTrue(UserNotificationPreference.objects.filter(
            user=self.emp).exists())

    def test_employee_cannot_read_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o@x", email="o@example.com", employee_id="O1",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.get(
            f"/api/common/notification-preferences/{prefs.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_update_others_preferences(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o2@x", email="o2@example.com", employee_id="O2",
            password="pw12345678")
        prefs = UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.patch(
            f"/api/common/notification-preferences/{prefs.pk}/",
            {"email_enabled": True}, format="json")
        self.assertEqual(res.status_code, 404)
        prefs.refresh_from_db()
        self.assertFalse(prefs.email_enabled)

    def test_it_staff_can_view_all_preferences_for_auditing(self):
        from common.models import UserNotificationPreference
        other = User.objects.create_user(
            username="o3@x", email="o3@example.com", employee_id="O3",
            password="pw12345678")
        UserNotificationPreference.objects.create(
            user=other, email_enabled=False, categories={})
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True, categories={})
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/notification-preferences/")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 2)

    def test_invalid_category_value_rejected(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True, "categories": {"bogus": True}},
                          format="json")
        self.assertEqual(res.status_code, 400)

    # ---------- Enforcement: enabled / disabled / missing / category ----------

    def _create_ticket(self, requester=None, assignee=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep,
            assignee=assignee)

    def test_missing_preference_record_defaults_to_enabled(self):
        # No UserNotificationPreference row exists for emp -> default opt-in.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_global_master_switch_off_suppresses_ticket_emails(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail goes to the requester (master on); the opted-out
        # assignee (emp) receives nothing.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])

    def test_category_opt_out_only_affects_that_category(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=True,
            categories={"ticket_status_change": False})
        # emp creates a ticket -> creation email (master switch) flows.
        auth(self.c, self.emp)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)  # creation to emp (master) flows
        t = Ticket.objects.get(title="t")
        # Status change -> requester (emp) opted out of ticket_status_change
        # -> suppressed, while creation (master) still delivered.
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.patch(f"/api/tickets/{t.pk}/",
                               {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)  # no status email

        # The opt-out did not block the unrelated ticket_assignment category:
        # a staff-created ticket assigned to emp still delivers the assignee.
        before = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t2", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), before + 2)  # creation + assignment

    def test_essential_security_emails_not_suppressed(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        mail.outbox.clear()
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_in_app_notification_independent_of_email_preferences(self):
        from common.models import UserNotificationPreference
        UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})
        auth(self.c, self.mgr)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.c.post("/api/tickets/",
                              {"title": "t", "description": "d",
                               "category": self.tcat.pk,
                               "department": self.dep.pk,
                               "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        # Creation mail to the requester (staff) still goes out; the opted-out
        # assignee (emp) is email-suppressed ...
        self.assertEqual(len(mail.outbox), 1)
        # ... but the in-app notification for the assignee is unaffected.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp).exists())


@override_settings(**LOC)
class TicketNotificationTransactionTests(TestCase):
    """Regression coverage for accounts.email_utils._notify_user.

    The in-app notification must be created only after the surrounding
    transaction commits, so a rolled-back ticket creation or state change
    never leaves an orphaned notification pointing at a non-existent or
    reverted record.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket",
            description="existing",
            category=self.tcat,
            priority="medium",
            status="open",
            requester=self.emp,
            department=self.dep)

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    def test_notify_user_created_after_commit(self):
        # Inside TestCase's atomic block: deferred, not yet visible.
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        # Simulate the commit: execute the captured callback.
        callbacks[0]()
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")

    def test_notify_user_rolled_back_with_transaction(self):
        try:
            with transaction.atomic():
                self._notify()
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_outside_transaction(self):
        self.assertEqual(Notification.objects.count(), 0)
        # Deferred via on_commit; not visible until commit (simulated below).
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        callbacks[0]()
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.object_id, str(self.ticket.pk))

    def test_notify_user_returns_none(self):
        self.assertIsNone(self._notify())

    def test_notify_user_skips_invalid_recipients(self):
        from accounts.email_utils import _notify_user
        _notify_user(None, self.emp, "t", "b", self.ticket)
        _notify_user(self.mgr, None, "t", "b", self.ticket)
        self.assertEqual(Notification.objects.count(), 0)


@override_settings(**LOC)
class TicketNotificationTransactionRealTests(TransactionTestCase):
    """Real database commit/rollback verification for _notify_user.

    Uses TransactionTestCase (not TestCase) so that actual transaction
    boundaries are exercised: on_commit() callbacks fire on real commit,
    and rolled-back transactions never create notifications.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket", description="existing",
            category=self.tcat, priority="medium", status="open",
            requester=self.emp, department=self.dep)

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    # ----- A. Successful commit -----

    def test_commit_creates_notification(self):
        with transaction.atomic():
            self._notify()
            self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")

    # ----- B. Full rollback -----

    def test_rollback_leaves_no_notification(self):
        try:
            with transaction.atomic():
                self._notify()
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    # ----- C. Nested atomic / savepoint rollback -----

    def test_nested_savepoint_rollback(self):
        # Django's transaction.on_commit() callbacks are scoped to the
        # full transaction, not to savepoints. A savepoint rollback does
        # NOT discard callbacks registered after the savepoint; they still
        # fire when the outer transaction commits. This is a known
        # limitation of on_commit(): savepoint-level rollbacks cannot
        # un-register already-registered commit callbacks.
        with transaction.atomic():
            self._notify()
            sp = transaction.savepoint()
            # Distinct notification so dedupe does not collapse the
            # savepoint-level callback proof.
            from accounts.email_utils import _notify_user
            _notify_user(
                self.mgr, self.emp,
                "Ticket status changed again",
                f"Ticket {self.ticket.pk} moved again.",
                self.ticket,
            )
            transaction.savepoint_rollback(sp)
        # Both callbacks fire on outer commit (savepoint rollback does not
        # discard on_commit callbacks). Only a full transaction rollback
        # discards them (see test_rollback_leaves_no_notification).
        self.assertEqual(Notification.objects.count(), 2)

    # ----- D. Notification outside an atomic block -----

    def test_outside_transaction(self):
        self.assertEqual(Notification.objects.count(), 0)
        self._notify()
        # Without an active transaction, on_commit fires immediately.
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.object_id, str(self.ticket.pk))

    # ----- E. Multiple notifications in one transaction -----

    def test_multiple_notifications_one_transaction(self):
        with transaction.atomic():
            self._notify()
            # Second distinct notification for a different recipient.
            from accounts.email_utils import _notify_user as nu2
            nu2(self.emp, self.mgr, "Ticket reassigned",
                f"Ticket {self.ticket.pk} moved queues.", self.ticket)
            self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 2)
        titles = set(Notification.objects.values_list("title", flat=True))
        self.assertIn("Ticket status changed", titles)
        self.assertIn("Ticket reassigned", titles)

    # ----- F. Callback failure after commit -----

    def test_callback_failure_after_commit(self):
        from accounts.email_utils import _notify_user
        from unittest.mock import patch

        with patch("accounts.email_utils.Notification.objects.create",
                   side_effect=RuntimeError("callback boom")):
            try:
                with transaction.atomic():
                    _notify_user(
                        self.mgr, self.emp, "Ticket status changed",
                        f"Ticket {self.ticket.pk} moved.", self.ticket)
            except RuntimeError:
                pass
        # The business transaction committed; the callback failure propagated
        # from the atomic block exit but does not undo the commit.
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())


@override_settings(**LOC)
class CommonNotificationsTests(TransactionTestCase):
    """Coverage for common.notifications.notify_user and notify_watchers.

    Verifies in-app notification creation, deduplication, recipient safety,
    and independence from email preferences using real transaction boundaries.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket", description="existing",
            category=self.tcat, priority="medium", status="open",
            requester=self.emp, department=self.dep)

    def _notify_user(self):
        from common.notifications import notify_user
        return notify_user(
            self.mgr, "ticket_assignment",
            "Ticket assigned", f"Ticket {self.ticket.pk} assigned to you",
            entity_type="tickets.Ticket", object_id=str(self.ticket.pk),
            actor=self.emp)

    # ----- Creation and commit -----

    def test_notify_user_creates_after_commit(self):
        from common.models import Notification
        with transaction.atomic():
            self._notify_user()
            self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket assigned")

    def test_notify_user_returns_none_on_commit(self):
        self.assertIsNone(self._notify_user())

    # ----- Deduplication -----

    def test_notify_user_dedup_same_event(self):
        from common.models import Notification
        from common.notifications import notify_user
        self._notify_user()
        # Same notification again -> deduped, no duplicate.
        notify_user(
            self.mgr, "ticket_assignment",
            "Ticket assigned", f"Ticket {self.ticket.pk} assigned to you",
            entity_type="tickets.Ticket", object_id=str(self.ticket.pk),
            actor=self.emp)
        self.assertEqual(Notification.objects.count(), 1)

    def test_notify_user_distinct_events_not_deduped(self):
        from common.models import Notification
        from common.notifications import notify_user
        self._notify_user()
        # Different title -> distinct notification.
        notify_user(
            self.mgr, "ticket_status_change",
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            entity_type="tickets.Ticket", object_id=str(self.ticket.pk),
            actor=self.emp)
        self.assertEqual(Notification.objects.count(), 2)

    # ----- Recipient safety -----

    def test_notify_user_skips_inactive_recipient(self):
        from common.models import Notification
        from common.notifications import notify_user
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "x",
            entity_type="tickets.Ticket", object_id=str(self.ticket.pk),
            actor=self.mgr)
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_skips_deleted_recipient(self):
        from common.models import Notification
        from common.notifications import notify_user
        self.emp.is_deleted = True
        self.emp.save(update_fields=["is_deleted"])
        notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "x",
            entity_type="tickets.Ticket", object_id=str(self.ticket.pk),
            actor=self.mgr)
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_skips_actor(self):
        from common.models import Notification
        from common.notifications import notify_user
        # emp notifying themselves -> skipped.
        notify_user(
            self.emp, "ticket_assignment", "Ticket assigned", "x",
            entity_type="tickets.Ticket", object_id=str(self.ticket.pk),
            actor=self.emp)
        self.assertEqual(Notification.objects.count(), 0)

    # ----- notify_watchers -----

    def test_notify_watchers_notifies_all_watchers(self):
        from common.models import Notification
        from common.notifications import notify_watchers
        from tickets.models import TicketWatcher
        # Add two watchers.
        TicketWatcher.objects.create(
            ticket=self.ticket, user=self.mgr, is_active=True, is_deleted=False)
        TicketWatcher.objects.create(
            ticket=self.ticket, user=self.emp, is_active=True, is_deleted=False)
        with transaction.atomic():
            notify_watchers(
                self.ticket, self.admin, "Ticket updated",
                f"Ticket {self.ticket.pk} was updated.",
                entity_type="tickets.Ticket",
            )
            self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 2)
        recipients = set(
            Notification.objects.values_list("recipient_id", flat=True))
        self.assertIn(self.mgr.pk, recipients)
        self.assertIn(self.emp.pk, recipients)

    def test_notify_watchers_excludes_actor(self):
        from common.models import Notification
        from common.notifications import notify_watchers
        from tickets.models import TicketWatcher
        TicketWatcher.objects.create(
            ticket=self.ticket, user=self.mgr, is_active=True, is_deleted=False)
        TicketWatcher.objects.create(
            ticket=self.ticket, user=self.admin, is_active=True, is_deleted=False)
        with transaction.atomic():
            notify_watchers(
                self.ticket, self.mgr, "Ticket updated",
                f"Ticket {self.ticket.pk} was updated.",
                entity_type="tickets.Ticket",
            )
            self.assertEqual(Notification.objects.count(), 0)
        # admin notified, mgr (actor) excluded.
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.admin)

    # ----- In-app independent of email preferences -----

    def test_notify_user_independent_of_email_preferences(self):
        from common.models import UserNotificationPreference, Notification
        UserNotificationPreference.objects.create(
            user=self.mgr, email_enabled=False, categories={})
        with transaction.atomic():
            self._notify_user()
            self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 1)
        # In-app notification created even though email is fully disabled.
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)

