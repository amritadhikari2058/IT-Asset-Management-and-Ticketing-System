"""Accounts + soft-delete + recycle-bin tests (spec sections 6-7)."""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from assets.models import Asset, AssetCategory
from common.models import AuditLog
from tickets.models import Ticket, TicketCategory


def token(user):
    return str(RefreshToken.for_user(user).access_token)


def auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token(user)}")


def make_users():
    dep = Department.objects.create(name="Eng", code="ENGX")
    admin = User.objects.create_user(
        username="a@x", email="a@x", employee_id="A1", password="pw12345678",
        role="system_admin", home_department=dep)
    mgr = User.objects.create_user(
        username="m@x", email="m@x", employee_id="M1", password="pw12345678",
        role="it_manager", home_department=dep)
    emp = User.objects.create_user(
        username="e@x", email="e@x", employee_id="E1", password="pw12345678",
        role="employee", home_department=dep)
    return dep, admin, mgr, emp


class SoftDeletePolicyTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_normal_delete_soft_deletes_and_hides(self):
        auth(self.c, self.mgr)
        cat = AssetCategory.objects.create(name="Laptops")
        res = self.c.delete(f"/api/assets/categories/{cat.pk}/", {})
        self.assertEqual(res.status_code, 204)
        self.assertTrue(
            AssetCategory.all_objects.get(pk=cat.pk).is_deleted)
        # hidden from normal list
        res = self.c.get("/api/assets/categories/")
        self.assertNotIn("Laptops", str(res.content))

    def test_only_admin_hard_delete(self):
        auth(self.c, self.mgr)
        cat = AssetCategory.objects.create(name="Desks")
        res = self.c.post(f"/api/assets/categories/{cat.pk}/hard_delete/",
                          {"confirm": str(cat.pk), "reason": "x"},
                          format="json")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.admin)
        res = self.c.post(f"/api/assets/categories/{cat.pk}/hard_delete/",
                          {"confirm": str(cat.pk), "reason": "cleanup"},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(
            action="hard_delete").exists())

    def test_recycle_bin_restore_and_uniqueness_block(self):
        # Unique identifiers are NOT released on soft delete: reusing the
        # same asset_tag while the row is deleted must fail at the DB.
        auth(self.c, self.admin)
        a_cat = AssetCategory.objects.create(name="C1")
        a1 = Asset.objects.create(asset_tag="T1", name="n", category=a_cat)
        a1.soft_delete(by_user=self.admin)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Asset.objects.create(asset_tag="T1", name="n2",
                                     category=a_cat)
        # Detail shows the record; restore works and preserves the PK.
        res = self.c.get(f"/api/recycle-bin/assets.Asset/{a1.pk}/")
        self.assertEqual(res.status_code, 200)
        res = self.c.post(
            f"/api/recycle-bin/assets.Asset/{a1.pk}/restore/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Asset.all_objects.get(pk=a1.pk).is_deleted)

    def test_soft_delete_preserves_relations(self):
        auth(self.c, self.mgr)
        tcat = TicketCategory.objects.create(name="SW")
        t = Ticket.objects.create(title="t", description="d",
                                  category=tcat, requester=self.emp,
                                  department=self.dep)
        t.soft_delete(by_user=self.mgr)
        self.assertEqual(Ticket.all_objects.get(pk=t.pk).history.count(), 0)
        # ticket history preserved (none deleted); requester intact
        self.assertEqual(Ticket.all_objects.get(pk=t.pk).requester, self.emp)

    def test_bulk_employee_update_preserves_roles(self):
        auth(self.c, self.mgr)
        res = self.c.post(
            "/api/accounts/users/bulk_update/",
            {"rows": [{"employee_id": "E1", "phone": "999",
                       "role": "system_admin",
                       "can_create_tickets": False}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.role, "employee")
        self.assertTrue(self.emp.can_create_tickets)
        self.assertEqual(self.emp.phone, "999")

    def test_bulk_delete_never_hard_deletes(self):
        auth(self.c, self.mgr)
        tcat = TicketCategory.objects.create(name="HW")
        t = Ticket.objects.create(title="t", description="d",
                                  category=tcat, requester=self.emp,
                                  department=self.dep)
        res = self.c.post("/api/tickets/bulk_delete/",
                          {"ids": [t.pk], "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Ticket.all_objects.filter(pk=t.pk).exists())
        self.assertTrue(Ticket.all_objects.get(pk=t.pk).is_deleted)


class ImportTemplateTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_template_json_by_default(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/accounts/users/bulk_import/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["matching_key"], "employee_id")
        self.assertIn("employee_id", res.data["template_columns"])

    def test_employee_template_csv_download(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/accounts/users/bulk_import/?download=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("employee_import_template.csv",
                      res["Content-Disposition"])
        header = res.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(header), 1)  # header only, no sample rows
        self.assertEqual(header[0].split(","),
                         ["employee_id", "email", "first_name",
                          "last_name", "phone", "job_title",
                          "home_department", "is_active"])

    def test_employee_template_forbidden_for_employee(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/accounts/users/bulk_import/?download=csv")
        self.assertEqual(res.status_code, 403)


def _csv_rows(response):
    import csv as _csv
    import io as _io
    return list(_csv.DictReader(
        _io.StringIO(response.content.decode("utf-8-sig"))))


class CurrentUserTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_me_returns_own_profile(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/accounts/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["employee_id"], "E1")
        self.assertEqual(res.data["role"], "employee")
        self.assertIn("can_create_tickets", res.data)

    def test_me_requires_auth(self):
        res = self.c.get("/api/accounts/me/")
        self.assertEqual(res.status_code, 401)


class BulkImportReportTests(TestCase):
    """CSV error reports for the employee import confirmation POST."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def _rows(self):
        return [
            {"employee_id": "E9", "email": "e9@example.com",
             "job_title": "UNIQUE-JOB-9"},
            {"employee_id": "E1", "email": "dupe@example.com"},
            {"email": "missing-key@example.com"},  # no employee_id -> failed
        ]

    def test_confirm_json_unchanged_by_default(self):
        res = self.c.post("/api/accounts/users/bulk_import/",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["E9"])
        self.assertEqual(len(res.data["skipped"]), 1)
        self.assertEqual(len(res.data["failed"]), 1)
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 1, "failed": 1})
        # Roles / ticket-creation rights untouched by import.
        from accounts.models import User
        u9 = User.objects.get(employee_id="E9")
        self.assertEqual(u9.role, "employee")
        self.assertTrue(u9.can_create_tickets)

    def test_confirm_csv_report(self):
        res = self.c.post("/api/accounts/users/bulk_import/?download=csv",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("employee_import_report.csv",
                      res["Content-Disposition"])
        rows = _csv_rows(res)
        self.assertTrue(rows)
        by_key = {r["key"]: r for r in rows}
        self.assertEqual(set(r["outcome"] for r in rows),
                         {"successful", "skipped", "failed"})
        self.assertEqual(by_key["E9"]["outcome"], "successful")
        self.assertEqual(by_key["E9"]["row"], "2")
        self.assertEqual(by_key["E1"]["outcome"], "skipped")
        self.assertEqual(by_key["E1"]["row"], "3")
        self.assertIn("exists", by_key["E1"]["message"])
        failed = [r for r in rows if r["outcome"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["row"], "4")
        self.assertIn("employee_id", failed[0]["message"])
        # No secrets or unnecessary personal data in the report.
        blob = res.content.decode("utf-8-sig")
        self.assertNotIn("UNIQUE-JOB-9", blob)
        self.assertNotIn("missing-key@example.com", blob)
        self.assertNotIn("dupe@example.com", blob)
        self.assertNotIn("password", blob.lower())

    def test_confirm_csv_duplicate_in_file_failed(self):
        rows = [{"employee_id": "E5", "email": "e5@example.com"},
                {"employee_id": "E5", "email": "e5b@example.com"}]
        res = self.c.post("/api/accounts/users/bulk_import/?download=csv",
                          {"rows": rows, "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.status_code, 200)
        rows = _csv_rows(res)
        failed = [r for r in rows if r["outcome"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["key"], "E5")
        self.assertEqual(failed[0]["row"], "3")
        self.assertIn("duplicate", failed[0]["message"])

    def test_confirm_still_requires_confirmation_for_csv(self):
        res = self.c.post("/api/accounts/users/bulk_import/?download=csv",
                          {"rows": self._rows(), "preview": False},
                          format="json")
        self.assertEqual(res.status_code, 400)

    def test_report_forbidden_for_employee(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/users/bulk_import/?download=csv",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 403)
