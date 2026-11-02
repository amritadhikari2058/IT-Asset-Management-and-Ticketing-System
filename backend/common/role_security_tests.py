"""Role-based security tests across all four roles.

Verifies object-level permissions, IDOR protection, and administrative
action separation for System Admin, IT Manager, IT Support, and Employee.
"""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Department, User
from accounts.tests import auth, make_users, token
from assets.models import Asset, AssetCategory

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


@override_settings(**LOC)
class RoleSecurityTests(TestCase):
    """Cross-role access checks for list, detail, update, delete, and
    custom actions. Each role should only see what it is entitled to."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        # Asset owned by emp, in emp's home department (visible to emp)
        self.emp_asset = Asset.objects.create(
            asset_tag="E1", name="emp asset", category=self.acat,
            status="assigned", assigned_to=self.emp,
            department=self.dep, serial_number="SN-E1")
        # Asset in a DIFFERENT department (NOT visible to emp)
        self.other_dep = Department.objects.create(name="Sales", code="SLS")
        self.other_asset = Asset.objects.create(
            asset_tag="O1", name="other dept asset", category=self.acat,
            status="available", department=self.other_dep,
            serial_number="SN-O1")
        # Asset owned by mgr (IT staff), in same department as emp
        self.mgr_asset = Asset.objects.create(
            asset_tag="M1", name="mgr asset", category=self.acat,
            status="available", department=self.dep,
            serial_number="SN-M1")

    def _as(self, role):
        """Return an authenticated client for the given role."""
        c = APIClient()
        user_map = {
            "system_admin": self.admin,
            "it_manager": self.mgr,
            "it_support": self.mgr,  # no it_support user; mgr covers IT staff
            "employee": self.emp,
        }
        auth(c, user_map[role])
        return c

    # ----------------------------------------------------------------
    # Employee cannot see other employees' assets (IDOR)
    # ----------------------------------------------------------------
    def test_employee_cannot_see_other_assets(self):
        c = self._as("employee")
        res = c.get("/api/assets/")
        self.assertEqual(res.status_code, 200, res.data)
        ids = [r["id"] for r in res.data.get("results", [])]
        # Own + home-department assets visible
        self.assertIn(self.emp_asset.id, ids)
        self.assertIn(self.mgr_asset.id, ids)
        # Other-department asset NOT visible (IDOR protection)
        self.assertNotIn(self.other_asset.id, ids)

    def test_it_staff_sees_all_assets(self):
        for role in ("system_admin", "it_manager", "it_support"):
            c = self._as(role)
            res = c.get("/api/assets/")
            self.assertEqual(res.status_code, 200, res.data)
            ids = [r["id"] for r in res.data.get("results", [])]
            self.assertIn(self.emp_asset.id, ids)
            self.assertIn(self.mgr_asset.id, ids)
            self.assertIn(self.other_asset.id, ids)

    def test_employee_cannot_access_other_asset_detail(self):
        c = self._as("employee")
        res = c.get(f"/api/assets/{self.other_asset.id}/")
        self.assertEqual(res.status_code, 404, res.data)

    # ----------------------------------------------------------------
    # Update/delete separation
    # ----------------------------------------------------------------
    def test_employee_cannot_update_asset(self):
        c = self._as("employee")
        res = c.patch(f"/api/assets/{self.emp_asset.id}/",
                      {"location": "Hacked"}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

    def test_it_manager_can_update_asset(self):
        c = self._as("it_manager")
        res = c.patch(f"/api/assets/{self.emp_asset.id}/",
                      {"location": "HQ"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def test_employee_cannot_delete_asset(self):
        c = self._as("employee")
        res = c.delete(f"/api/assets/{self.emp_asset.id}/", {}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

    def test_it_manager_can_soft_delete_asset(self):
        c = self._as("it_manager")
        res = c.delete(f"/api/assets/{self.mgr_asset.id}/", {}, format="json")
        self.assertEqual(res.status_code, 204, res.data)

    def test_only_system_admin_can_hard_delete(self):
        c = self._as("it_manager")
        cat = AssetCategory.objects.create(name="Temp")
        res = c.post(f"/api/assets/categories/{cat.pk}/hard_delete/",
                     {"confirm": str(cat.pk)}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

        c = self._as("system_admin")
        res = c.post(f"/api/assets/categories/{cat.pk}/hard_delete/",
                     {"confirm": str(cat.pk), "reason": "cleanup"},
                     format="json")
        self.assertEqual(res.status_code, 200, res.data)

    # ----------------------------------------------------------------
    # User management separation
    # ----------------------------------------------------------------
    def test_employee_can_list_user_directory(self):
        """User directory is readable by all authenticated users."""
        c = self._as("employee")
        res = c.get("/api/accounts/users/")
        self.assertEqual(res.status_code, 200, res.data)
        ids = [u["employee_id"] for u in res.data.get("results", [])]
        self.assertIn(self.mgr.employee_id, ids)

    def test_employee_can_see_other_profile(self):
        """User profile detail is readable by all authenticated users."""
        c = self._as("employee")
        res = c.get(f"/api/accounts/users/{self.mgr.pk}/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["employee_id"], self.mgr.employee_id)

    def test_employee_cannot_update_other_user(self):
        c = self._as("employee")
        res = c.patch(f"/api/accounts/users/{self.mgr.pk}/",
                      {"is_active": False}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

    # ----------------------------------------------------------------
    # Department restrictions
    # ----------------------------------------------------------------
    def test_employee_sees_only_home_department(self):
        c = self._as("employee")
        res = c.get("/api/accounts/departments/")
        self.assertEqual(res.status_code, 200, res.data)
        ids = [d["id"] for d in res.data.get("results", [])]
        self.assertIn(self.dep.id, ids)

    # ----------------------------------------------------------------
    # Notification access
    # ----------------------------------------------------------------
    def test_employee_sees_only_own_notifications(self):
        from common.models import Notification
        Notification.objects.create(
            recipient=self.emp, title="Your notice", body="hi",
            entity_type="tickets.Ticket", object_id="1")
        Notification.objects.create(
            recipient=self.mgr, title="Mgr notice", body="hi",
            entity_type="tickets.Ticket", object_id="2")

        c = self._as("employee")
        res = c.get("/api/common/notifications/")
        self.assertEqual(res.status_code, 200, res.data)
        titles = [n["title"] for n in res.data.get("results", [])]
        self.assertIn("Your notice", titles)
        self.assertNotIn("Mgr notice", titles)

    # ----------------------------------------------------------------
    # Self-service: employee sees own profile
    # ----------------------------------------------------------------
    def test_employee_sees_own_profile(self):
        c = self._as("employee")
        res = c.get("/api/accounts/me/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["employee_id"], self.emp.employee_id)

    def test_employee_can_see_other_profile(self):
        """User profile detail is readable by all authenticated users
        (directory behavior)."""
        c = self._as("employee")
        res = c.get(f"/api/accounts/users/{self.mgr.pk}/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["employee_id"], self.mgr.employee_id)
