from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, User
from changes.models import ChangeApproval, ChangeHistory, ChangeRequest
from changes.services import approve_change, complete_implementation, reject_change
from rest_framework.exceptions import ValidationError


def make_user(prefix, role, dep):
    return User.objects.create_user(
        username=f"{prefix}@x", email=f"{prefix}@x", employee_id=prefix.upper(),
        password="pw12345678", role=role, home_department=dep,
    )


class ChangeStateIntegrityTests(TestCase):
    def setUp(self):
        self.dep = Department.objects.create(name="Eng", code="ENGX")
        self.requester = make_user("req", "employee", self.dep)
        self.approver = make_user("apr", "it_manager", self.dep)
        self.change = ChangeRequest.objects.create(
            title="Test change", description="desc",
            change_type="normal", category="infrastructure",
            status="pending_approval", priority="normal",
            requester=self.requester, change_owner=self.requester,
            planned_start=timezone.now(), planned_end=timezone.now() + timezone.timedelta(hours=1),
            rollback_plan="rollback",
        )
        self.approval = ChangeApproval.objects.create(
            change=self.change, approval_level="manager", status="pending",
            requester=self.requester, change_version=self.change.version,
        )

    def test_approve_change_rolls_back_on_audit_failure(self):
        before_status = self.change.status
        before_approved_at = self.change.approved_at
        with mock.patch("changes.services.log_action", side_effect=RuntimeError("audit boom")):
            with self.assertRaises(RuntimeError):
                approve_change(self.change, self.approver, decision_reason="ok", approval=self.approval)
        self.change.refresh_from_db()
        self.approval.refresh_from_db()
        self.assertEqual(self.change.status, before_status)
        self.assertEqual(self.change.approved_at, before_approved_at)
        self.assertEqual(self.approval.status, "pending")
        self.assertEqual(ChangeHistory.objects.filter(change=self.change, event_type="approved").count(), 0)

    def test_reject_change_rolls_back_on_audit_failure(self):
        before_status = self.change.status
        with mock.patch("changes.services.log_action", side_effect=RuntimeError("audit boom")):
            with self.assertRaises(RuntimeError):
                reject_change(self.change, self.approver, decision_reason="no", approval=self.approval)
        self.change.refresh_from_db()
        self.approval.refresh_from_db()
        self.assertEqual(self.change.status, before_status)
        self.assertEqual(self.approval.status, "pending")
        self.assertEqual(ChangeHistory.objects.filter(change=self.change, event_type="rejected").count(), 0)

    def test_complete_implementation_rolls_back_on_audit_failure(self):
        self.change.status = "in_progress"
        self.change.save(update_fields=["status"])
        before_status = self.change.status
        before_end = self.change.actual_end
        with mock.patch("changes.services.log_action", side_effect=RuntimeError("audit boom")):
            with self.assertRaises(RuntimeError):
                complete_implementation(self.change, self.approver, validation_passed=True, notes="done")
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, before_status)
        self.assertEqual(self.change.actual_end, before_end)
        self.assertEqual(ChangeHistory.objects.filter(change=self.change, event_type="completed").count(), 0)
