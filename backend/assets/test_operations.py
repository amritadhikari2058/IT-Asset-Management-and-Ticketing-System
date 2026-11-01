"""Maintenance and disposal workflow tests (filters, blocking, completion)."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory, Disposal, Maintenance


class MaintenanceApiTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(
            asset_tag="LT-1", name="ThinkPad", category=self.cat,
            department=self.dep)
        self.m = Maintenance.objects.create(
            asset=self.asset, title="Replace fan", maintenance_type="corrective",
            scheduled_date=timezone.now() + timedelta(days=1))
        Maintenance.objects.create(
            asset=self.asset, title="Annual clean", maintenance_type="cleaning",
            status="completed",
            scheduled_date=timezone.now() - timedelta(days=3),
            completion_date=timezone.now() - timedelta(days=2))

    def test_filters_search_type_and_open(self):
        auth(self.c, self.mgr)
        res = self.c.get(
            "/api/assets/maintenance/?q=fan&maintenance_type=corrective"
            "&open=true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["title"], "Replace fan")

    def test_assign_is_blocked_while_maintenance_is_open(self):
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/{self.asset.pk}/assign/",
            {"assigned_to": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("maintenance", res.data["detail"].lower())


class DisposalApiTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(
            asset_tag="LT-2", name="Old ThinkPad", category=self.cat,
            department=self.dep)
        self.d = Disposal.objects.create(
            asset=self.asset, disposal_reason="End of life",
            disposal_method="recycled", disposal_value="12.50")

    def test_filters_search_method_and_completion(self):
        auth(self.c, self.mgr)
        res = self.c.get(
            "/api/assets/disposals/?q=life&disposal_method=recycled"
            "&completed=false")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)
        empty = self.c.get("/api/assets/disposals/?completed=true")
        self.assertEqual(empty.data["count"], 0)

    def test_complete_requires_approval(self):
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/assets/disposals/{self.d.pk}/complete/")
        self.assertEqual(res.status_code, 400)

    def test_complete_disposes_asset_and_records_value(self):
        self.d.approval_status = "approved"
        self.d.approver = self.mgr
        self.d.save()
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/assets/disposals/{self.d.pk}/complete/")
        self.assertEqual(res.status_code, 200)
        self.asset.refresh_from_db()
        self.d.refresh_from_db()
        self.assertEqual(self.asset.status, "disposed")
        self.assertIsNone(self.asset.assigned_to)
        self.assertIsNotNone(self.d.disposal_date)
        self.assertEqual(str(self.d.disposal_value), "12.50")
