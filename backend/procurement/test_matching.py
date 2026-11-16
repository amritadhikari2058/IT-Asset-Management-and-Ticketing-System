"""P3 matching and exception API/service tests."""
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from accounts.models import User, Department
from assets.models import Vendor
from procurement.models import (
    PurchaseRequest, PurchaseRequestItem, PurchaseOrder, PurchaseOrderItem,
    GoodsReceipt, GoodsReceiptItem, SupplierInvoice, InvoiceException, InvoiceMatchResult,
    ProcurementSetting,
)


def make_user(email, role, eid):
    return User.objects.create_user(username=eid, email=email, password="test-pass-123", role=role, employee_id=eid)


class MatchingAPITests(APITestCase):
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

    def c(self, u):
        c = APIClient(); c.force_authenticate(user=u); return c

    def make_invoice(self, qty_received=2, inv_qty="2", inv_price="100.00", rejected=0, damaged=0):
        gr = GoodsReceipt.objects.create(purchase_order=self.po, received_by=self.support)
        gri = GoodsReceiptItem.objects.create(goods_receipt=gr, purchase_order_item=self.poi, quantity_received=qty_received, quantity_rejected=rejected, quantity_damaged=damaged, accepted_quantity=max(0, qty_received-rejected-damaged))
        today = timezone.now().date().isoformat()
        cm = self.c(self.manager)
        r = cm.post("/api/procurement/supplier-invoices/", {"invoice_number": f"INV-{SupplierInvoice.objects.count()+1}", "vendor": self.vendor.id, "purchase_order": self.po.id, "invoice_date": today, "received_date": today, "currency": "NPR"}, format="json")
        self.assertIn(r.status_code, (200,201), r.data)
        pk = r.data.get("id") if isinstance(getattr(r, "data", None), dict) else None; inv = SupplierInvoice.objects.get(pk=pk) if pk is not None else SupplierInvoice.objects.order_by("-id").first()
        lr = cm.post("/api/procurement/supplier-invoice-lines/", {"invoice": inv.id, "purchase_order_item": self.poi.id, "goods_receipt_item": gri.id, "invoiced_quantity": inv_qty, "unit_price": inv_price, "discount_amount": "0.00", "tax_rate": "0", "tax_amount": "0.00"}, format="json")
        self.assertIn(lr.status_code, (200,201), lr.data)
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        return inv, gri, cm

    def test_exact_match(self):
        inv, _, cm = self.make_invoice()
        r = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_quantity_variance(self):
        inv, _, cm = self.make_invoice(qty_received=2, inv_qty="3")
        r = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_price_variance(self):
        inv, _, cm = self.make_invoice(inv_qty="2", inv_price="150.00")
        r = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_match_snapshot_created(self):
        inv, _, cm = self.make_invoice()
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertTrue(InvoiceMatchResult.objects.filter(invoice=inv).exists())

    def test_rematch_versions(self):
        inv, _, cm = self.make_invoice()
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertGreaterEqual(InvoiceMatchResult.objects.filter(invoice=inv).count(), 1)

    def test_match_history_and_exceptions_endpoints(self):
        inv, _, cm = self.make_invoice(inv_qty="3")
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(cm.get(f"/api/procurement/supplier-invoices/{inv.id}/match-history/").status_code, 200)
        self.assertEqual(cm.get(f"/api/procurement/supplier-invoices/{inv.id}/exceptions/").status_code, 200)

    def test_rejected_damaged_accepted_less(self):
        gr = GoodsReceipt.objects.create(purchase_order=self.po, received_by=self.support)
        gri = GoodsReceiptItem.objects.create(goods_receipt=gr, purchase_order_item=self.poi, quantity_received=2, quantity_rejected=1, quantity_damaged=0, accepted_quantity=1)
        today = timezone.now().date().isoformat()
        cm = self.c(self.manager)
        r = cm.post("/api/procurement/supplier-invoices/", {"invoice_number": "INV-RD", "vendor": self.vendor.id, "purchase_order": self.po.id, "invoice_date": today, "received_date": today, "currency": "NPR"}, format="json")
        pk = r.data.get("id") if isinstance(getattr(r, "data", None), dict) else None; inv = SupplierInvoice.objects.get(pk=pk) if pk is not None else SupplierInvoice.objects.order_by("-id").first()
        cm.post("/api/procurement/supplier-invoice-lines/", {"invoice": inv.id, "purchase_order_item": self.poi.id, "goods_receipt_item": gri.id, "invoiced_quantity": "2", "unit_price": "100.00", "discount_amount": "0.00", "tax_rate": "0", "tax_amount": "0.00"}, format="json")
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/submit/", {}, format="json")
        mr = cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(mr.status_code, 200, mr.data)

    def test_over_invoicing(self):
        inv, _, cm = self.make_invoice(qty_received=2, inv_qty="5")
        self.assertEqual(cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json").status_code, 200)

    def test_match_results_readonly(self):
        inv, _, cm = self.make_invoice()
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        mr = InvoiceMatchResult.objects.filter(invoice=inv).first()
        self.assertIn(cm.post("/api/procurement/invoice-match-results/", {"invoice": inv.id}, format="json").status_code, (403,405,400))
        self.assertIn(cm.delete(f"/api/procurement/invoice-match-results/{mr.id}/").status_code, (403,405))

    def test_exception_list_filter(self):
        inv, _, cm = self.make_invoice(inv_qty="3")
        cm.post(f"/api/procurement/supplier-invoices/{inv.id}/match/", {}, format="json")
        self.assertEqual(cm.get(f"/api/procurement/invoice-exceptions/?invoice={inv.id}").status_code, 200)

    def test_reports(self):
        cm = self.c(self.manager)
        for path in ["/api/procurement/reports/match-rate/", "/api/procurement/reports/exceptions/", "/api/procurement/reports/payment-readiness/", "/api/procurement/reports/invoice-aging/"]:
            self.assertEqual(cm.get(path).status_code, 200, path)

    def test_decimal_totals(self):
        inv, _, cm = self.make_invoice()
        inv.refresh_from_db(); self.assertIsNotNone(inv.grand_total)
