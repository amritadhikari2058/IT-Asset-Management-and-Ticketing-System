"""Asset API tests: bulk safety (assignment guard), bulk assignment."""
import threading
from django.db import IntegrityError, connection, transaction
from unittest import SkipTest
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department, User
from accounts.tests import auth, make_users
from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
    Disposal, Maintenance,
)
from common.models import AuditLog, Notification


class AssetBulkSafetyTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")

    def test_bulk_asset_update_cannot_change_assignment(self):
        auth(self.c, self.mgr)
        a = Asset.objects.create(asset_tag="A1", name="n",
                                 category=self.acat)
        res = self.c.post("/api/assets/bulk_update/",
                          {"rows": [{"asset_tag": "A1",
                                     "assigned_to": self.emp.pk}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["failed"]), 1)
        a.refresh_from_db()
        self.assertIsNone(a.assigned_to)

    def test_asset_template_json_by_default(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/assets/bulk_create/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["matching_key"], "asset_tag")
        self.assertIn("asset_tag", res.data["template_columns"])

    def test_asset_template_csv_download(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/assets/bulk_create/?download=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("asset_import_template.csv",
                      res["Content-Disposition"])
        header = res.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(header), 1)  # header only, no sample rows
        self.assertEqual(header[0].split(","),
                         ["asset_tag", "name", "category",
                          "serial_number", "status", "department", "location",
                          "description", "purchase_date", "warranty_expiry",
                          "purchase_cost"])

    def test_asset_template_forbidden_for_employee(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/assets/bulk_create/?download=csv")
        self.assertEqual(res.status_code, 403)


def _csv_rows(response):
    import csv as _csv
    import io as _io
    return list(_csv.DictReader(
        _io.StringIO(response.content.decode("utf-8-sig"))))


class BulkCreateReportTests(TestCase):
    """CSV error reports for the asset bulk-create confirmation POST."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        Asset.objects.create(asset_tag="OLD", name="old",
                             category=self.acat)
        auth(self.c, self.mgr)

    def _rows(self):
        return [
            {"asset_tag": "A9", "name": "new",
             "category": "Laptop", "location": "UNIQUE-LOC-9"},
            {"asset_tag": "OLD", "name": "dup",
             "category": "Laptop"},  # exists -> skipped
            {"asset_tag": "BADC", "name": "bad",
             "category": "NoSuchCat"},  # unknown category -> failed
            "oops",  # malformed row -> failed with a safe message
        ]

    def test_confirm_json_unchanged_by_default(self):
        res = self.c.post("/api/assets/bulk_create/",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["A9"])
        self.assertEqual(len(res.data["skipped"]), 1)
        self.assertEqual(res.data["skipped"][0]["asset_tag"], "OLD")
        self.assertEqual(len(res.data["failed"]), 2)
        # No silent assignment changes through bulk create.
        a9 = Asset.objects.get(asset_tag="A9")
        self.assertIsNone(a9.assigned_to)

    def test_confirm_csv_report(self):
        res = self.c.post("/api/assets/bulk_create/?download=csv",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("asset_import_report.csv",
                      res["Content-Disposition"])
        rows = _csv_rows(res)
        self.assertTrue(rows)
        by_key = {r["key"]: r for r in rows}
        self.assertEqual(set(r["outcome"] for r in rows),
                         {"successful", "skipped", "failed"})
        self.assertEqual(by_key["A9"]["outcome"], "successful")
        self.assertEqual(by_key["A9"]["row"], "2")
        self.assertEqual(by_key["OLD"]["outcome"], "skipped")
        self.assertEqual(by_key["OLD"]["row"], "3")
        self.assertIn("exists", by_key["OLD"]["message"])
        self.assertEqual(by_key["BADC"]["outcome"], "failed")
        self.assertEqual(by_key["BADC"]["row"], "4")
        self.assertIn("unknown category", by_key["BADC"]["message"])
        failed = [r for r in rows if r["outcome"] == "failed"]
        self.assertEqual(len(failed), 2)
        malformed = [r for r in failed if r["key"] == ""]
        self.assertEqual(len(malformed), 1)
        self.assertEqual(malformed[0]["row"], "5")
        self.assertTrue(malformed[0]["message"])
        # No secrets or unnecessary payload data in the report.
        blob = res.content.decode("utf-8-sig")
        self.assertNotIn("UNIQUE-LOC-9", blob)
        self.assertNotIn("Traceback", blob)
        self.assertNotIn(".py", blob)

    def test_confirm_still_requires_confirmation_for_csv(self):
        res = self.c.post("/api/assets/bulk_create/?download=csv",
                          {"rows": self._rows(), "preview": False},
                          format="json")
        self.assertEqual(res.status_code, 400)

    def test_report_forbidden_for_employee(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/assets/bulk_create/?download=csv",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 403)


class BulkAssignTests(TestCase):
    """Explicit bulk assignment: preview -> confirm, per-row results."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.free = Asset.objects.create(asset_tag="FREE", name="free",
                                         category=self.acat)
        self.free2 = Asset.objects.create(asset_tag="FREE2", name="free2",
                                          category=self.acat)
        self.busy = Asset.objects.create(
            asset_tag="BUSY", name="busy", category=self.acat,
            status="assigned", assigned_to=self.emp)
        self.ret = Asset.objects.create(asset_tag="RET", name="ret",
                                        category=self.acat, status="retired")
        self.rep = Asset.objects.create(asset_tag="REP", name="rep",
                                        category=self.acat,
                                        status="in_repair")
        self.lost = Asset.objects.create(asset_tag="LOST", name="lost",
                                         category=self.acat, status="lost")
        self.gone = Asset.objects.create(asset_tag="GONE", name="gone",
                                         category=self.acat)
        self.gone.soft_delete(by_user=self.admin, reason="t")
        self.e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        self.inactive = User.objects.create_user(
            username="e3@x", email="e3@example.com", employee_id="E3",
            password="pw12345678", home_department=self.dep)
        self.inactive.is_active = False
        self.inactive.save(update_fields=["is_active"])
        self.deleted_emp = User.objects.create_user(
            username="e4@x", email="e4@example.com", employee_id="E4",
            password="pw12345678", home_department=self.dep)
        self.deleted_emp.soft_delete(by_user=self.admin, reason="t")
        auth(self.c, self.mgr)

    def _counts(self):
        return (Assignment.objects.count(), AssetHistory.objects.count(),
                AuditLog.objects.count())

    def test_preview_writes_nothing(self):
        before = self._counts()
        res = self.c.post("/api/assets/bulk_assign/",
                          {"assignments": [
                              {"asset_tag": "FREE", "employee_id": "E2"},
                              {"asset_tag": "NOPE", "employee_id": "E2"}]},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["affected"], 1)
        self.assertEqual(len(res.data["invalid"]), 1)
        self.assertEqual(self._counts(), before)
        self.free.refresh_from_db()
        self.assertIsNone(self.free.assigned_to)
        self.assertEqual(self.free.status, "available")

    def test_confirm_required(self):
        before = self._counts()
        res = self.c.post("/api/assets/bulk_assign/",
                          {"assignments": [
                              {"asset_tag": "FREE", "employee_id": "E2"}],
                           "preview": False}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._counts(), before)

    def test_success_writes_assignment_history_audit(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "FREE", "employee_id": "E2",
                              "note": "deploy"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 0})
        self.assertEqual(res.data["successful"][0]["asset_tag"], "FREE")
        self.free.refresh_from_db()
        self.assertEqual(self.free.assigned_to, self.e2)
        self.assertEqual(self.free.status, "assigned")
        assn = Assignment.objects.get(asset=self.free)
        self.assertEqual(assn.assigned_to, self.e2)
        self.assertEqual(assn.assigned_by, self.mgr)
        self.assertEqual(assn.note, "deploy")
        hist = AssetHistory.objects.filter(asset=self.free).latest("id")
        self.assertEqual(hist.action, "assigned")
        self.assertTrue(AuditLog.objects.filter(
            entity_type="assets.asset", object_id=str(self.free.pk),
            action="assignment").exists())

    def test_multiple_rows_succeed_independently(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "FREE", "employee_id": "E2"},
                              {"asset_tag": "FREE2", "employee_id": "E1"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 2, "skipped": 0, "failed": 0})
        self.assertEqual(Assignment.objects.filter(
            assigned_by=self.mgr).count(), 2)

    def test_invalid_asset_and_employee_fail(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "NOPE", "employee_id": "E2"},
                              {"asset_tag": "FREE", "employee_id": "ZZZ"},
                              {"asset_tag": "", "employee_id": "E2"},
                              {"asset_tag": "FREE2"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 4})
        msgs = " ".join(f["errors"] for f in res.data["failed"])
        self.assertIn("not found", msgs)
        self.assertIn("required", msgs)

    def test_deleted_and_inactive(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [
                {"asset_tag": "GONE", "employee_id": "E2"},
                {"asset_tag": "FREE", "employee_id": "E4"},
                {"asset_tag": "FREE2", "employee_id": "E3"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 3})
        msgs = " ".join(f["errors"] for f in res.data["failed"])
        self.assertIn("deleted", msgs)
        self.assertIn("inactive", msgs)

    def test_duplicate_tags_reported(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "FREE", "employee_id": "E2"},
                              {"asset_tag": "FREE", "employee_id": "E1"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 1})
        self.assertIn("duplicate",
                      res.data["failed"][0]["errors"])
        # First occurrence wins; no ambiguous reassignment.
        self.free.refresh_from_db()
        self.assertEqual(self.free.assigned_to, self.e2)

    def test_conflict_skipped_without_overwrite(self):
        n_assign = Assignment.objects.filter(asset=self.busy).count()
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "BUSY", "employee_id": "E2"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 1, "failed": 0})
        self.assertIn("already assigned",
                      res.data["skipped"][0]["reason"])
        self.busy.refresh_from_db()
        self.assertEqual(self.busy.assigned_to, self.emp)
        self.assertEqual(Assignment.objects.filter(asset=self.busy).count(),
                         n_assign)

    def test_disallowed_statuses_fail(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "RET", "employee_id": "E2"},
                              {"asset_tag": "REP", "employee_id": "E2"},
                              {"asset_tag": "LOST", "employee_id": "E2"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 3})
        for f in res.data["failed"]:
            self.assertIn("status", f["errors"])

    def test_mixed_rows_and_row_atomicity(self):
        res = self.c.post(
            "/api/assets/bulk_assign/",
            {"assignments": [{"asset_tag": "FREE", "employee_id": "E2"},
                              {"asset_tag": "BUSY", "employee_id": "E2"},
                              {"asset_tag": "RET", "employee_id": "E2"},
                              {"asset_tag": "NOPE", "employee_id": "E2"}],
             "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 1, "failed": 2})
        rows = ([r["row"] for r in res.data["successful"]] +
                [r["row"] for r in res.data["skipped"]] +
                [r["row"] for r in res.data["failed"]])
        self.assertEqual(sorted(rows), [1, 2, 3, 4])
        # Failed rows left no partial records behind.
        self.assertFalse(Assignment.objects.filter(
            asset__asset_tag="RET").exists())
        self.assertFalse(AssetHistory.objects.filter(
            asset__asset_tag="RET").exists())
        self.assertFalse(Assignment.objects.filter(
            asset__asset_tag="NOPE").exists())

    def test_forbidden_for_employee_and_anonymous(self):
        auth(self.c, self.emp)
        for body in ({"assignments": [{"asset_tag": "FREE",
                                        "employee_id": "E2"}]},
                     {"assignments": [{"asset_tag": "FREE",
                                        "employee_id": "E2"}],
                      "preview": False, "confirm": True}):
            res = self.c.post("/api/assets/bulk_assign/", body,
                              format="json")
            self.assertEqual(res.status_code, 403)
        self.c.credentials()
        res = self.c.post("/api/assets/bulk_assign/",
                          {"assignments": [{"asset_tag": "FREE",
                                            "employee_id": "E2"}]},
                          format="json")
        self.assertEqual(res.status_code, 401)
        self.free.refresh_from_db()
        self.assertIsNone(self.free.assigned_to)

    def test_single_assign_and_return_intact(self):
        res = self.c.post(f"/api/assets/{self.free.pk}/assign/",
                          {"assigned_to": self.e2.pk, "note": "one"},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.free.refresh_from_db()
        self.assertEqual(self.free.assigned_to, self.e2)
        res = self.c.post(f"/api/assets/{self.free.pk}/return_asset/",
                          {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.free.refresh_from_db()
        self.assertIsNone(self.free.assigned_to)
        self.assertEqual(self.free.status, "available")


class AssetNotificationTests(TestCase):
    """In-app notifications for asset assignment + return only.

    No emails, no preference checks Ã¢â‚¬â€ pure Notification rows sharing the
    mutation's transaction.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.free = Asset.objects.create(asset_tag="FREE", name="free",
                                         category=self.acat)
        self.e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        auth(self.c, self.mgr)

    def _for_asset(self, asset):
        return Notification.objects.filter(
            entity_type="assets.Asset", object_id=str(asset.pk))

    def test_assign_notifies_new_holder_not_actor(self):
        res = self.c.post(f"/api/assets/{self.free.pk}/assign/",
                          {"assigned_to": self.e2.pk}, format="json")
        self.assertEqual(res.status_code, 200)
        notes = self._for_asset(self.free)
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.get().recipient, self.e2)
        self.assertEqual(
            Notification.objects.filter(recipient=self.mgr).count(), 0)

    def test_assign_to_self_notifies_nobody(self):
        res = self.c.post(f"/api/assets/{self.free.pk}/assign/",
                          {"assigned_to": self.mgr.pk}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._for_asset(self.free).count(), 0)

    def test_return_notifies_previous_holder(self):
        self.c.post(f"/api/assets/{self.free.pk}/assign/",
                    {"assigned_to": self.e2.pk}, format="json")
        self.assertEqual(self._for_asset(self.free).count(), 1)
        res = self.c.post(f"/api/assets/{self.free.pk}/return_asset/",
                          {}, format="json")
        self.assertEqual(res.status_code, 200)
        notes = self._for_asset(self.free)
        self.assertEqual(notes.count(), 2)
        self.assertEqual(notes.filter(recipient=self.e2).count(), 2)
        self.assertEqual(
            Notification.objects.filter(recipient=self.mgr).count(), 0)

    def test_return_with_no_holder_notifies_nobody(self):
        res = self.c.post(f"/api/assets/{self.free.pk}/return_asset/",
                          {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._for_asset(self.free).count(), 0)

    def test_bulk_assign_notifies_only_successes(self):
        busy = Asset.objects.create(asset_tag="BUSY", name="busy",
                                    category=self.acat, status="assigned",
                                    assigned_to=self.emp)
        res = self.c.post("/api/assets/bulk_assign/",
                          {"assignments": [
                              {"asset_tag": "FREE", "employee_id": "E2"},
                              {"asset_tag": "BUSY", "employee_id": "E2"},
                              {"asset_tag": "NOPE", "employee_id": "E2"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 1, "failed": 1})
        notes = self._for_asset(self.free)
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.get().recipient, self.e2)
        self.assertEqual(self._for_asset(busy).count(), 0)

    def test_preview_writes_no_notifications(self):
        res = self.c.post("/api/assets/bulk_assign/",
                          {"assignments": [
                              {"asset_tag": "FREE", "employee_id": "E2"}]},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Notification.objects.count(), 0)

    def test_failed_validation_notifies_nobody(self):
        res = self.c.post("/api/assets/bulk_assign/",
                          {"assignments": [
                              {"asset_tag": "FREE", "employee_id": "ZZZ"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"]["failed"], 1)
        self.assertEqual(Notification.objects.count(), 0)


class HistoryAssignmentFilterTests(TestCase):
    """?asset= narrows history/assignments without widening permissions."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.a1 = Asset.objects.create(asset_tag="F1", name="n1",
                                       category=self.acat)
        self.a2 = Asset.objects.create(asset_tag="F2", name="n2",
                                       category=self.acat)
        AssetHistory.objects.create(asset=self.a1, actor=self.mgr,
                                    action="created")
        AssetHistory.objects.create(asset=self.a2, actor=self.mgr,
                                    action="created")
        Assignment.objects.create(asset=self.a1, assigned_to=self.emp,
                                  assigned_by=self.mgr)
        auth(self.c, self.mgr)

    def test_history_filter_by_asset(self):
        res = self.c.get(f"/api/assets/histories/?asset={self.a1.pk}")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if "results" in res.data else res.data
        self.assertTrue(rows)
        self.assertTrue(all(r["asset"] == self.a1.pk for r in rows))

    def test_assignment_filter_by_asset(self):
        res = self.c.get(
            f"/api/assets/assignments/history/?asset={self.a1.pk}")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if "results" in res.data else res.data
        self.assertTrue(rows)
        self.assertTrue(all(r["asset"] == self.a1.pk for r in rows))

    def test_employee_history_still_hidden(self):
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/histories/?asset={self.a1.pk}")
        rows = res.data.get("results", res.data) if res.status_code == 200 \
            else []
        self.assertEqual(list(rows), [])


class AssetAttachmentTests(TestCase):
    """Secure asset attachments: same lifecycle as ticket attachments."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(asset_tag="AT1", name="n",
                                          category=self.acat,
                                          assigned_to=self.emp,
                                          status="assigned",
                                          department=self.dep)
        auth(self.c, self.mgr)

    def tearDown(self):
        # Test-DB rows only; never real user uploads.
        # Materialize rows first so a closed DB (possible under file-DB test
        # settings where request_finished closes the connection before this
        # loop runs) cannot turn this cleanup loop into a test error.
        try:
            attachments = list(AssetAttachment.all_objects.all())
        except Exception:
            attachments = []
        for att in attachments:
            try:
                if att.file:
                    att.file.storage.delete(att.file.name)
            except Exception:
                pass

    def _upload(self, name="doc.txt", content=b"hello",
                ctype="text/plain", asset=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile(name, content, content_type=ctype)
        return self.c.post("/api/assets/attachments/",
                           {"asset": (asset or self.asset).pk, "file": up},
                           format="multipart")

    def test_upload_and_list(self):
        res = self._upload()
        self.assertEqual(res.status_code, 201)
        aid = res.data["id"]
        att = AssetAttachment.objects.get(pk=aid)
        self.assertTrue(att.file.name.startswith("asset_attachments/"))
        self.assertNotIn("..", att.file.name)
        self.assertTrue(att.original_filename.endswith("doc.txt"))
        self.assertEqual(att.uploaded_by, self.mgr)
        res = self.c.get(f"/api/assets/attachments/?asset={self.asset.pk}")
        rows = res.data["results"] if "results" in res.data else res.data
        self.assertEqual([r["id"] for r in rows], [aid])
        self.assertTrue(AuditLog.objects.filter(
            entity_type="assets.assetattachment",
            object_id=str(aid), action="create").exists())

    def test_bad_extension_and_executable_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("evil.exe", b"data",
                                 content_type="application/octet-stream")
        res = self.c.post("/api/assets/attachments/",
                          {"asset": self.asset.pk, "file": bad},
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    @override_settings(ATTACHMENT_MAX_SIZE_MB=0.001)
    def test_oversize_rejected(self):
        res = self._upload(content=b"x" * 2000)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    def test_employee_cannot_upload_but_can_download_visible(self):
        auth(self.c, self.emp)
        res = self._upload()
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.mgr)
        aid = self._upload().data["id"]
        auth(self.c, self.emp)
        dl = self.c.get(f"/api/assets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        # Consuming the stream releases the file handle held by the
        # FileResponse; the response is left for the client to collect so
        # the test does not fire request_finished mid-transaction (which
        # would close the connection under TestCase's atomic block).
        self.assertEqual(b"".join(dl.streaming_content), b"hello")

    def test_anonymous_denied(self):
        self.c.credentials()
        res = self.c.get("/api/assets/attachments/")
        self.assertEqual(res.status_code, 401)

    def test_upload_to_missing_or_deleted_asset(self):
        res = self.c.post("/api/assets/attachments/",
                          {"asset": 999999, "file": self._upload_file()},
                          format="multipart")
        self.assertIn(res.status_code, (400, 403, 404))
        gone = Asset.objects.create(asset_tag="GONE", name="g",
                                    category=self.acat)
        gone.soft_delete(by_user=self.admin, reason="t")
        res = self.c.post("/api/assets/attachments/",
                          {"asset": gone.pk, "file": self._upload_file()},
                          format="multipart")
        self.assertIn(res.status_code, (400, 403, 404))
        self.assertEqual(AssetAttachment.objects.count(), 0)

    def _upload_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile("d.txt", b"hi", content_type="text/plain")

    def test_soft_delete_keeps_file_restore_reexposes(self):
        aid = self._upload().data["id"]
        att = AssetAttachment.objects.get(pk=aid)
        stored = att.file.name
        self.assertFalse(AuditLog.objects.filter(
            action="soft_delete").exists())
        self.c.delete(f"/api/assets/attachments/{aid}/")
        att = AssetAttachment.all_objects.get(pk=aid)
        self.assertTrue(att.is_deleted)
        self.assertTrue(att.file.storage.exists(stored))
        dl = self.c.get(f"/api/assets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 404)
        att.restore()
        dl = self.c.get(f"/api/assets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(b"".join(dl.streaming_content), b"hello")
        self.assertTrue(AuditLog.objects.filter(
            entity_type="assets.assetattachment",
            object_id=str(aid), action="soft_delete").exists())

    def test_permanent_delete_removes_file_when_unreferenced(self):
        auth(self.c, self.admin)
        aid = self._upload().data["id"]
        stored = AssetAttachment.objects.get(pk=aid).file.name
        self.c.delete(f"/api/assets/attachments/{aid}/")
        res = self.c.post(
            f"/api/recycle-bin/assets.AssetAttachment/{aid}/permanent/",
            {"confirm": str(aid), "reason": "cleanup"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(AssetAttachment.all_objects.filter(
            pk=aid).exists())
        from django.core.files.storage import default_storage
        self.assertFalse(default_storage.exists(stored))

    def test_permanent_delete_keeps_shared_file(self):
        auth(self.c, self.admin)
        aid = self._upload().data["id"]
        first = AssetAttachment.objects.get(pk=aid)
        twin = AssetAttachment.objects.create(
            asset=self.asset, file=first.file.name,
            original_filename="twin.txt", uploaded_by=self.admin)
        self.c.delete(f"/api/assets/attachments/{aid}/")
        res = self.c.post(
            f"/api/recycle-bin/assets.AssetAttachment/{aid}/permanent/",
            {"confirm": str(aid), "reason": "cleanup"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(first.file.storage.exists(first.file.name))
        # Removing the last reference unlinks the file.
        twin.soft_delete(by_user=self.admin, reason="t")
        res = self.c.post(
            f"/api/recycle-bin/assets.AssetAttachment/{twin.pk}/permanent/",
            {"confirm": str(twin.pk), "reason": "cleanup"}, format="json")
        self.assertEqual(res.status_code, 200)
        from django.core.files.storage import default_storage
        self.assertFalse(default_storage.exists(first.file.name))

    def test_missing_file_returns_410(self):
        aid = self._upload().data["id"]
        att = AssetAttachment.objects.get(pk=aid)
        att.file.storage.delete(att.file.name)
        dl = self.c.get(f"/api/assets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 410)
        # No file body is opened for a 410, so there is nothing to close.


class AssetAttachmentDownloadConnectionTests(TransactionTestCase):
    """A consumed+closed download must leave the DB connection usable.

    Uses TransactionTestCase because closing the response fires
    ``request_finished``, and ``close_old_connections`` intentionally drops
    the connection when autocommit differs from the configured value --
    which is always the case inside a plain TestCase's atomic block. With
    autocommit matching the settings, the download can be fully consumed
    and closed while the connection stays reusable for later ORM work.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(asset_tag="AT1", name="n",
                                          category=self.acat,
                                          assigned_to=self.emp,
                                          status="assigned",
                                          department=self.dep)

    def tearDown(self):
        for att in list(AssetAttachment.all_objects.all()):
            if att.file:
                att.file.storage.delete(att.file.name)

    def test_download_response_lifecycle_keeps_connection_usable(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.db import connection

        aid = self.c.post(
            "/api/assets/attachments/",
            {"asset": self.asset.pk,
             "file": SimpleUploadedFile("doc.txt", b"hello",
                                        content_type="text/plain")},
            format="multipart").data["id"]

        dl = self.c.get(f"/api/assets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        self.assertFalse(getattr(dl, "closed", False))
        try:
            body = b"".join(dl.streaming_content)
        finally:
            dl.close()

        self.assertEqual(body, b"hello")
        self.assertTrue(getattr(dl, "closed", False))
        self.assertTrue(connection.is_usable())

        # The connection must still serve ORM work after the response was
        # consumed and closed; a dangling connection would raise
        # "sqlite3.ProgrammingError: Cannot operate on a closed database".
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.fetchone(), (1,))
        probe = AssetCategory.objects.create(name="Lifecycle Probe")
        self.assertIsNotNone(probe.pk)
        self.assertTrue(
            AssetCategory.objects.filter(pk=probe.pk).exists())
        self.assertTrue(connection.is_usable())


class AssetAttachmentIdorTests(TestCase):
    """Asset attachment IDOR: employees cannot reach out-of-scope files."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        # Asset assigned to emp (visible to emp via home department).
        self.own_asset = Asset.objects.create(
            asset_tag="OWN1", name="Own", category=self.acat,
            assigned_to=self.emp, status="assigned", department=self.dep)
        # Asset assigned to another employee in a different department
        # (NOT visible to emp).
        other = self.emp.__class__.objects.create_user(
            username="o@x", email="o@x", employee_id="O1",
            password="pw12345678", role="employee")
        other_dep = Department.objects.create(
            name="Other Dept", code="OT", description="x")
        self.other_asset = Asset.objects.create(
            asset_tag="OTH1", name="Other", category=self.acat,
            assigned_to=other, status="assigned", department=other_dep)

    def _upload(self, asset, name="doc.txt", content=b"hello",
                ctype="text/plain"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile(name, content, content_type=ctype)
        return self.c.post("/api/assets/attachments/",
                           {"asset": asset.pk, "file": up},
                           format="multipart")

    def test_employee_cannot_download_other_asset_attachment(self):
        auth(self.c, self.mgr)
        aid = self._upload(self.other_asset).data["id"]
        # Switch to the employee who has no visibility on the other asset.
        auth(self.c, self.emp)
        dl = self.c.get(f"/api/assets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 404)


class AssetStatusWorkflowTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        auth(self.c, self.mgr)

    def _asset(self, **kw):
        base = {"asset_tag": "T1", "name": "n", "category": self.acat}
        base.update(kw)
        return Asset.objects.create(**base)

    def test_generic_assigned_rejected(self):
        a = self._asset()
        res = self.c.patch(f"/api/assets/{a.pk}/", {"status": "assigned"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("status", res.data)
        a.refresh_from_db()
        self.assertEqual(a.status, "available")
        self.assertEqual(a.history.count(), 0)
        self.assertFalse(AuditLog.objects.filter(object_id=str(a.pk)).exists())

    def test_generic_retired_rejected(self):
        a = self._asset()
        res = self.c.patch(f"/api/assets/{a.pk}/", {"status": "retired"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.status, "available")

    def test_generic_lost_rejected(self):
        a = self._asset()
        res = self.c.patch(f"/api/assets/{a.pk}/", {"status": "lost"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.status, "available")

    def test_unchanged_status_resubmit_ok(self):
        a = self._asset(status="retired")
        res = self.c.patch(f"/api/assets/{a.pk}/",
                           {"name": "n2", "status": "retired"},
                           format="json")
        self.assertEqual(res.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.name, "n2")
        self.assertEqual(a.status, "retired")

    def test_ordinary_status_edit_ok(self):
        a = self._asset()
        res = self.c.patch(f"/api/assets/{a.pk}/",
                           {"status": "in_repair"}, format="json")
        self.assertEqual(res.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, "in_repair")

    def test_mark_lost_requires_reason(self):
        a = self._asset()
        for body in ({}, {"reason": ""}, {"reason": "   "}):
            res = self.c.post(f"/api/assets/{a.pk}/mark_lost/", body,
                              format="json")
            self.assertEqual(res.status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.status, "available")
        self.assertEqual(a.history.count(), 0)

    def test_mark_lost_writes_history_and_audit(self):
        a = self._asset()
        res = self.c.post(f"/api/assets/{a.pk}/mark_lost/",
                          {"reason": "Not returned after offboarding."},
                          format="json")
        self.assertEqual(res.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, "lost")
        self.assertEqual(
            a.history.filter(action="lost").count(), 1)
        self.assertIn("offboarding", a.history.get(action="lost").note)
        self.assertTrue(AuditLog.objects.filter(
            object_id=str(a.pk), action="status_change").exists())

    def test_mark_lost_closes_assignment(self):
        a = self._asset(status="assigned", assigned_to=self.emp)
        from assets.models import Assignment
        Assignment.objects.create(asset=a, assigned_to=self.emp,
                                  assigned_by=self.mgr)
        res = self.c.post(f"/api/assets/{a.pk}/mark_lost/",
                          {"reason": "Vanished from desk."}, format="json")
        self.assertEqual(res.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, "lost")
        self.assertIsNone(a.assigned_to)
        open_rows = Assignment.objects.filter(
            asset=a, returned_at__isnull=True).count()
        self.assertEqual(open_rows, 0)
        # Assignment history itself is preserved.
        self.assertEqual(Assignment.objects.filter(asset=a).count(), 1)

    def test_mark_lost_idempotent(self):
        a = self._asset()
        self.c.post(f"/api/assets/{a.pk}/mark_lost/",
                    {"reason": "Gone."}, format="json")
        res = self.c.post(f"/api/assets/{a.pk}/mark_lost/",
                          {"reason": "Gone again."}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            a.history.filter(action="lost").count(), 1)
        self.assertEqual(AuditLog.objects.filter(
            object_id=str(a.pk), action="status_change").count(), 1)

    def test_mark_lost_forbidden_for_employee(self):
        a = self._asset()
        auth(self.c, self.emp)
        res = self.c.post(f"/api/assets/{a.pk}/mark_lost/",
                          {"reason": "Gone."}, format="json")
        self.assertEqual(res.status_code, 403)
        a.refresh_from_db()
        self.assertEqual(a.status, "available")


class AssetOrderingTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        auth(self.c, self.mgr)

    def _tags(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        rows = data["results"] if isinstance(data, dict) else data
        return [r["asset_tag"] for r in rows]

    def test_name_ordering(self):
        for tag in ("Z9", "A1", "M5"):
            Asset.objects.create(asset_tag=tag, name=f"n-{tag}",
                                 category=self.acat)
        res = self.c.get("/api/assets/", {"ordering": "name"})
        self.assertEqual(self._tags(res), ["A1", "M5", "Z9"])
        res = self.c.get("/api/assets/", {"ordering": "-name"})
        self.assertEqual(self._tags(res), ["Z9", "M5", "A1"])

    def test_unsupported_ordering_falls_back_to_tag_order(self):
        for tag in ("Z9", "A1"):
            Asset.objects.create(asset_tag=tag, name=f"n-{tag}",
                                 category=self.acat)
        res = self.c.get("/api/assets/", {"ordering": "owner"})
        self.assertEqual(self._tags(res), ["A1", "Z9"])


class AssetSerialUniquenessTests(TestCase):
    """Serial numbers stay optional but unique across ALL assets.

    Enforcement is layered: serializer validation (readable field error),
    bulk-endpoint pre-checks (row-level messages), and the SQLite triggers
    from migration 0003 (concurrency backstop). Soft-deleted assets keep
    reserving their serial so a restore can never collide.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.first = Asset.objects.create(asset_tag="S1", name="one",
                                          category=self.acat,
                                          serial_number="SN-1")
        auth(self.c, self.mgr)

    def _create(self, **kw):
        payload = {"asset_tag": "S2", "name": "two",
                   "category": self.acat.pk, "serial_number": ""}
        payload.update(kw)
        return self.c.post("/api/assets/", payload, format="json")

    # ---------- serializer-level (readable errors) ----------

    def test_duplicate_serial_rejected_on_create(self):
        res = self._create(serial_number="SN-1")
        self.assertEqual(res.status_code, 400)
        self.assertIn("serial_number", res.data)
        self.assertIn("already used", str(res.data["serial_number"]))
        self.assertEqual(Asset.all_objects.count(), 1)

    def test_duplicate_serial_rejected_on_update(self):
        other = Asset.objects.create(asset_tag="S2", name="two",
                                     category=self.acat)
        res = self.c.patch(f"/api/assets/{other.pk}/",
                           {"serial_number": "SN-1"}, format="json")
        self.assertEqual(res.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.serial_number, "")

    def test_serial_is_trimmed_before_the_duplicate_check(self):
        res = self._create(serial_number="  SN-1  ")
        self.assertEqual(res.status_code, 400)
        self.assertIn("SN-1", str(res.data["serial_number"]))

    def test_unchanged_serial_still_saves(self):
        res = self.c.patch(f"/api/assets/{self.first.pk}/",
                           {"serial_number": "SN-1", "name": "renamed"},
                           format="json")
        self.assertEqual(res.status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.serial_number, "SN-1")
        self.assertEqual(self.first.name, "renamed")

    def test_blank_serial_allowed_repeatedly(self):
        for tag in ("A", "B", "C"):
            res = self._create(asset_tag=tag, serial_number="")
            self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(
            self._create(asset_tag="D", serial_number="   ").status_code, 201)
        self.assertEqual(
            Asset.all_objects.filter(serial_number="").count(), 4)

    def test_soft_deleted_asset_keeps_reserving_its_serial(self):
        self.first.soft_delete(by_user=self.admin, reason="retired")
        res = self._create(serial_number="SN-1")
        self.assertEqual(res.status_code, 400)
        # Deleted rows are hidden from the default manager but still
        # occupy the serial (all_objects is what validation consults).
        self.assertFalse(Asset.objects.filter(serial_number="SN-1").exists())
        self.assertTrue(
            Asset.all_objects.filter(serial_number="SN-1").exists())

    # ---------- database-level (concurrency backstop) ----------

    def test_database_trigger_blocks_duplicate_insert(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Asset.objects.create(asset_tag="S9", name="x",
                                     category=self.acat,
                                     serial_number="SN-1")
        # The failed write rolled back cleanly; the row was not created.
        self.assertFalse(Asset.all_objects.filter(asset_tag="S9").exists())

    def test_database_trigger_blocks_duplicate_update(self):
        other = Asset.objects.create(asset_tag="S2", name="two",
                                     category=self.acat)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Asset.objects.filter(pk=other.pk).update(
                    serial_number="SN-1")
        other.refresh_from_db()
        self.assertEqual(other.serial_number, "")

    def test_database_trigger_ignores_blank_serials(self):
        for tag in ("S2", "S3", "S4"):
            Asset.objects.create(asset_tag=tag, name="n",
                                 category=self.acat, serial_number="")
        self.assertEqual(Asset.all_objects.count(), 4)

    def test_database_trigger_lets_an_asset_keep_its_own_serial(self):
        # UPDATE OF serial_number still fires on every ORM save(), so an
        # ordinary edit of an asset whose serial is unchanged must pass.
        self.first.name = "renamed"
        self.first.save()
        self.first.refresh_from_db()
        self.assertEqual(self.first.serial_number, "SN-1")

    def test_concurrent_duplicate_maps_to_a_400_field_error(self):
        # Simulate the race the serializer cannot see: the row passes
        # validation, then the DB trigger aborts the insert. The view must
        # answer 400 with a field error, never a 500 page.
        from assets import serializers as asset_serializers
        original = asset_serializers.AssetSerializer.validate_serial_number
        asset_serializers.AssetSerializer.validate_serial_number = (
            lambda self, value: (value or "").strip())
        try:
            res = self._create(serial_number="SN-1")
        finally:
            asset_serializers.AssetSerializer.validate_serial_number = (
                original)
        self.assertEqual(res.status_code, 400)
        self.assertIn("serial_number", res.data)
        self.assertIn("already used", str(res.data["serial_number"]))
        self.assertEqual(Asset.all_objects.count(), 1)

    # ---------- bulk endpoints ----------

    def test_bulk_create_duplicate_serial_rejected(self):
        res = self.c.post("/api/assets/bulk_create/", {
            "preview": False, "confirm": True,
            "rows": [
                {"asset_tag": "BK1", "name": "one",
                 "category": self.acat.name, "serial_number": "SN-BK-1"},
                {"asset_tag": "BK2", "name": "two",
                 "category": self.acat.name, "serial_number": "SN-BK-1"},
            ],
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["successful"]), 1)
        self.assertEqual(len(res.data["failed"]), 1)
        self.assertIn("serial", res.data["failed"][0]["errors"].lower())
        # self.first + BK1 persisted.
        self.assertEqual(Asset.all_objects.count(), 2)

    def test_bulk_update_duplicate_serial_rejected(self):
        other = Asset.objects.create(asset_tag="S2", name="two",
                                     category=self.acat)
        res = self.c.post("/api/assets/bulk_update/", {
            "preview": False, "confirm": True,
            "rows": [{"asset_tag": "S2", "serial_number": "SN-1"}],
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["failed"]), 1)
        self.assertIn("serial", res.data["failed"][0]["errors"].lower())
        other.refresh_from_db()
        self.assertEqual(other.serial_number, "")

    def test_serial_number_case_sensitivity_is_exact_match(self):
        # Exact-match semantics: no Lower() normalization is applied, so
        # "sn-1" differs from the existing "SN-1" on both SQLite (BINARY
        # collation for =) and PostgreSQL. Both serials coexist.
        b = Asset.objects.create(asset_tag="SX", name="x",
                                 category=self.acat, serial_number="sn-1")
        self.assertEqual(b.serial_number, "sn-1")
        self.assertEqual(
            Asset.all_objects.filter(serial_number="sn-1").count(), 1)
        self.assertEqual(
            Asset.all_objects.filter(serial_number="SN-1").count(), 1)


class AssetWarrantyTests(TestCase):
    """warranty_start/warranty_expiry are stored and returned by the API."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        auth(self.c, self.mgr)

    def test_warranty_dates_round_trip(self):
        res = self.c.post("/api/assets/", {
            "asset_tag": "W1", "name": "Warranty laptop",
            "category": self.acat.pk,
            "purchase_date": "2024-01-15",
            "warranty_start": "2024-02-01",
            "warranty_expiry": "2026-02-01",
            "purchase_cost": "1299.00",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["warranty_start"], "2024-02-01")
        self.assertEqual(res.data["warranty_expiry"], "2026-02-01")
        self.assertEqual(res.data["purchase_date"], "2024-01-15")

        a = Asset.objects.get(asset_tag="W1")
        self.assertEqual(str(a.warranty_start), "2024-02-01")
        self.assertEqual(str(a.warranty_expiry), "2026-02-01")

    def test_warranty_dates_optional(self):
        res = self.c.post("/api/assets/", {
            "asset_tag": "W2", "name": "No warranty",
            "category": self.acat.pk,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNone(res.data["warranty_start"])
        self.assertIsNone(res.data["warranty_expiry"])

    def test_warranty_dates_update(self):
        a = Asset.objects.create(asset_tag="W3", name="w3",
                                 category=self.acat)
        res = self.c.patch(f"/api/assets/{a.pk}/", {
            "warranty_start": "2025-01-01",
            "warranty_expiry": "2027-01-01",
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        a.refresh_from_db()
        self.assertEqual(str(a.warranty_start), "2025-01-01")
        self.assertEqual(str(a.warranty_expiry), "2027-01-01")


class AssetBulkSerialTests(TestCase):
    """Bulk create/update honour the same serial uniqueness policy."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        Asset.objects.create(asset_tag="OLD", name="old",
                             category=self.acat, serial_number="SN-1")
        auth(self.c, self.mgr)

    def _rows(self):
        return [
            {"asset_tag": "N1", "name": "n", "category": "Laptop",
             "serial_number": "SN-1"},   # clashes with OLD
            {"asset_tag": "N2", "name": "n", "category": "Laptop",
             "serial_number": "SN-2"},   # fresh
            {"asset_tag": "N3", "name": "n", "category": "Laptop",
             "serial_number": "SN-2"},   # clashes with N2 in the same file
        ]

    def test_preview_flags_duplicate_serials(self):
        res = self.c.post("/api/assets/bulk_create/",
                          {"rows": self._rows(), "preview": True},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["asset_tag"] for r in res.data["preview"]],
                         ["N2"])
        messages = " | ".join(e["errors"] for e in res.data["errors"])
        self.assertIn("duplicate serial number SN-1", messages)
        self.assertIn("duplicate serial number SN-2", messages)
        self.assertEqual(
            sorted(e["row"] for e in res.data["errors"]), [2, 4])

    def test_confirm_fails_duplicate_serial_rows_and_creates_the_rest(self):
        res = self.c.post("/api/assets/bulk_create/",
                          {"rows": self._rows(), "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["N2"])
        self.assertEqual(len(res.data["failed"]), 2)
        for row in res.data["failed"]:
            self.assertIn("duplicate serial number", row["errors"])
        self.assertFalse(Asset.all_objects.filter(asset_tag="N1").exists())
        self.assertFalse(Asset.all_objects.filter(asset_tag="N3").exists())
        self.assertEqual(Asset.all_objects.count(), 2)  # OLD + N2

    def test_blank_serials_are_not_treated_as_duplicates(self):
        rows = [{"asset_tag": f"B{i}", "name": "n", "category": "Laptop",
                 "serial_number": ""} for i in range(3)]
        res = self.c.post("/api/assets/bulk_create/",
                          {"rows": rows, "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.data["successful"], ["B0", "B1", "B2"])
        self.assertEqual(res.data["failed"], [])

    def test_bulk_update_rejects_a_duplicate_serial(self):
        other = Asset.objects.create(asset_tag="S2", name="two",
                                     category=self.acat, serial_number="")
        res = self.c.post("/api/assets/bulk_update/",
                          {"rows": [{"asset_tag": "S2",
                                     "serial_number": "SN-1"}],
                           "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["failed"]), 1)
        self.assertIn("duplicate serial number SN-1",
                      res.data["failed"][0]["errors"])
        other.refresh_from_db()
        self.assertEqual(other.serial_number, "")

    def test_bulk_update_accepts_a_fresh_serial(self):
        other = Asset.objects.create(asset_tag="S2", name="two",
                                     category=self.acat, serial_number="")
        res = self.c.post("/api/assets/bulk_update/",
                          {"rows": [{"asset_tag": "S2",
                                     "serial_number": "SN-9"}],
                           "preview": False, "confirm": True},
                           format="json")
        self.assertEqual(res.data["successful"], ["S2"])
        other.refresh_from_db()
        self.assertEqual(other.serial_number, "SN-9")

    def test_bulk_update_can_blank_a_serial(self):
        other = Asset.objects.create(asset_tag="S2", name="two",
                                     category=self.acat, serial_number="SN-2")
        res = self.c.post("/api/assets/bulk_update/",
                          {"rows": [{"asset_tag": "S2", "serial_number": ""}],
                           "preview": False, "confirm": True},
                           format="json")
        self.assertEqual(res.data["successful"], ["S2"])
        other.refresh_from_db()
        self.assertEqual(other.serial_number, "")


class AssetBulkUploadParseTests(TestCase):
    """Unreadable bulk uploads answer 400 JSON, never a Django 500 page."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        auth(self.c, self.mgr)

    def _upload(self, name, content, **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {"file": SimpleUploadedFile(name, content,
                                           content_type="text/plain")}
        data.update(fields)
        return self.c.post("/api/assets/bulk_create/", data,
                           format="multipart")

    def _assert_clean_400(self, res):
        self.assertEqual(res.status_code, 400)
        body = res.content.decode("utf-8", "replace")
        self.assertNotIn("Traceback", body)
        self.assertNotIn("DEBUG", body)
        self.assertNotIn("OperationalError", body)
        self.assertNotIn("UnicodeDecodeError", body)
        self.assertTrue(res["Content-Type"].startswith("application/json"))

    def test_binary_junk_csv_is_rejected(self):
        res = self._upload("data.csv", b"\xff\xfe\x00\x01junk\x00\xff")
        self._assert_clean_400(res)
        self.assertIn("file", res.data)

    def test_fake_xlsx_is_rejected(self):
        res = self._upload("assets.xlsx", b"this is not a zip archive")
        self._assert_clean_400(res)
        self.assertIn("file", res.data)

    def test_empty_csv_is_rejected(self):
        res = self._upload("empty.csv", b"")
        self._assert_clean_400(res)
        self.assertIn("file", res.data)

    def test_header_only_csv_previews_cleanly(self):
        res = self._upload("ok.csv",
                           b"asset_tag,name,category\n",
                           preview="true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["preview"], [])
        self.assertEqual(res.data["errors"], [])

    def test_valid_csv_still_imports(self):
        csv = ("asset_tag,name,category,serial_number\n"
               "P1,Printer,Laptop,PS-1\n").encode("utf-8")
        res = self._upload("good.csv", csv, preview="false", confirm="true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["P1"])
        self.assertEqual(res.data["failed"], [])
        self.assertTrue(
            Asset.all_objects.filter(asset_tag="P1",
                                     serial_number="PS-1").exists())

    def test_parse_errors_are_logged_server_side_only(self):
        with self.assertLogs("assets.views", level="ERROR") as captured:
            res = self._upload("data.csv", b"\xff\xfe\x00junk")
        self._assert_clean_400(res)
        self.assertTrue(any("bulk" in line or "parse" in line
                            for line in captured.output))


class AssetCreateWithFileTests(TestCase):
    """POST /api/assets/ may carry a file; success and failure paths."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        auth(self.c, self.mgr)

    def tearDown(self):
        for att in AssetAttachment.all_objects.all():
            try:
                if att.file:
                    att.file.storage.delete(att.file.name)
            except Exception:
                pass

    def _post(self, name="spec.pdf", content=b"%PDF-1.4 fake",
              ctype="application/pdf", **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile
        payload = {
            "asset_tag": "U1", "name": "unit",
            "category": self.acat.pk,
            "file": SimpleUploadedFile(name, content, content_type=ctype),
        }
        payload.update(fields)
        return self.c.post("/api/assets/", payload, format="multipart")

    def test_create_with_file_creates_asset_and_attachment(self):
        res = self._post()
        self.assertEqual(res.status_code, 201, res.data)
        aid = res.data["id"]
        att = AssetAttachment.objects.get(asset__pk=aid)
        self.assertTrue(att.file.name)
        self.assertTrue(att.original_filename.endswith("spec.pdf"))
        self.assertEqual(att.uploaded_by, self.mgr)
        self.assertTrue(AssetHistory.objects.filter(
            asset__pk=aid, action="created").exists())
        self.assertTrue(AuditLog.objects.filter(
            entity_type="assets.asset", object_id=str(aid),
            action="create").exists())

    def test_create_without_file_still_works(self):
        res = self.c.post("/api/assets/",
                          {"asset_tag": "U2", "name": "n",
                           "category": self.acat.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Asset.all_objects.filter(asset_tag="U2").count(), 1)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    @override_settings(ATTACHMENT_ALLOWED_EXTENSIONS=["pdf"])
    def test_invalid_file_type_is_rejected_and_no_asset_is_created(self):
        res = self._post(name="evil.exe", content=b"MZ",
                         ctype="application/octet-stream")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertEqual(Asset.all_objects.count(), 0)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    @override_settings(ATTACHMENT_MAX_SIZE_MB=0.001)
    def test_oversized_file_is_rejected_and_no_asset_is_created(self):
        res = self._post(content=b"x" * 2000)
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertEqual(Asset.all_objects.count(), 0)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    def test_rejected_file_leaves_no_partial_state_on_serial_conflict(self):
        Asset.objects.create(asset_tag="OLD", name="old",
                             category=self.acat, serial_number="SN-1")
        res = self._post(serial_number="SN-1")
        self.assertEqual(res.status_code, 400)
        self.assertIn("serial_number", res.data)
        self.assertEqual(Asset.all_objects.count(), 1)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    def test_file_on_patch_is_rejected_explicitly(self):
        created = self.c.post("/api/assets/",
                              {"asset_tag": "U3", "name": "n",
                               "category": self.acat.pk}, format="json")
        from django.core.files.uploadedfile import SimpleUploadedFile
        res = self.c.patch(
            f"/api/assets/{created.data['id']}/",
            {"name": "renamed",
             "file": SimpleUploadedFile("x.pdf", b"%PDF")},
            format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertEqual(AssetAttachment.objects.count(), 0)

    def test_employee_cannot_create_with_a_file(self):
        auth(self.c, self.emp)
        res = self._post()
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Asset.all_objects.count(), 0)


class AssetCategoryEditTests(TestCase):
    """Asset-category EDIT flow: staff-only PATCH and preserved asset
    relationships after renaming."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)
        self.acat = AssetCategory.objects.create(
            name="Laptop", description="Portable machines.")
        self.asset = Asset.objects.create(asset_tag="LT-1", name="n",
                                          category=self.acat)

    def test_staff_edits_name_and_description(self):
        res = self.c.patch(
            f"/api/assets/categories/{self.acat.pk}/",
            {"name": "Laptops & Tablets",
             "description": "Portable machines, incl. tablets."},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.acat.refresh_from_db()
        self.assertEqual(self.acat.name, "Laptops & Tablets")
        self.assertEqual(self.acat.description,
                         "Portable machines, incl. tablets.")

    def test_edit_preserves_asset_relationship(self):
        res = self.c.patch(f"/api/assets/categories/{self.acat.pk}/",
                           {"name": "Renamed"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.category_id, self.acat.pk)
        self.assertEqual(self.asset.category.name, "Renamed")

    def test_duplicate_name_rejected_with_field_error(self):
        AssetCategory.objects.create(name="Desk")
        res = self.c.patch(f"/api/assets/categories/{self.acat.pk}/",
                           {"name": "Desk"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data)

    def test_employee_cannot_edit_categories(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/assets/categories/{self.acat.pk}/",
                           {"name": "X"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.acat.refresh_from_db()
        self.assertEqual(self.acat.name, "Laptop")


class AssetWorkflowAuthorizationTests(TestCase):
    """Custom actions must not let non-IT users mutate asset workflows.

    PERMISSIONS.md grants employees read-only access to asset records and no
    access to return / maintenance / disposal actions; only IT staff may
    change assignment, maintenance, or disposal state. The frontend hiding
    these controls is UX only — the backend is the control boundary.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.colleague = User.objects.create_user(
            username="c@x", email="c@x", employee_id="C1",
            password="pw12345678", role="employee",
            home_department=self.dep)
        self.support = User.objects.create_user(
            username="s@x", email="s@x", employee_id="S1",
            password="pw12345678", role="it_support",
            home_department=self.dep)

    def test_employee_cannot_return_department_asset(self):
        asset = Asset.objects.create(
            asset_tag="RET-1", name="laptop", category=self.acat,
            status="assigned", assigned_to=self.colleague,
            department=self.dep)
        auth(self.c, self.emp)
        res = self.c.post(f"/api/assets/{asset.pk}/return_asset/", {},
                          format="json")
        self.assertEqual(res.status_code, 403)
        asset.refresh_from_db()
        self.assertEqual(asset.status, "assigned")
        self.assertEqual(asset.assigned_to_id, self.colleague.pk)

    def test_employee_cannot_mark_maintenance_overdue(self):
        asset = Asset.objects.create(
            asset_tag="MNT-1", name="laptop", category=self.acat,
            status="assigned", assigned_to=self.emp, department=self.dep)
        maint = Maintenance.objects.create(
            asset=asset, title="Fan check", maintenance_type="preventive",
            status="scheduled", scheduled_date=timezone.now())
        auth(self.c, self.emp)
        res = self.c.post(
            f"/api/assets/maintenance/{maint.pk}/mark_overdue/", {},
            format="json")
        self.assertEqual(res.status_code, 403)
        maint.refresh_from_db()
        self.assertEqual(maint.status, "scheduled")

    def test_it_support_cannot_approve_disposal_via_update(self):
        asset = Asset.objects.create(
            asset_tag="DSP-1", name="printer", category=self.acat)
        disposal = Disposal.objects.create(
            asset=asset, disposal_reason="end of life",
            disposal_method="recycled", approval_status="pending",
            created_by=self.mgr)
        auth(self.c, self.support)
        res = self.c.patch(f"/api/assets/disposals/{disposal.pk}/",
                           {"approval_status": "approved"}, format="json")
        self.assertEqual(res.status_code, 403)
        disposal.refresh_from_db()
        self.assertEqual(disposal.approval_status, "pending")
        self.assertIsNone(disposal.approver_id)
        self.assertIsNone(disposal.approved_at)

    def test_disposal_cannot_be_completed_by_patching_date(self):
        asset = Asset.objects.create(
            asset_tag="DSP-2", name="printer", category=self.acat)
        disposal = Disposal.objects.create(
            asset=asset, disposal_reason="end of life",
            disposal_method="recycled", approval_status="pending",
            created_by=self.mgr)
        auth(self.c, self.mgr)
        res = self.c.patch(
            f"/api/assets/disposals/{disposal.pk}/",
            {"disposal_date": timezone.now().isoformat()}, format="json")
        self.assertEqual(res.status_code, 400)
        disposal.refresh_from_db()
        asset.refresh_from_db()
        self.assertIsNone(disposal.disposal_date)
        self.assertFalse(disposal.is_completed)
        self.assertNotEqual(asset.status, "disposed")

    def test_it_support_cannot_create_approved_disposal(self):
        asset = Asset.objects.create(
            asset_tag="DSP-4", name="printer", category=self.acat)
        auth(self.c, self.support)
        res = self.c.post("/api/assets/disposals/", {
            "asset": asset.pk, "disposal_reason": "end of life",
            "disposal_method": "recycled",
            "approval_status": "approved"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Disposal.objects.filter(asset=asset).exists())

    def test_disposal_cannot_be_created_completed(self):
        asset = Asset.objects.create(
            asset_tag="DSP-5", name="printer", category=self.acat)
        auth(self.c, self.mgr)
        res = self.c.post("/api/assets/disposals/", {
            "asset": asset.pk, "disposal_reason": "end of life",
            "disposal_method": "recycled",
            "disposal_date": timezone.now().isoformat()}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Disposal.objects.filter(asset=asset).exists())
        asset.refresh_from_db()
        self.assertNotEqual(asset.status, "disposed")

    def test_manager_can_still_approve_disposal_via_update(self):
        asset = Asset.objects.create(
            asset_tag="DSP-3", name="printer", category=self.acat)
        disposal = Disposal.objects.create(
            asset=asset, disposal_reason="end of life",
            disposal_method="recycled", approval_status="pending",
            created_by=self.mgr)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/assets/disposals/{disposal.pk}/",
                           {"approval_status": "approved"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        disposal.refresh_from_db()
        self.assertEqual(disposal.approval_status, "approved")
        self.assertEqual(disposal.approver_id, self.mgr.pk)


class DisposalWorkflowConsistencyTests(TestCase):
    """Generic PATCH must produce the same decision trail as the actions.

    PATCH approval is an existing API contract (integration_tests.py uses it),
    so it stays supported; it must nevertheless match approve()/reject() for
    approver metadata, asset history, audit, notifications, and validation.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")

    def _make(self, tag, **extra):
        asset = Asset.objects.create(
            asset_tag=tag, name="old laptop", category=self.acat)
        return Disposal.objects.create(
            asset=asset, disposal_reason="end of life",
            disposal_method="recycled", responsible_person=self.emp,
            created_by=self.mgr, **extra)

    def test_patch_approval_matches_approve_action(self):
        patched = self._make("CMP-1")
        actioned = self._make("CMP-2")
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/assets/disposals/{patched.pk}/",
                           {"approval_status": "approved"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        res = self.c.post(f"/api/assets/disposals/{actioned.pk}/approve/")
        self.assertEqual(res.status_code, 200, res.data)
        for d in (patched, actioned):
            d.refresh_from_db()
            self.assertEqual(d.approval_status, "approved")
            self.assertEqual(d.approver_id, self.mgr.pk)
            self.assertIsNotNone(d.approved_at)
            self.assertTrue(d.asset.history.filter(action="approved").exists())
            self.assertTrue(AuditLog.objects.filter(
                entity_type="assets.disposal", object_id=str(d.pk),
                action="approve").exists())
            self.assertTrue(Notification.objects.filter(
                recipient=self.emp, object_id=str(d.pk)).exists())
        # A decision recorded through PATCH is not a generic "update".
        self.assertFalse(AuditLog.objects.filter(
            entity_type="assets.disposal", object_id=str(patched.pk),
            action="update").exists())

    def test_patch_rejection_matches_reject_action(self):
        patched = self._make("CMP-3")
        actioned = self._make("CMP-4")
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/assets/disposals/{patched.pk}/",
                           {"approval_status": "rejected"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        res = self.c.post(f"/api/assets/disposals/{actioned.pk}/reject/")
        self.assertEqual(res.status_code, 200, res.data)
        for d in (patched, actioned):
            d.refresh_from_db()
            self.assertEqual(d.approval_status, "rejected")
            self.assertEqual(d.approver_id, self.mgr.pk)
            self.assertIsNone(d.approved_at)
            self.assertTrue(d.asset.history.filter(action="rejected").exists())
            self.assertTrue(AuditLog.objects.filter(
                entity_type="assets.disposal", object_id=str(d.pk),
                action="reject").exists())

    def test_patch_cannot_rewrite_completed_decision(self):
        d = self._make("CMP-5", approval_status="approved",
                       approver=self.mgr, disposal_date=timezone.now())
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/assets/disposals/{d.pk}/",
                           {"approval_status": "rejected"}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        d.refresh_from_db()
        self.assertEqual(d.approval_status, "approved")
        self.assertTrue(d.is_completed)

    def test_patch_back_to_pending_clears_approval_metadata(self):
        d = self._make("CMP-6", approval_status="approved",
                       approver=self.mgr, approved_at=timezone.now())
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/assets/disposals/{d.pk}/",
                           {"approval_status": "pending"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        d.refresh_from_db()
        self.assertEqual(d.approval_status, "pending")
        self.assertIsNone(d.approver_id)
        self.assertIsNone(d.approved_at)
        self.assertTrue(d.asset.history.filter(action="pending").exists())

    def test_cannot_repoint_approved_disposal_to_another_asset(self):
        d = self._make("CMP-7", approval_status="approved",
                       approver=self.mgr)
        other = Asset.objects.create(
            asset_tag="CMP-8", name="other", category=self.acat)
        original_asset_id = d.asset_id
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/assets/disposals/{d.pk}/",
                           {"asset": other.pk}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        d.refresh_from_db()
        self.assertEqual(d.asset_id, original_asset_id)
        self.assertNotEqual(d.asset_id, other.pk)
        # Editing the asset while the disposal is still pending is allowed.
        pending = self._make("CMP-9")
        res = self.c.patch(f"/api/assets/disposals/{pending.pk}/",
                           {"asset": other.pk}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def test_manager_created_approved_disposal_records_decision_trail(self):
        asset = Asset.objects.create(
            asset_tag="CMP-10", name="old laptop", category=self.acat)
        auth(self.c, self.mgr)
        res = self.c.post("/api/assets/disposals/", {
            "asset": asset.pk, "disposal_reason": "end of life",
            "disposal_method": "recycled",
            "approval_status": "approved"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        d = Disposal.objects.get(pk=res.data["id"])
        self.assertEqual(d.approver_id, self.mgr.pk)
        self.assertIsNotNone(d.approved_at)
        self.assertTrue(d.asset.history.filter(action="approved").exists())
        self.assertTrue(AuditLog.objects.filter(
            entity_type="assets.disposal", object_id=str(d.pk),
            action="approve").exists())


class AssetAssignmentConcurrencyTests(TransactionTestCase):
    """Genuine concurrent assignment/return/retire/disposal tests.

    Each worker runs on its own database connection (Django connections are
    thread-local) and workers start simultaneously via a threading.Barrier.
    SQLite serializes all writers with a database-wide lock, so these tests
    only prove row-lock correctness on PostgreSQL; on SQLite they exercise
    the same code paths but cannot expose true concurrent write races.
    """

    reset_sequences = True

    def setUp(self):
        from django.db import connections
        if connections['default'].vendor == 'sqlite':
            raise SkipTest('SQLite does not support concurrent writes via ThreadPoolExecutor; requires PostgreSQL for reliable verification.')
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)

    def _open_count(self, asset):
        return Assignment.objects.filter(
            asset=asset, returned_at__isnull=True).count()

    def _run_concurrent(self, fn_a, fn_b, barrier_timeout=10):
        """Run two API functions concurrently, synchronized at start.

        Each function receives a fresh authenticated APIClient. Returns
        the two HTTP status codes (sorted).
        """
        results = {}
        barrier = threading.Barrier(2, timeout=barrier_timeout)

        def worker(fn, client, key):
            try:
                barrier.wait()
                res = fn(client)
                results[key] = res.status_code
            except Exception as exc:  # noqa: BLE001
                results[key] = f"EXC:{type(exc).__name__}:{exc}"

        client_a = APIClient()
        auth(client_a, self.mgr)
        client_b = APIClient()
        auth(client_b, self.mgr)

        t1 = threading.Thread(target=worker, args=(fn_a, client_a, "a"))
        t2 = threading.Thread(target=worker, args=(fn_b, client_b, "b"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        return sorted(v for v in results.values() if isinstance(v, int)), results

    def test_concurrent_assign_same_asset(self):
        """Two simultaneous assigns to same asset: exactly one succeeds."""
        asset = Asset.objects.create(
            asset_tag="CONC-1", name="conc1", category=self.acat)

        codes, results = self._run_concurrent(
            lambda c: c.post(f"/api/assets/{asset.pk}/assign/",
                             {"assigned_to": self.emp.pk, "note": "c"},
                             format="json"),
            lambda c: c.post(f"/api/assets/{asset.pk}/assign/",
                             {"assigned_to": self.e2.pk, "note": "c"},
                             format="json"))

        self.assertEqual(
            codes, [200, 400],
            f"Expected one 200 and one 400, got {codes}: {results}")
        asset.refresh_from_db()
        self.assertEqual(self._open_count(asset), 1)
        self.assertIsNotNone(asset.assigned_to_id)
        self.assertEqual(asset.status, "assigned")

    def test_concurrent_assign_and_return(self):
        """Simultaneous return and re-assign: serialized, at most one open."""
        asset = Asset.objects.create(
            asset_tag="CONC-2", name="conc2", category=self.acat,
            status="assigned", assigned_to=self.emp)

        codes, results = self._run_concurrent(
            lambda c: c.post(f"/api/assets/{asset.pk}/return_asset/",
                             {}, format="json"),
            lambda c: c.post(f"/api/assets/{asset.pk}/assign/",
                             {"assigned_to": self.e2.pk, "note": "c"},
                             format="json"))

        self.assertEqual(len(codes), 2,
                         f"Both workers should complete, got {codes}: {results}")
        asset.refresh_from_db()
        # At most one open assignment; if assigned, holder agrees.
        self.assertLessEqual(self._open_count(asset), 1)
        if asset.assigned_to_id:
            self.assertEqual(asset.status, "assigned")
            open_a = Assignment.objects.filter(
                asset=asset, returned_at__isnull=True).first()
            self.assertIsNotNone(open_a)
            self.assertEqual(open_a.assigned_to_id, asset.assigned_to_id)
        else:
            self.assertEqual(asset.status, "available")

    def test_concurrent_assign_and_bulk_assign(self):
        """Simultaneous single assign and bulk assign on same asset."""
        asset = Asset.objects.create(
            asset_tag="CONC-3", name="conc3", category=self.acat)

        codes, results = self._run_concurrent(
            lambda c: c.post(f"/api/assets/{asset.pk}/assign/",
                             {"assigned_to": self.emp.pk, "note": "c"},
                             format="json"),
            lambda c: c.post("/api/assets/bulk_assign/",
                             {"assignments": [
                                 {"asset_tag": asset.asset_tag,
                                  "employee_id": self.e2.employee_id}],
                              "preview": False, "confirm": True},
                             format="json"))

        self.assertEqual(len(codes), 2,
                         f"Both workers should complete, got {codes}: {results}")
        asset.refresh_from_db()
        self.assertLessEqual(self._open_count(asset), 1)

    def test_concurrent_assign_and_retire(self):
        """Simultaneous assign and retire: at most one open assignment."""
        asset = Asset.objects.create(
            asset_tag="CONC-4", name="conc4", category=self.acat)

        codes, results = self._run_concurrent(
            lambda c: c.post(f"/api/assets/{asset.pk}/assign/",
                             {"assigned_to": self.emp.pk, "note": "c"},
                             format="json"),
            lambda c: c.post(f"/api/assets/{asset.pk}/retire/", {},
                             format="json"))

        self.assertEqual(len(codes), 2,
                         f"Both workers should complete, got {codes}: {results}")
        asset.refresh_from_db()
        self.assertLessEqual(self._open_count(asset), 1)
        # Asset status must agree with assignment state.
        if self._open_count(asset) == 1:
            self.assertEqual(asset.status, "assigned")
            self.assertIsNotNone(asset.assigned_to_id)
        else:
            self.assertIn(asset.status, ("available", "retired"))
            self.assertIsNone(asset.assigned_to_id)

    def test_concurrent_assign_and_complete_disposal(self):
        """Simultaneous assign and disposal completion: at most one open."""
        asset = Asset.objects.create(
            asset_tag="CONC-5", name="conc5", category=self.acat)
        disposal = Disposal.objects.create(
            asset=asset, disposal_reason="end of life",
            disposal_method="recycled", responsible_person=self.emp,
            created_by=self.mgr, approval_status="approved",
            approver=self.mgr)

        codes, results = self._run_concurrent(
            lambda c: c.post(f"/api/assets/{asset.pk}/assign/",
                             {"assigned_to": self.emp.pk, "note": "c"},
                             format="json"),
            lambda c: c.post(
                f"/api/assets/disposals/{disposal.pk}/complete/", {},
                format="json"))

        self.assertEqual(len(codes), 2,
                         f"Both workers should complete, got {codes}: {results}")
        asset.refresh_from_db()
        self.assertLessEqual(self._open_count(asset), 1)
        # Asset status must agree with assignment state.
        if self._open_count(asset) == 1:
            self.assertEqual(asset.status, "assigned")
            self.assertIsNotNone(asset.assigned_to_id)
        else:
            self.assertIn(asset.status, ("available", "disposed"))
            self.assertIsNone(asset.assigned_to_id)


