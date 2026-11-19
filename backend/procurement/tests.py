"""API tests for the procurement workflow.

These cover the contract the frontend relies on: purchase request
submission/approval, quotation selection, PO generation, and goods receipt
booking (partial, complete and over-receipt rejection).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Vendor

from .models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseQuotation,
    PurchaseRequest,
    PurchaseRequestItem,
    ProcurementSetting,
)


def make_user(email, role, employee_id):
    return User.objects.create_user(
        username=employee_id,
        email=email,
        password="test-pass-123",
        role=role,
        employee_id=employee_id,
    )


class ProcurementAPITestCase(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="IT", code="IT")
        self.vendor = Vendor.objects.create(name="Acme Supplies", code="ACME")
        self.admin = make_user("admin@example.test", "system_admin", "T-ADM")
        self.manager = make_user("manager@example.test", "it_manager", "T-MGR")
        self.support = make_user("support@example.test", "it_support", "T-SUP")
        self.employee = make_user("employee@example.test", "employee", "T-EMP")
        self.support.home_department = self.department
        self.support.save(update_fields=["home_department"])
        ProcurementSetting.objects.update_or_create(
            pk=1, defaults={"approval_threshold": Decimal("1000.00")},
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def make_request(self, total="500.00", user=None):
        client = self.client_for(user or self.support)
        resp = client.post(
            "/api/procurement/purchase-requests/",
            {"reason": "Need laptops for new hires", "notes": "urgent",
             "estimated_total": total},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        pr_id = resp.data["id"]
        item = client.post(
            "/api/procurement/purchase-request-items/",
            {
                "purchase_request": pr_id,
                "item_name": "Laptop",
                "quantity": 2,
                "estimated_unit_price": "250.00",
                "estimated_total": total,
            },
            format="json",
        )
        self.assertEqual(item.status_code, 201, item.data)
        return PurchaseRequest.objects.get(pk=pr_id)

    # ---- purchase request lifecycle ----

    def test_requester_submits_and_manager_approves(self):
        pr = self.make_request()
        resp = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "pending_approval")
        self.assertFalse(resp.data["requires_system_admin_approval"])

        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/",
            {"reason": "approved"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "approved")
        self.assertEqual(resp.data["approver"], self.manager.pk)

    def test_requester_cannot_approve_own_request(self):
        pr = self.make_request(user=self.manager)
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "pending_approval")

    def test_it_support_cannot_approve(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/",
            {}, format="json",
        )
        resp = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "pending_approval")

    def test_high_value_request_requires_system_admin(self):
        pr = self.make_request(total="5000.00")
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        pr.refresh_from_db()
        self.assertTrue(pr.requires_system_admin_approval)

        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

        resp = self.client_for(self.admin).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "approved")

    def test_submit_twice_is_rejected(self):
        pr = self.make_request()
        client = self.client_for(self.support)
        client.post(f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json")
        resp = client.post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # ---- quotations ----

    def test_quotation_create_and_select(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        quote = self.client_for(self.manager).post(
            "/api/procurement/quotations/",
            {
                "purchase_request": pr.pk,
                "vendor": self.vendor.pk,
                "quoted_amount": "520.00",
                "delivery_days": 5,
                "warranty": "1 year",
            },
            format="json",
        )
        self.assertEqual(quote.status_code, 201, quote.data)

        self.assertEqual(
            self.client_for(self.support).post(
                f"/api/procurement/quotations/{quote.data['id']}/select/",
                {"reason": "best"}, format="json",
            ).status_code,
            403,
        )
        selected = self.client_for(self.manager).post(
            f"/api/procurement/quotations/{quote.data['id']}/select/",
            {"reason": "best value"}, format="json",
        )
        self.assertEqual(selected.status_code, 200, selected.data)
        self.assertTrue(selected.data["is_selected"])
        self.assertEqual(selected.data["selected_by"], self.manager.pk)

    # ---- purchase orders ----

    def _approved_request_with_quote(self):
        pr = self.make_request(total="500.00")
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        quote = PurchaseQuotation.objects.create(
            purchase_request=pr, vendor=self.vendor,
            quoted_amount=Decimal("520.00"), created_by=self.manager,
        )
        quote.is_selected = True
        quote.selected_by = self.manager
        quote.save()
        return pr

    def test_generate_purchase_order_from_selected_quotation(self):
        pr = self._approved_request_with_quote()
        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["vendor"], self.vendor.pk)
        self.assertEqual(resp.data["status"], "pending_approval")
        # Line values roll up so a generated PO never shows a zero total.
        self.assertEqual(Decimal(resp.data["subtotal"]), Decimal("500.00"))
        self.assertEqual(Decimal(resp.data["total"]), Decimal("500.00"))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "po_generated")

    def test_generate_purchase_order_requires_selected_quotation(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_purchase_order_approve_then_issue(self):
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        po = PurchaseOrder.objects.get(pk=po_data["id"])

        # Creator cannot approve their own PO.
        self.assertEqual(
            self.client_for(self.manager).post(
                f"/api/procurement/purchase-orders/{po.pk}/approve/", {}, format="json",
            ).status_code,
            400,
        )
        approved = self.client_for(self.admin).post(
            f"/api/procurement/purchase-orders/{po.pk}/approve/",
            {"reason": "ok"}, format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")

        sent = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/send_to_vendor/",
            {}, format="json",
        )
        self.assertEqual(sent.status_code, 200, sent.data)
        self.assertEqual(sent.data["status"], "sent_to_vendor")

    # ---- goods receipts ----

    def _issued_po(self):
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        po = PurchaseOrder.objects.get(pk=po_data["id"])
        self.client_for(self.admin).post(
            f"/api/procurement/purchase-orders/{po.pk}/approve/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/send_to_vendor/", {}, format="json",
        )
        po.refresh_from_db()
        return po

    def test_partial_receipt_then_complete_receipt(self):
        po = self._issued_po()
        line = po.items.first()
        self.assertEqual(line.quantity, 2)

        gr = self.client_for(self.support).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk, "delivery_note_number": "DN-1"},
            format="json",
        )
        self.assertEqual(gr.status_code, 201, gr.data)
        receipt = GoodsReceipt.objects.get(pk=gr.data["id"])

        first = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 1,
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 1)
        self.assertEqual(po.status, "partially_received")

        second = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 1,
            },
            format="json",
        )
        self.assertEqual(second.status_code, 201, second.data)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 2)
        self.assertEqual(po.status, "received")

    def test_rejected_and_damaged_units_do_not_count_as_accepted(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 2,
                "quantity_rejected": 1,
                "quantity_damaged": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 0)
        self.assertEqual(line.rejected_qty, 1)
        self.assertEqual(line.damaged_qty, 1)
        self.assertEqual(po.status, "received")

    def test_over_receipt_is_rejected(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 5,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity_received", resp.data)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, 0)

    def test_rejected_plus_damaged_cannot_exceed_received(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 1,
                "quantity_rejected": 2,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_receipt_line_must_match_receipt_purchase_order(self):
        po = self._issued_po()
        other_pr = self._approved_request_with_quote()
        other_po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{other_pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        other_line = PurchaseOrderItem.objects.filter(
            purchase_order_id=other_po_data["id"]).first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": other_line.pk,
                "quantity_received": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # ---- visibility ----

    def test_it_support_only_sees_own_purchase_requests(self):
        own = self.make_request()
        other_user = make_user("other-support@example.test", "it_support", "T-SUP2")
        other = self.make_request(user=other_user)
        resp = self.client_for(self.support).get("/api/procurement/purchase-requests/")
        self.assertEqual(resp.status_code, 200)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_receipt_rejected_for_pending_approval_order(self):
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        po = PurchaseOrder.objects.get(pk=po_data["id"])
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_employee_denied_procurement_access(self):
        resp = self.client_for(self.employee).get("/api/procurement/purchase-requests/")
        self.assertEqual(resp.status_code, 403)

    def test_procurement_history_is_written(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        detail = self.client_for(self.manager).get(
            f"/api/procurement/purchase-requests/{pr.pk}/").data
        actions = [row["action"] for row in detail["history"]]
        self.assertEqual(actions[:3], ["created", "submitted", "approved"])
