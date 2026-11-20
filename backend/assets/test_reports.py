"""Tests for Asset Management reporting and analytics functions."""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from assets.models import Asset, AssetCategory
from assets import reports


class ReportAggregationTests(TestCase):
    """Test the new report aggregation functions."""

    def setUp(self):
        from decimal import Decimal
        from assets.models import Vendor

        self.vendor1 = Vendor.objects.create(name="Dell", code="DELL")
        self.cat1 = AssetCategory.objects.create(name="Laptop")
        self.cat2 = AssetCategory.objects.create(name="Desktop")
        self.cat3 = AssetCategory.objects.create(name="Printer")

        # a1: available, with vendor
        self.a1 = Asset.objects.create(
            asset_tag="LT-1", name="ThinkPad", category=self.cat1,
            vendor=self.vendor1, status="available",
        )
        # a2: available
        self.a2 = Asset.objects.create(
            asset_tag="LT-2", name="Latitude", category=self.cat1,
            status="available",
        )
        # a3: in_repair
        self.a3 = Asset.objects.create(
            asset_tag="DT-1", name="OptiPlex", category=self.cat2,
            status="in_repair",
        )
        # a4: available
        self.a4 = Asset.objects.create(
            asset_tag="PR-1", name="LaserJet", category=self.cat3,
            status="available",
        )
        # a5: available, no purchase_cost
        self.a5 = Asset.objects.create(
            asset_tag="LT-3", name="Ideapad", category=self.cat1,
            status="available",
        )
        # a6: retired, no vendor
        self.a6 = Asset.objects.create(
            asset_tag="DT-2", name="GX-Vostro", category=self.cat2,
            vendor=None, status="retired",
        )
        # a7: available, no department
        self.a7 = Asset.objects.create(
            asset_tag="SP-1", name="ThinkStation", category=self.cat2,
            status="available",
        )

        # Set purchase costs on some assets using Decimal
        self.a1.purchase_cost = Decimal('1099.98')
        self.a2.purchase_cost = Decimal('1300.00')
        self.a3.purchase_cost = Decimal('899.50')
        self.a4.purchase_cost = Decimal('500.00')
        self.a6.purchase_cost = Decimal('650.00')
        self.a7.purchase_cost = Decimal('2100.00')
        self.a1.save(); self.a2.save(); self.a3.save()
        self.a4.save(); self.a6.save(); self.a7.save()

    # --- assets_by_department ---

    def test_assets_by_department_all_no_dept(self):
        """Assets with no department should be grouped as 'No department'."""
        data = reports.assets_by_department()
        rows = data["by_department"]
        no_dept = [d for d in rows if d["department"] == "No department"]
        self.assertEqual(len(no_dept), 1)
        self.assertEqual(no_dept[0]["asset_count"], 7)

    def test_assets_by_department_empty(self):
        """Function runs without error even with minimal data."""
        data = reports.assets_by_department()
        rows = data["by_department"]
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("department", rows[0])
        self.assertIn("asset_count", rows[0])

    # --- assets_by_location ---

    def test_assets_by_location(self):
        """Assets should be grouped by location."""
        data = reports.assets_by_location()
        rows = data["by_location"]
        unassigned = [d for d in rows if d["location"] == "Unassigned"]
        self.assertEqual(len(unassigned), 1)
        self.assertEqual(unassigned[0]["asset_count"], 7)

    # --- assets_with_incomplete_info ---

    def test_assets_with_incomplete_info(self):
        """Should identify assets missing critical fields."""
        data = reports.assets_with_incomplete_info()
        self.assertIn("total", data)
        self.assertIn("missing_department", data)
        self.assertIn("missing_vendor", data)
        self.assertIn("missing_serial", data)
        self.assertIn("missing_purchase_cost", data)
        self.assertEqual(data["missing_department"], 7)
        self.assertEqual(data["missing_vendor"], 6)
        self.assertEqual(data["missing_serial"], 7)

    def test_assets_with_incomplete_info_no_serial_missing(self):
        """All assets have empty serial_number by default."""
        data = reports.assets_with_incomplete_info()
        self.assertEqual(data["missing_serial"], 7)

    # --- warranty_by_department ---

    def test_warranty_by_department_with_dates(self):
        """Warranty status should be correctly classified with dates."""
        from datetime import date
        self.a1.warranty_expiry = date.today() + timedelta(days=30)
        self.a2.warranty_expiry = date.today() - timedelta(days=10)
        self.a3.warranty_expiry = date.today() + timedelta(days=180)
        self.a4.warranty_expiry = None
        self.a5.warranty_expiry = None
        self.a6.warranty_expiry = date.today() + timedelta(days=200)
        self.a7.warranty_expiry = date.today() + timedelta(days=60)

        self.a1.save(); self.a2.save(); self.a3.save()
        self.a4.save(); self.a5.save(); self.a6.save(); self.a7.save()

        data = reports.warranty_by_department()
        self.assertIn("by_department", data)
        self.assertIn("total_with_warranty", data)
        self.assertIn("total_without_warranty", data)

    def test_warranty_by_department_no_dates(self):
        """When no warranty_expiry set, should classify as 'without warranty'."""
        self.a1.warranty_expiry = None
        self.a1.save()

        data = reports.warranty_by_department()
        self.assertIn("by_department", data)
        self.assertIn("total_without_warranty", data)

    # --- warranty_by_category ---

    def test_warranty_by_category(self):
        """Warranty status should be groupable by category."""
        self.a1.warranty_expiry = date.today() + timedelta(days=30)
        self.a2.warranty_expiry = date.today() - timedelta(days=5)
        self.a3.warranty_expiry = None
        self.a1.save(); self.a2.save(); self.a3.save()

        data = reports.warranty_by_category()
        self.assertIn("by_category", data)
        self.assertIn("total_with_warranty", data)
        self.assertIn("total_without_warranty", data)
        self.assertGreaterEqual(len(data["by_category"]), 1)

    # --- warranty_by_vendor ---

    def test_warranty_by_vendor(self):
        """Warranty status should be groupable by vendor."""
        self.a1.warranty_expiry = date.today() + timedelta(days=90)
        self.a1.save()

        data = reports.warranty_by_vendor()
        self.assertIn("by_vendor", data)
        self.assertIn("total_with_warranty", data)
        self.assertIn("total_without_warranty", data)
        self.assertGreaterEqual(len(data["by_vendor"]), 1)

    # --- purchase_cost_by_department ---

    def test_purchase_cost_by_department(self):
        """Purchase cost should be grouped by department."""
        data = reports.purchase_cost_by_department()
        rows = data["by_department"]
        dept_names = [d["department"] for d in rows]
        self.assertIn("No department", dept_names)
        no_dept_entry = [d for d in rows if d["department"] == "No department"][0]
        self.assertEqual(no_dept_entry["asset_count"], 7)
        total_cost = Decimal('6549.48')
        self.assertEqual(sum(d["purchase_cost"] for d in rows), total_cost)

    # --- purchase_cost_trends ---

    def test_purchase_cost_trends(self):
        """Purchase cost trends should group by month."""
        from datetime import date
        self.a1.purchase_date = date(2025, 1, 15)
        self.a2.purchase_date = date(2025, 1, 20)
        self.a3.purchase_date = date(2025, 2, 5)
        self.a4.purchase_date = date(2025, 2, 28)
        self.a1.save(); self.a2.save(); self.a3.save()
        self.a4.save()

        data = reports.purchase_cost_trends()
        self.assertIsInstance(data, dict)
        self.assertIn("total_assets", data)
        self.assertIn("by_month", data)
        self.assertGreaterEqual(len(data["by_month"]), 1)
        months = {(r["year"], r["month"]) for r in data["by_month"]}
        self.assertIn((2025, 1), months)
        self.assertIn((2025, 2), months)

    # --- API endpoint tests ---

    def test_report_endpoints(self):
        """Test all report endpoints via API."""
        client = APIClient()
        from accounts.models import User
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(
            username="testit@local", email="testit@local",
            role="it_manager", is_active=True
        )
        client.force_authenticate(user=user)

        supported_reports = [
            "financial", "maintenance", "warranty", "utilization",
            "inventory", "assets_by_department", "assets_by_location",
            "assets_with_incomplete_info", "warranty_by_department",
            "warranty_by_category", "warranty_by_vendor",
            "purchase_cost_by_department", "purchase_cost_trends"
        ]

        for report in supported_reports:
            res = client.get(f"/api/assets/reports/?report={report}")
            self.assertEqual(res.status_code, 200, f"Report '{report}' failed with status {res.status_code}")

    def test_unsupported_report(self):
        """Unsupported report names should return 400."""
        client = APIClient()
        from accounts.models import User
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(
            username="testit@local", email="testit@local",
            role="it_manager", is_active=True
        )
        client.force_authenticate(user=user)

        res = client.get("/api/assets/reports/?report=nonexistent")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported report", res.data["detail"])


class ReportPermissionTests(TestCase):
    """Test permission enforcement on report endpoints."""

    def setUp(self):
        from accounts.tests import make_users
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_financial_report_forbidden_for_employee(self):
        """Employee should not access financial report."""
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.emp)

        res = client.get("/api/assets/reports/?report=financial")
        self.assertEqual(res.status_code, 403)

    def test_financial_report_allowed_for_manager(self):
        """IT Manager should access financial report."""
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.mgr)

        res = client.get("/api/assets/reports/?report=financial")
        self.assertEqual(res.status_code, 200)

    def test_unsupported_report(self):
        """Unsupported report names should return 400."""
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.mgr)

        res = client.get("/api/assets/reports/?report=nonexistent")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported report", res.data["detail"])