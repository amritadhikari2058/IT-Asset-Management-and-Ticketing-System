"""Dashboard, department report, and filtered export tests."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory, Disposal, Maintenance
from tickets.models import Ticket, TicketCategory


class ReportApiTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Network")
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(
            asset_tag="A-1", name="ThinkPad", category=self.acat,
            department=self.dep)
        self.ticket = Ticket.objects.create(
            title="VPN down", description="Cannot connect", category=self.tcat,
            requester=self.emp, department=self.dep, priority="high")
        self.ticket.sla_due_at = timezone.now() - timedelta(hours=2)
        self.ticket.save(update_fields=["sla_due_at"])
        self.maintenance = Maintenance.objects.create(
            asset=self.asset, title="Replace fan",
            maintenance_type="corrective",
            scheduled_date=timezone.now() + timedelta(days=1))
        self.disposal = Disposal.objects.create(
            asset=self.asset, disposal_reason="End of life",
            disposal_method="recycled", disposal_value="12.50")

    def test_dashboard_is_staff_only(self):
        auth(self.c, self.emp)
        self.assertEqual(self.c.get("/api/common/dashboard/").status_code, 403)
        auth(self.c, self.mgr)
        self.assertEqual(self.c.get("/api/common/dashboard/").status_code, 200)

    def test_dashboard_counts_and_sla(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/dashboard/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["employees"]["active"], 3)
        self.assertEqual(res.data["assets"]["total"], 1)
        self.assertEqual(res.data["tickets"]["total"], 1)
        self.assertEqual(res.data["tickets"]["open"], 1)
        self.assertEqual(res.data["tickets"]["overdue"], 1)
        self.assertEqual(res.data["tickets"]["sla"]["overdue"], 1)
        self.assertEqual(res.data["maintenance"]["open"], 1)
        self.assertEqual(res.data["disposals"]["pending_approval"], 1)

    def test_dashboard_invalid_or_reversed_dates_are_400(self):
        auth(self.c, self.mgr)
        bad = self.c.get("/api/common/dashboard/?date_from=not-a-date")
        self.assertEqual(bad.status_code, 400)
        today = timezone.localdate().isoformat()
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        reversed_range = self.c.get(
            f"/api/common/dashboard/?date_from={today}&date_to={yesterday}")
        self.assertEqual(reversed_range.status_code, 400)

    def test_dashboard_date_filter_is_inclusive(self):
        auth(self.c, self.mgr)
        today = timezone.localdate().isoformat()
        res = self.c.get(
            f"/api/common/dashboard/?date_from={today}&date_to={today}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["tickets"]["total"], 1)

    def test_department_report_totals(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/reports/departments/")
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.data["results"] if r["id"] == self.dep.pk)
        self.assertEqual(row["employees_total"], 3)
        self.assertEqual(row["assets_total"], 1)
        self.assertEqual(row["tickets_total"], 1)
        self.assertEqual(row["tickets_open"], 1)
        self.assertEqual(row["sla_overdue"], 1)

    def test_department_report_is_staff_only(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/reports/departments/")
        self.assertEqual(res.status_code, 403)

    def test_department_export_honors_filters(self):
        auth(self.c, self.mgr)
        today = timezone.localdate().isoformat()
        res = self.c.get(
            "/api/common/exports/department_report/"
            f"?format=csv&scope=filtered&date_from={today}&date_to={today}")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8")
        self.assertIn("Eng", body)
        self.assertIn("1", body)

    def test_employee_cannot_export_operational_datasets(self):
        auth(self.c, self.emp)
        res = self.c.get(
            "/api/common/exports/maintenance/?format=csv&scope=all")
        self.assertEqual(res.status_code, 403)
