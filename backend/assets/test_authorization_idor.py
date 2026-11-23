from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users, _make_user
from assets.models import Asset, AssetAttachment, AssetCategory, AssetHistory


class AssetAuthorizationIDORTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.dep2 = Department.objects.create(name="HR", code="HR1")
        self.emp2 = _make_user("E2", "e2@x", "e2@x", "employee", self.dep)
        self.emp_other = _make_user("E3", "e3@x", "e3@x", "employee", self.dep2)
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.asset_emp = Asset.objects.create(
            asset_tag="A-1", name="Laptop 1", category=self.cat,
            department=self.dep, status="assigned", assigned_to=self.emp)
        self.asset_other = Asset.objects.create(
            asset_tag="A-2", name="Laptop 2", category=self.cat,
            department=self.dep2, status="assigned", assigned_to=self.emp_other)
        self.c = APIClient()

    def test_employee_cannot_retrieve_other_employees_asset(self):
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/{self.asset_other.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_modify_asset(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/assets/{self.asset_emp.pk}/",
                           {"name": "hacked"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.asset_emp.refresh_from_db()
        self.assertEqual(self.asset_emp.name, "Laptop 1")

    def test_employee_cannot_assign_asset(self):
        auth(self.c, self.emp)
        res = self.c.post(f"/api/assets/{self.asset_emp.pk}/assign/",
                          {"assigned_to": self.emp2.pk}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_delete_asset(self):
        auth(self.c, self.emp)
        res = self.c.delete(f"/api/assets/{self.asset_emp.pk}/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Asset.objects.filter(pk=self.asset_emp.pk).exists())

    def test_asset_history_idor_for_employee(self):
        AssetHistory.objects.create(asset=self.asset_other, actor=self.admin, action="created")
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/histories/?asset={self.asset_other.pk}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get("count", len(res.data.get("results", res.data))), 0)

    def test_asset_attachment_download_idor(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        att = AssetAttachment.objects.create(
            asset=self.asset_other,
            file=SimpleUploadedFile("s.txt", b"secret", content_type="text/plain"),
            uploaded_by=self.admin, original_filename="s.txt")
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/attachments/{att.pk}/download/")
        self.assertIn(res.status_code, (403, 404))

    def test_asset_attachment_serializer_mass_assignment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        auth(self.c, self.mgr)
        # manager is IT staff, can create attachment on visible asset
        f = SimpleUploadedFile("a.txt", b"hello", content_type="text/plain")
        res = self.c.post("/api/assets/attachments/",
                          {"asset": self.asset_emp.pk, "file": f,
                           "uploaded_by": self.emp_other.pk, "is_deleted": True},
                          format="multipart")
        # create should succeed but ignore uploaded_by/is_deleted
        self.assertIn(res.status_code, (201, 400))
        if res.status_code == 201:
            att = AssetAttachment.objects.get(pk=res.data["id"])
            self.assertEqual(att.uploaded_by_id, self.mgr.pk)
            self.assertFalse(att.is_deleted)

    def test_disabled_user_denied_asset_list(self):
        auth(self.c, self.emp)
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        res = self.c.get("/api/assets/")
        self.assertIn(res.status_code, (401, 403))
