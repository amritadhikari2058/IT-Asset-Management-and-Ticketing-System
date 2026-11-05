"""Dashboard, department report, and filtered export tests."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from accounts.models import Department, User
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


class DepartmentReportBucketTests(TestCase):
    """Regression coverage for per-department bucket isolation and
    current/previous-period correctness (P2 milestone reconciliation)."""

    def setUp(self):
        self.dep_a, self.admin, self.mgr, self.emp = make_users()
        self.dep_b = Department.objects.create(name="Ops", code="OPSX")
        self.emp_a = User.objects.create_user(
            username="ea@x", email="ea@x", employee_id="EA1",
            password="pw12345678", role="employee",
            home_department=self.dep_a)
        self.emp_b = User.objects.create_user(
            username="eb@x", email="eb@x", employee_id="EB1",
            password="pw12345678", role="employee",
            home_department=self.dep_b)
        # Unassigned records: no department set.
        self.emp_unassigned = User.objects.create_user(
            username="eu@x", email="eu@x", employee_id="EU1",
            password="pw12345678", role="employee")
        self.tcat = TicketCategory.objects.create(name="Network")
        self.acat = AssetCategory.objects.create(name="Laptop")
        # Department A records.
        self.asset_a = Asset.objects.create(
            asset_tag="A-1", name="ThinkPad A", category=self.acat,
            department=self.dep_a)
        self.ticket_a = Ticket.objects.create(
            title="Ticket A", description="d", category=self.tcat,
            requester=self.emp_a, department=self.dep_a, priority="high")
        # Department B records.
        self.asset_b = Asset.objects.create(
            asset_tag="B-1", name="ThinkPad B", category=self.acat,
            department=self.dep_b)
        self.ticket_b = Ticket.objects.create(
            title="Ticket B", description="d", category=self.tcat,
            requester=self.emp_b, department=self.dep_b, priority="low")
        # Unassigned records.
        self.asset_unassigned = Asset.objects.create(
            asset_tag="U-1", name="Unassigned laptop", category=self.acat,
            department=None)
        self.ticket_unassigned = Ticket.objects.create(
            title="Unassigned ticket", description="d", category=self.tcat,
            requester=self.emp_unassigned, department=None, priority="medium")
        self.c = APIClient()
        auth(self.c, self.mgr)

    def _rows(self, res):
        self.assertEqual(res.status_code, 200, res.data)
        return res.data["results"]

    def _bucket(self, rows, dept_id):
        for row in rows:
            if row["id"] == dept_id:
                return row
        return None

    def test_department_a_records_do_not_appear_in_department_b(self):
        rows = self._rows(self.c.get("/api/common/reports/departments/"))
        b = self._bucket(rows, self.dep_b.pk)
        # Department B's own asset + ticket only; Department A's records absent.
        self.assertEqual(b["assets_total"], 1)
        self.assertEqual(b["tickets_total"], 1)
        # Cross-department isolation: every assigned asset/ticket lands in
        # exactly one department bucket; unassigned records are not returned
        # in any department bucket.
        total_assets = sum(r["assets_total"] for r in rows)
        total_tickets = sum(r["tickets_total"] for r in rows)
        self.assertEqual(total_assets, 2)  # A + B only (unassigned excluded)
        self.assertEqual(total_tickets, 2)

    def test_department_b_records_do_not_appear_in_department_a(self):
        rows = self._rows(self.c.get("/api/common/reports/departments/"))
        a = self._bucket(rows, self.dep_a.pk)
        self.assertEqual(a["assets_total"], 1)
        self.assertEqual(a["tickets_total"], 1)

    def test_unassigned_records_do_not_leak_into_department_buckets(self):
        rows = self._rows(self.c.get("/api/common/reports/departments/"))
        for r in rows:
            if r["id"] in (self.dep_a.pk, self.dep_b.pk):
                # Only that department's own asset/ticket, never unassigned.
                self.assertEqual(r["assets_total"], 1)
                self.assertEqual(r["tickets_total"], 1)

    def test_current_period_buckets_are_correct(self):
        today = timezone.localdate().isoformat()
        res = self.c.get(
            f"/api/common/reports/departments/?date_from={today}&date_to={today}")
        rows = self._rows(res)
        a = self._bucket(rows, self.dep_a.pk)
        self.assertEqual(a["tickets_total"], 1)
        self.assertEqual(a["assets_total"], 1)

    def test_previous_period_buckets_are_correct(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        res = self.c.get(
            "/api/common/reports/departments/"
            f"?date_from={today.isoformat()}&date_to={today.isoformat()}"
            f"&date_from_prev={yesterday.isoformat()}"
            f"&date_to_prev={yesterday.isoformat()}")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("results_prev", res.data)
        # No records were created yesterday, so previous-period buckets are empty.
        for row in res.data["results_prev"]:
            self.assertEqual(row["tickets_total"], 0)
            self.assertEqual(row["assets_total"], 0)

    def test_exported_rows_match_api_report_buckets(self):
        today = timezone.localdate().isoformat()
        api = self.c.get(
            f"/api/common/reports/departments/?date_from={today}&date_to={today}")
        self.assertEqual(api.status_code, 200)
        api_rows = {r["id"]: r for r in api.data["results"]}
        res = self.c.get(
            "/api/common/exports/department_report/"
            f"?format=csv&scope=filtered&date_from={today}&date_to={today}")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8")
        # Every API bucket must appear as an exported row with matching totals.
        for row in api_rows.values():
            self.assertIn(row["name"], body)
            self.assertIn(str(row["tickets_total"]), body)
            self.assertIn(str(row["assets_total"]), body)
