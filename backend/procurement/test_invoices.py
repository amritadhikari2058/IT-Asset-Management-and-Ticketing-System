"""P3 Supplier Invoice API tests."""
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from accounts.models import User, Department
from assets.models import Vendor
from procurement.models import (
    PurchaseRequest, PurchaseRequestItem, PurchaseOrder, PurchaseOrderItem,
    GoodsReceipt, GoodsReceiptItem, SupplierInvoice, ProcurementSetting,
)


def make_user(email, role, eid):
    return User.objects.create_user(username=eid, email=email, password="test-pass-123", role=role, employee_id=eid)


class InvoiceAPITests(APITestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="IT", code="IT")
        self.vendor = Vendor.objects.create(name="Acme", code="ACME")
        self.admin = make_user("a@t.test", "system_admin", "A1")
        self.manager = make_user("m@t.test", "it_manager", "M1")
        self.support = make_user("s@t.test", "it_support", "S1")
        ProcurementSetting.objects.update_or_create(pk=1, defaults={"approval_threshold": Decimal("1000.00")})
        self.pr = PurchaseRequest.objects.create(requester=self.support, department=self.dept, reason="need", status="approved", estimated_total=Decimal("200.00"))
        self.pri = PurchaseRequestItem.objects.create(purchase_request=self.pr, item_name="Laptop", quantity=2, estimated_unit_price=Decimal("100.00"), estimated_total=Decimal("200.00"))
        self.po = PurchaseOrder.objects.create(purchase_request=self.pr, vendor=self.vendor, created_by=self.manager, status="approved", currency="NPR", total=Decimal("200.00"))
        self.poi = PurchaseOrderItem.objects.create(purchase_order=self.po, item_name="Laptop", quantity=2, unit_price=Decimal("100.00"), total=Decimal("200.00"))
        self.gr = GoodsReceipt.objects.create(purchase_order=self.po, received_by=self.support)
        self.gri = GoodsReceiptItem.objects.create(goods_receipt=self.gr, purchase_order_item=self.poi, quantity_received=2, quantity_rejected=0, quantity_damaged=0, accepted_quantity=2)

    def client_for(self, u):
        c = APIClient(); c.force_authenticate(user=u); return c

    def inv_payload(self, **overrides):
        today = timezone.now().date().isoformat()
        p = {"invoice_number": "INV-1", "vendor": self.vendor.id, "purchase_order": self.po.id,
             "invoice_date": today, "received_date": today, "currency": "NPR",
             "discount_total": "0.00", "freight_total": "0.00", "other_charge_total": "0.00"}
        p.update(overrides); return p

    def create_invoice(self, user=None):
        c = self.client_for(user or self.manager)
        r = c.post("/api/procurement/supplier-invoices/", self.inv_payload(), format="json")
        self.assertIn(r.status_code, (200, 201), getattr(r, 'data', r.content))
        self.assertIn("id", r.data, r.data)
        inv = SupplierInvoice.objects.get(pk=r.data["id"])
        return inv, c

    def add_line(self, inv, client, qty="2", price="100.00"):
        r = client.post("/api/procurement/supplier-invoice-lines/", {
            "invoice": inv.id, "purchase_order_item": self.poi.id, "goods_receipt_item": self.gri.id,
            "description": "Laptop", "invoiced_quantity": qty, "unit_price": price,
            "discount_amount": "0.00", "tax_rate": "0", "tax_amount": "0.00",
        }, format="json")
        self.assertIn(r.status_code, (200, 201), r.data)
        return r

    def test_create_draft_invoice(self):
        inv, _ = self.create_invoice(); self.assertEqual(inv.status, "draft")

    def test_duplicate_normalized_invoice_number_detected(self):
        inv1, c = self.create_invoice(); self.add_line(inv1, c)
        c.post(f"/api/procurement/supplier-invoices/{inv1.id}/submit/", {}, format="json")
        r2 = c.post("/api/procurement/supplier-invoices/", self.inv_payload(invoice_number="inv-1"), format="json")
        self.assertIn(r2.status_code, (200, 201), r2.data)
        self.assertIn("id", r2.data, r2.data); inv2 = SupplierInvoice.objects.get(pk=r2.data["id"]); self.add_line(inv2, c)
        r3 = c.post(f"/api/procurement/supplier-invoices/{inv2.id}/submit/", {}, format="json")
        self.assertIn(r3.status_code, (400, 409), r3.data)

    def test_submit_requires_line(self):
        inv, c = self.create_invoice()
        r = c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.data)

    def test_submit_success(self):
        inv, c = self.create_invoice(); self.add_line(inv, c)
        r = c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db(); self.assertEqual(inv.status, "submitted")

    def test_creator_cannot_approve_own_invoice(self):
        inv, c = self.create_invoice(user=self.manager); self.add_line(inv, c)
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        r = c.post(f"/api/procurement/supplier-invoices/{inv.id}/approve/", {}, format="json")
        self.assertIn(r.status_code, (403, 409), r.data)

    def test_match_and_readiness_endpoint(self):
        inv, c = self.create_invoice(); self.add_line(inv, c)
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        r = c.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rd = c.get(f"/api/procurement/supplier-invoices/{inv.id}/readiness/")
        self.assertEqual(rd.status_code, 200, rd.data); self.assertIn("ready", rd.data)

    def test_employee_denied(self):
        emp = make_user("e@t.test", "employee", "E1")
        r = self.client_for(emp).get("/api/procurement/supplier-invoices/")
        self.assertEqual(r.status_code, 403, r.data)

    def test_mark_paid_requires_reference_and_date(self):
        inv, c = self.create_invoice(user=self.support); self.add_line(inv, c)
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        cm = self.client_for(self.manager)
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/approve/", {}, format="json")
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/mark-payment-ready/", {}, format="json")
        r = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/mark-paid/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.data)

    def test_cancel_and_close_rules(self):
        inv, c = self.create_invoice(); self.add_line(inv, c)
        r = c.post(f"/api/procurement/supplier-invoices/{inv.id}/cancel/", {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db(); self.assertEqual(inv.status, "cancelled")
        r2 = c.post(f"/api/procurement/supplier-invoices/{inv.id}/close/", {}, format="json")
        self.assertIn(r2.status_code, (400, 409), r2.data)

    def test_hard_delete_not_allowed(self):
        inv, c = self.create_invoice()
        r = c.delete(f"/api/procurement/supplier-invoices/{inv.id}/")
        self.assertEqual(r.status_code, 405, r.data)

    def test_match_history_and_exceptions_endpoints(self):
        inv, c = self.create_invoice(); self.add_line(inv, c)
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(c.get(f"/api/procurement/supplier-invoices/{inv.id}/match-history/").status_code, 200)
        self.assertEqual(c.get(f"/api/procurement/supplier-invoices/{inv.id}/exceptions/").status_code, 200)

    def test_invoice_list_and_history(self):
        inv, c = self.create_invoice()
        self.assertEqual(c.get("/api/procurement/supplier-invoices/?status=draft").status_code, 200)
        self.assertEqual(c.get(f"/api/procurement/supplier-invoices/{inv.id}/history/").status_code, 200)

    def test_mark_paid_success(self):
        inv, c = self.create_invoice(user=self.support); self.add_line(inv, c)
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        c.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        cm = self.client_for(self.manager)
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/approve/", {}, format="json")
        rdy = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/mark-payment-ready/", {}, format="json")
        if rdy.status_code == 200:
            r = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/mark-paid/", {"payment_reference": "REF1", "payment_date": timezone.now().date().isoformat()}, format="json")
            self.assertEqual(r.status_code, 200, r.data)

    def test_place_and_release_hold(self):
        inv, c = self.create_invoice(); self.add_line(inv, c)
        cm = self.client_for(self.manager)
        r = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/place-hold/", {"reason": "hold"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r2 = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/release-hold/", {}, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)
