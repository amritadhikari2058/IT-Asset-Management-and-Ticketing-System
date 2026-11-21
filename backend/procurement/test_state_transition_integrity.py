from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Vendor
from common.models import AuditLog

from .models import (
    ProcurementHistory,
    ProcurementSetting,
    PurchaseOrder,
    PurchaseQuotation,
    PurchaseRequest,
    PurchaseRequestItem,
)


def make_user(email, role, employee_id):
    return User.objects.create_user(
        username=employee_id,
        email=email,
        password="test-pass-123",
        role=role,
        employee_id=employee_id,
    )


class ProcurementStateIntegrityTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="IT", code="IT")
        self.vendor = Vendor.objects.create(name="Acme Supplies", code="ACME")
        self.admin = make_user("admin@example.test", "system_admin", "T-ADM")
        self.manager = make_user("manager@example.test", "it_manager", "T-MGR")
        self.support = make_user("support@example.test", "it_support", "T-SUP")
        self.support.home_department = self.department
        self.support.save(update_fields=["home_department"])
        ProcurementSetting.objects.update_or_create(
            pk=1, defaults={"approval_threshold": Decimal("1000.00")},
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def make_request(self, status="draft"):
        pr = PurchaseRequest.objects.create(
            requester=self.support,
            department=self.department,
            reason="Need laptops",
            status=status,
        )
        PurchaseRequestItem.objects.create(
            purchase_request=pr,
            item_name="Laptop",
            quantity=2,
            estimated_unit_price=Decimal("200.00"),
            estimated_total=Decimal("400.00"),
        )
        return pr

    def test_approve_rolls_back_on_audit_failure(self):
        pr = self.make_request(status="pending_approval")
        before = (pr.status, pr.approver_id, pr.approval_decision, pr.version)
        client = self.client_for(self.manager)
        old_raise = client.raise_request_exception
        client.raise_request_exception = False
        try:
            with mock.patch("procurement.views.log_action", side_effect=RuntimeError("audit boom")):
                resp = client.post(
                    f"/api/procurement/purchase-requests/{pr.pk}/approve/",
                    {"reason": "ok"}, format="json",
                )
        finally:
            client.raise_request_exception = old_raise
        self.assertEqual(resp.status_code, 500)
        pr.refresh_from_db()
        self.assertEqual((pr.status, pr.approver_id, pr.approval_decision, pr.version), before)
        self.assertEqual(ProcurementHistory.objects.filter(purchase_request=pr, action="approved").count(), 0)

    def test_reject_rolls_back_on_audit_failure(self):
        pr = self.make_request(status="pending_approval")
        before = (pr.status, pr.approver_id, pr.approval_decision, pr.version)
        client = self.client_for(self.manager)
        old_raise = client.raise_request_exception
        client.raise_request_exception = False
        try:
            with mock.patch("procurement.views.log_action", side_effect=RuntimeError("audit boom")):
                resp = client.post(
                    f"/api/procurement/purchase-requests/{pr.pk}/reject/",
                    {"reason": "no"}, format="json",
                )
        finally:
            client.raise_request_exception = old_raise
        self.assertEqual(resp.status_code, 500)
        pr.refresh_from_db()
        self.assertEqual((pr.status, pr.approver_id, pr.approval_decision, pr.version), before)
        self.assertEqual(ProcurementHistory.objects.filter(purchase_request=pr, action="rejected").count(), 0)

    def test_submit_rolls_back_on_audit_failure(self):
        pr = self.make_request(status="draft")
        before = (pr.status, pr.version)
        client = self.client_for(self.support)
        old_raise = client.raise_request_exception
        client.raise_request_exception = False
        try:
            with mock.patch("procurement.views.log_action", side_effect=RuntimeError("audit boom")):
                resp = client.post(
                    f"/api/procurement/purchase-requests/{pr.pk}/submit/",
                    {}, format="json",
                )
        finally:
            client.raise_request_exception = old_raise
        self.assertEqual(resp.status_code, 500)
        pr.refresh_from_db()
        self.assertEqual((pr.status, pr.version), before)
        self.assertEqual(ProcurementHistory.objects.filter(purchase_request=pr, action="submitted").count(), 0)

    def test_generate_from_pr_rejects_when_po_already_exists(self):
        pr = self.make_request(status="approved")
        PurchaseQuotation.objects.create(
            purchase_request=pr, vendor=self.vendor, quoted_amount=Decimal("400.00"), is_selected=True,
        )
        client = self.client_for(self.manager)
        first = client.post(f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/", {}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        second = client.post(f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/", {}, format="json")
        self.assertEqual(second.status_code, 409, second.data)
        self.assertEqual(PurchaseOrder.objects.filter(purchase_request=pr, is_deleted=False).count(), 1)
