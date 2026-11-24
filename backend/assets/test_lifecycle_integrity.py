"""Regression tests for asset lifecycle integrity and safe deletion (Phase 55)."""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from assets.models import (
    Asset, AssetCategory, Assignment, Disposal, Maintenance,
)
from common.models import AuditLog


class AssetHardDeleteIntegrityTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = AssetCategory.objects.create(name="Laptop")

    def _make_asset(self, tag="A1", **kw):
        defaults = dict(asset_tag=tag, name=f"Asset {tag}", category=self.cat)
        defaults.update(kw)
        return Asset.objects.create(**defaults)

    def test_hard_delete_success_no_references(self):
        auth(self.c, self.admin)
        asset = self._make_asset("DEL-OK")
        pk = asset.pk
        res = self.c.post(f"/api/assets/{pk}/hard_delete/", {"confirm": str(pk)}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data.get("permanently_deleted"))
        self.assertFalse(Asset.all_objects.filter(pk=pk).exists())
        self.assertTrue(AuditLog.objects.filter(
            action="hard_delete", entity_type="assets.Asset", object_id=str(pk)).exists())

    def test_hard_delete_requires_confirmation(self):
        auth(self.c, self.admin)
        asset = self._make_asset("DEL-CONF")
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": "wrong"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_hard_delete_unauthorized_for_non_admin(self):
        auth(self.c, self.mgr)
        asset = self._make_asset("DEL-AUTH")
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_hard_delete_blocked_by_maintenance_protect(self):
        """Maintenance.asset is PROTECT; hard delete must return 409, not 500."""
        auth(self.c, self.admin)
        asset = self._make_asset("DEL-MAINT")
        Maintenance.objects.create(
            asset=asset, title="Fix", maintenance_type="preventive",
            status="scheduled", scheduled_date=timezone.now(),
        )
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 409, res.data)
        self.assertIn("references", res.data)
        self.assertGreater(res.data["references"].get("maintenance", 0), 0)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_hard_delete_blocked_by_disposal_protect(self):
        """Disposal.asset is PROTECT; hard delete must return 409, not 500."""
        auth(self.c, self.admin)
        asset = self._make_asset("DEL-DISP")
        Disposal.objects.create(
            asset=asset,
            disposal_reason="old",
            disposal_method="recycle",
            approval_status="pending",
        )
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 409, res.data)
        self.assertGreater(res.data["references"].get("disposals", 0), 0)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_hard_delete_blocked_by_assignment_history(self):
        auth(self.c, self.admin)
        asset = self._make_asset("DEL-ASN")
        Assignment.objects.create(asset=asset, assigned_to=self.emp, assigned_by=self.admin)
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 409, res.data)
        self.assertGreater(res.data["references"].get("assignments", 0), 0)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_hard_delete_blocked_by_ticket_reference(self):
        """View treats ticket references as blocking history; Ticket.asset is SET_NULL in DB."""
        from tickets.models import Ticket, TicketCategory
        auth(self.c, self.admin)
        asset = self._make_asset("DEL-TKT")
        tc = TicketCategory.objects.create(name="HW")
        Ticket.objects.create(
            title="t", description="d", requester=self.emp, category=tc, asset=asset,
        )
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 409, res.data)
        self.assertGreater(res.data["references"].get("tickets", 0), 0)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

class AssetPermissionDispatchTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = AssetCategory.objects.create(name="Laptop")

    def _asset(self, tag="P1"):
        return Asset.objects.create(asset_tag=tag, name=f"Asset {tag}", category=self.cat)

    def test_hard_delete_respects_action_level_system_admin_permission(self):
        asset = self._asset("PD1")
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_hard_delete_allows_system_admin(self):
        asset = self._asset("PD2")
        auth(self.c, self.admin)
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def test_employee_cannot_hard_delete(self):
        asset = self._asset("PD3")
        auth(self.c, self.emp)
        res = self.c.post(f"/api/assets/{asset.pk}/hard_delete/", {"confirm": str(asset.pk)}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Asset.all_objects.filter(pk=asset.pk).exists())

    def test_employee_can_list_assets(self):
        self._asset("PD4")
        auth(self.c, self.emp)
        res = self.c.get("/api/assets/")
        self.assertEqual(res.status_code, 200)

    def test_anonymous_cannot_list_assets(self):
        res = self.c.get("/api/assets/")
        self.assertIn(res.status_code, (401, 403))

class AssetAssignmentIntegrityTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        from accounts.models import User
        self.emp2 = User.objects.create_user(
            username="E2", email="e2@x", password="pw12345678",
            role="employee", employee_id="E2", home_department=self.dep)
        self.c = APIClient()
        self.cat = AssetCategory.objects.create(name="Laptop")

    def _asset(self, tag="A1", **kw):
        defaults = dict(asset_tag=tag, name=f"Asset {tag}", category=self.cat)
        defaults.update(kw)
        return Asset.objects.create(**defaults)

    def test_assign_available_asset_creates_open_assignment(self):
        auth(self.c, self.mgr)
        a = self._asset("AS1")
        res = self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp.pk, "note": "n"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        a.refresh_from_db()
        self.assertEqual(a.status, "assigned")
        self.assertEqual(a.assigned_to_id, self.emp.pk)
        self.assertEqual(Assignment.objects.filter(asset=a, returned_at__isnull=True).count(), 1)

    def test_reassign_to_different_employee_rejected(self):
        auth(self.c, self.mgr)
        a = self._asset("AS2")
        r1 = self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        r2 = self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp2.pk}, format="json")
        self.assertEqual(r2.status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.assigned_to_id, self.emp.pk)
        self.assertEqual(Assignment.objects.filter(asset=a, returned_at__isnull=True).count(), 1)

    def test_same_holder_reassign_rejected(self):
        auth(self.c, self.mgr)
        a = self._asset("AS3")
        self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
        res = self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Assignment.objects.filter(asset=a, returned_at__isnull=True).count(), 1)

    def test_return_asset_closes_open_assignment(self):
        auth(self.c, self.mgr)
        a = self._asset("AS4")
        self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
        res = self.c.post(f"/api/assets/{a.pk}/return_asset/", {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        a.refresh_from_db()
        self.assertEqual(a.status, "available")
        self.assertIsNone(a.assigned_to_id)
        self.assertEqual(Assignment.objects.filter(asset=a, returned_at__isnull=True).count(), 0)
        self.assertEqual(Assignment.objects.filter(asset=a, returned_at__isnull=False).count(), 1)

    def test_assign_retired_asset_rejected(self):
        auth(self.c, self.mgr)
        a = self._asset("AS5", status="retired")
        res = self.c.post(f"/api/assets/{a.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.status, "retired")
        self.assertEqual(Assignment.objects.filter(asset=a).count(), 0)
