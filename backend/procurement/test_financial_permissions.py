"""P3 financial permission and dashboard/report access tests."""
from decimal import Decimal
from rest_framework.test import APITestCase, APIClient

from accounts.models import User, Department
from assets.models import Vendor
from procurement.models import PurchaseRequest, PurchaseOrder


def make_user(email, role, eid):
    return User.objects.create_user(username=eid, email=email, password="test-pass-123", role=role, employee_id=eid)


class FinancialPermissionTests(APITestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="IT", code="IT")
        self.vendor = Vendor.objects.create(name="Acme", code="ACME")
        self.admin = make_user("a@t.test", "system_admin", "A1")
        self.manager = make_user("m@t.test", "it_manager", "M1")
        self.support = make_user("s@t.test", "it_support", "S1")
        self.employee = make_user("e@t.test", "employee", "E1")
        self.pr = PurchaseRequest.objects.create(requester=self.support, department=self.dept, reason="need", status="approved")
        self.po = PurchaseOrder.objects.create(purchase_request=self.pr, vendor=self.vendor, created_by=self.manager, status="approved", currency="NPR", total=Decimal("100.00"))

    def c(self, u): c = APIClient(); c.force_authenticate(user=u); return c

    def test_employee_denied_supplier_invoices(self):
        self.assertEqual(self.c(self.employee).get("/api/procurement/supplier-invoices/").status_code, 403)

    def test_employee_denied_financial_dashboard(self):
        self.assertEqual(self.c(self.employee).get("/api/procurement/financial-dashboard/").status_code, 403)

    def test_support_denied_or_limited_financial_dashboard(self):
        r = self.c(self.support).get("/api/procurement/financial-dashboard/")
        self.assertIn(r.status_code, (200,403))

    def test_manager_can_access_financial_dashboard(self):
        self.assertEqual(self.c(self.manager).get("/api/procurement/financial-dashboard/").status_code, 200)

    def test_admin_can_access_financial_dashboard(self):
        self.assertEqual(self.c(self.admin).get("/api/procurement/financial-dashboard/").status_code, 200)

    def test_manager_can_access_reports(self):
        for path in ["/api/procurement/reports/invoice-aging/", "/api/procurement/reports/match-rate/", "/api/procurement/reports/exceptions/", "/api/procurement/reports/vendor-returns/", "/api/procurement/reports/credits/", "/api/procurement/reports/payment-readiness/", "/api/procurement/reports/vendor-performance/"]:
            self.assertEqual(self.c(self.manager).get(path).status_code, 200, path)

    def test_employee_denied_vendor_performance(self):
        self.assertEqual(self.c(self.employee).get("/api/procurement/reports/vendor-performance/").status_code, 403)

    def test_unauthenticated_denied(self):
        self.assertIn(APIClient().get("/api/procurement/supplier-invoices/").status_code, (401,403))

    def test_financial_history_access(self):
        self.assertEqual(self.c(self.manager).get("/api/procurement/financial-history/").status_code, 200)
        self.assertIn(self.c(self.support).get("/api/procurement/financial-history/").status_code, (200,403))

    def test_invoice_exceptions_list(self):
        self.assertEqual(self.c(self.manager).get("/api/procurement/invoice-exceptions/").status_code, 200)

    def test_credit_note_and_return_lists_authz(self):
        self.assertEqual(self.c(self.manager).get("/api/procurement/vendor-returns/").status_code, 200)
        self.assertEqual(self.c(self.manager).get("/api/procurement/credit-notes/").status_code, 200)

    def test_employee_denied_credit_notes(self):
        self.assertEqual(self.c(self.employee).get("/api/procurement/credit-notes/").status_code, 403)
