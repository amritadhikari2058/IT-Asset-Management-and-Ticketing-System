"""Asset API tests: bulk safety (assignment guard), bulk assignment."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
)
from common.models import AuditLog


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
                          "serial_number", "status", "location",
                          "purchase_date"])

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
                                          category=self.acat)
        auth(self.c, self.mgr)

    def tearDown(self):
        # Test-DB rows only; never real user uploads.
        for att in AssetAttachment.all_objects.all():
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
        dl.close()

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
        dl.close()
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
