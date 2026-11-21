"""Focused regression tests for the asset bulk-import (bulk_create) endpoint.

Exercises the real `/api/assets/bulk_create/` endpoint and validation path:
preview, confirm, CSV/XLSX upload parsing, authorization, normalization,
duplicate detection, soft-deleted conflicts, per-row outcomes, and rollback
behavior. These tests are specific to asset bulk import and do not cover
ticket bulk import, reports, ordinary asset creation, or unrelated features.
"""
import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory


def _csv_upload(rows, fieldnames=None, name="assets.csv"):
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else ["asset_tag", "name", "category"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(name, buf.getvalue().encode("utf-8"), content_type="text/csv")


def _xlsx_upload(rows, header, name="assets.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append([row.get(h, "") for h in header])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return SimpleUploadedFile(
        name, out.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class AssetBulkImportBase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.cat2 = AssetCategory.objects.create(name="Monitor")
        auth(self.c, self.mgr)

    def post_json(self, payload, query=""):
        return self.c.post(f"/api/assets/bulk_create/{query}", payload, format="json")

    def post_file(self, upload, extra=None, query=""):
        data = {"file": upload}
        if extra:
            data.update(extra)
        return self.c.post(f"/api/assets/bulk_create/{query}", data, format="multipart")


class AssetBulkImportValidAndPreviewTests(AssetBulkImportBase):
    def test_valid_multi_row_json_import_preview_and_confirm(self):
        rows = [
            {"asset_tag": "IMP-1", "name": "One", "category": "Laptop", "status": "available"},
            {"asset_tag": "IMP-2", "name": "Two", "category": "Monitor", "status": "in_repair"},
        ]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual([r["asset_tag"] for r in preview.data["preview"]], ["IMP-1", "IMP-2"])
        self.assertEqual(preview.data["errors"], [])
        self.assertEqual(Asset.objects.filter(asset_tag__in=["IMP-1", "IMP-2"]).count(), 0)

        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.data["successful"], ["IMP-1", "IMP-2"])
        self.assertEqual(confirm.data["skipped"], [])
        self.assertEqual(confirm.data["failed"], [])
        a1 = Asset.objects.get(asset_tag="IMP-1")
        a2 = Asset.objects.get(asset_tag="IMP-2")
        self.assertEqual(a1.category, self.cat)
        self.assertEqual(a2.category, self.cat2)
        self.assertEqual(a1.status, "available")
        self.assertEqual(a2.status, "in_repair")
        self.assertIsNone(a1.assigned_to)
        self.assertIsNone(a2.assigned_to)

    def test_confirm_requires_explicit_confirmation(self):
        res = self.post_json({"rows": [{"asset_tag": "NC1", "name": "N", "category": "Laptop"}],
                              "preview": False})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Asset.objects.filter(asset_tag="NC1").exists())

    def test_optional_fields_and_blank_serials_allowed(self):
        rows = [
            {"asset_tag": "OPT-1", "name": "One", "category": "Laptop", "serial_number": "",
             "location": "", "description": ""},
            {"asset_tag": "OPT-2", "name": "Two", "category": "Laptop"},
        ]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(res.data["successful"]), ["OPT-1", "OPT-2"])
        self.assertEqual(res.data["failed"], [])
        self.assertEqual(Asset.objects.get(asset_tag="OPT-1").serial_number, "")
        self.assertEqual(Asset.objects.get(asset_tag="OPT-2").serial_number, "")


class AssetBulkImportValidationTests(AssetBulkImportBase):
    def test_missing_required_asset_tag(self):
        res = self.post_json({"rows": [{"name": "NoTag", "category": "Laptop"}], "preview": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["preview"], [])
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("asset_tag required", res.data["errors"][0]["errors"])

    def test_missing_required_category(self):
        res = self.post_json({"rows": [{"asset_tag": "NCAT", "name": "N"}], "preview": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("category required", res.data["errors"][0]["errors"])

    def test_unknown_category_case_sensitive(self):
        # Category matching is intentionally case-sensitive.
        rows = [{"asset_tag": "CASE-CAT", "name": "N", "category": "laptop"}]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(any("unknown category" in e["errors"] for e in preview.data["errors"]))
        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.data["successful"], [])
        self.assertEqual(len(confirm.data["failed"]), 1)
        self.assertIn("unknown category", confirm.data["failed"][0]["errors"])

    def test_unknown_status_rejected(self):
        rows = [{"asset_tag": "BADSTAT", "name": "N", "category": "Laptop", "status": "broken"}]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertTrue(any("unknown status" in e["errors"] for e in preview.data["errors"]))
        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.data["successful"], [])
        self.assertIn("unknown status", confirm.data["failed"][0]["errors"])

    def test_status_assigned_rejected_in_import(self):
        rows = [{"asset_tag": "ASG1", "name": "N", "category": "Laptop", "status": "assigned"}]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertTrue(any("cannot be imported" in e["errors"] for e in preview.data["errors"]))
        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.data["successful"], [])
        self.assertIn("cannot be imported", confirm.data["failed"][0]["errors"])

    def test_invalid_field_value_invalid_date_reported_per_row(self):
        rows = [
            {"asset_tag": "DATE1", "name": "Bad", "category": "Laptop", "purchase_date": "not-a-date"},
            {"asset_tag": "DATE2", "name": "Good", "category": "Laptop"},
        ]
        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.status_code, 200)
        self.assertIn("DATE2", confirm.data["successful"])
        self.assertTrue(any(f["asset_tag"] == "DATE1" for f in confirm.data["failed"]))
        self.assertFalse(Asset.objects.filter(asset_tag="DATE1").exists())
        self.assertTrue(Asset.objects.filter(asset_tag="DATE2").exists())

    def test_whitespace_normalization_and_csv_header_whitespace(self):
        # CSV headers with whitespace should be normalized; values trimmed.
        def make_upload():
            return SimpleUploadedFile(
                "ws.csv",
                b" asset_tag , name , category , status , serial_number \n"
                b" WS-1 , Spaced Name , Laptop , AVAILABLE ,  SN-WS  \n",
                content_type="text/csv")
        preview = self.post_file(make_upload(), {"preview": "true"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual([r["asset_tag"] for r in preview.data["preview"]], ["WS-1"])
        self.assertEqual(preview.data["errors"], [])
        confirm = self.post_file(make_upload(), {"preview": "false", "confirm": "true"})
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.data["successful"], ["WS-1"])
        asset = Asset.objects.get(asset_tag="WS-1")
        self.assertEqual(asset.name, "Spaced Name")
        self.assertEqual(asset.category, self.cat)
        self.assertEqual(asset.status, "available")
        self.assertEqual(asset.serial_number, "SN-WS")

    def test_whitespace_in_category_value_preserved_case_sensitive_match(self):
        # Leading/trailing whitespace in category value is trimmed, but case remains exact.
        rows = [{"asset_tag": "CATWS", "name": "N", "category": " Laptop "}]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["CATWS"])
        self.assertEqual(Asset.objects.get(asset_tag="CATWS").category, self.cat)

    def test_invalid_foreign_key_reference_department_ignored(self):
        # Nonexistent department reference is not assigned (current behavior).
        rows = [{"asset_tag": "NODEPT", "name": "N", "category": "Laptop", "department": "NO-SUCH-DEPT"}]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["NODEPT"])
        self.assertIsNone(Asset.objects.get(asset_tag="NODEPT").department)

    def test_valid_department_resolved_by_code_name_and_pk(self):
        dept = Department.objects.create(name="Engineering", code="ENG")
        rows = [
            {"asset_tag": "D1", "name": "N", "category": "Laptop", "department": "ENG"},
            {"asset_tag": "D2", "name": "N", "category": "Laptop", "department": "Engineering"},
            {"asset_tag": "D3", "name": "N", "category": "Laptop", "department": str(dept.pk)},
        ]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(sorted(res.data["successful"]), ["D1", "D2", "D3"])
        self.assertEqual(Asset.objects.get(asset_tag="D1").department, dept)
        self.assertEqual(Asset.objects.get(asset_tag="D2").department, dept)
        self.assertEqual(Asset.objects.get(asset_tag="D3").department, dept)


class AssetBulkImportDuplicateAndConflictTests(AssetBulkImportBase):
    def test_duplicate_serial_within_upload_preview_and_confirm(self):
        rows = [
            {"asset_tag": "DUPA", "name": "A", "category": "Laptop", "serial_number": "SN-DUP"},
            {"asset_tag": "DUPB", "name": "B", "category": "Laptop", "serial_number": "SN-DUP"},
        ]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertEqual([r["asset_tag"] for r in preview.data["preview"]], ["DUPA"])
        self.assertTrue(any("duplicate serial number SN-DUP" in e["errors"] for e in preview.data["errors"]))
        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.data["successful"], ["DUPA"])
        self.assertTrue(any("duplicate serial number SN-DUP" in f["errors"] for f in confirm.data["failed"]))
        self.assertEqual(Asset.all_objects.filter(serial_number="SN-DUP").count(), 1)

    def test_duplicate_tag_within_upload_preview(self):
        rows = [
            {"asset_tag": "SAME", "name": "A", "category": "Laptop"},
            {"asset_tag": "SAME", "name": "B", "category": "Laptop"},
        ]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertEqual([r["asset_tag"] for r in preview.data["preview"]], ["SAME"])
        self.assertTrue(any("duplicate tag SAME" in e["errors"] for e in preview.data["errors"]))

    def test_duplicate_tag_and_serial_already_in_database(self):
        Asset.objects.create(asset_tag="EXIST", name="Old", category=self.cat, serial_number="SN-EXIST")
        rows = [
            {"asset_tag": "EXIST", "name": "New", "category": "Laptop"},
            {"asset_tag": "NEW1", "name": "New1", "category": "Laptop", "serial_number": "SN-EXIST"},
        ]
        preview = self.post_json({"rows": rows, "preview": True})
        self.assertEqual(preview.data["preview"], [])
        msgs = " | ".join(e["errors"] for e in preview.data["errors"])
        self.assertIn("duplicate tag EXIST", msgs)
        self.assertIn("duplicate serial number SN-EXIST", msgs)

    def test_soft_deleted_asset_conflicts_detected(self):
        soft = Asset.objects.create(asset_tag="SOFT", name="Soft", category=self.cat, serial_number="SN-SOFT")
        soft.soft_delete(by_user=self.mgr, reason="test")
        self.assertTrue(Asset.all_objects.filter(asset_tag="SOFT", is_deleted=True).exists())
        rows = [
            {"asset_tag": "SOFT", "name": "New", "category": "Laptop"},
            {"asset_tag": "NEWSN", "name": "New", "category": "Laptop", "serial_number": "SN-SOFT"},
        ]
        preview = self.post_json({"rows": rows, "preview": True})
        msgs = " | ".join(e["errors"] for e in preview.data["errors"])
        self.assertIn("duplicate tag SOFT", msgs)
        self.assertIn("duplicate serial number SN-SOFT", msgs)
        confirm = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(confirm.data["successful"], [])
        # Tag conflict results in skip (exists; use bulk_update), serial conflict in failed.
        self.assertTrue(any(s.get("asset_tag") == "SOFT" for s in confirm.data["skipped"]))
        self.assertTrue(any(f.get("asset_tag") == "NEWSN" for f in confirm.data["failed"]))

    def test_repeated_submission_does_not_create_duplicates(self):
        rows = [
            {"asset_tag": "REP1", "name": "One", "category": "Laptop", "serial_number": "SN-REP1"},
            {"asset_tag": "REP2", "name": "Two", "category": "Laptop"},
        ]
        first = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(sorted(first.data["successful"]), ["REP1", "REP2"])
        second = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(second.data["successful"], [])
        self.assertEqual(sorted([s["asset_tag"] for s in second.data["skipped"]]), ["REP1", "REP2"])
        self.assertEqual(Asset.all_objects.filter(asset_tag__in=["REP1", "REP2"]).count(), 2)


class AssetBulkImportFileParsingTests(AssetBulkImportBase):
    def test_xlsx_upload_valid_import(self):
        header = ["asset_tag", "name", "category", "serial_number"]
        rows = [{"asset_tag": "X1", "name": "X One", "category": "Laptop", "serial_number": "SNX1"}]
        preview = self.post_file(_xlsx_upload(rows, header), {"preview": "true"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual([r["asset_tag"] for r in preview.data["preview"]], ["X1"])
        confirm = self.post_file(_xlsx_upload(rows, header), {"preview": "false", "confirm": "true"})
        self.assertEqual(confirm.data["successful"], ["X1"])
        self.assertTrue(Asset.objects.filter(asset_tag="X1", serial_number="SNX1").exists())

    def test_xlsx_blank_rows_skipped(self):
        upload = _xlsx_upload(
            [
                {"asset_tag": "XBL1", "name": "One", "category": "Laptop"},
                {"asset_tag": "", "name": "", "category": ""},
                {"asset_tag": "XBL2", "name": "Two", "category": "Laptop"},
            ],
            ["asset_tag", "name", "category"],
        )
        confirm = self.post_file(upload, {"preview": "false", "confirm": "true"})
        self.assertEqual(sorted(confirm.data["successful"]), ["XBL1", "XBL2"])
        self.assertEqual(confirm.data["failed"], [])

    def test_csv_blank_rows_do_not_create_assets(self):
        upload = SimpleUploadedFile(
            "blankrows.csv",
            b"asset_tag,name,category\nBL1,One,Laptop\n,,\nBL2,Two,Laptop\n",
            content_type="text/csv")
        confirm = self.post_file(upload, {"preview": "false", "confirm": "true"})
        self.assertEqual(sorted(confirm.data["successful"]), ["BL1", "BL2"])
        self.assertFalse(Asset.objects.filter(asset_tag="").exists())

    def test_missing_columns_unknown_column_reported(self):
        upload = _csv_upload([{"asset_tag": "A", "name": "N", "category": "Laptop", "nope": "x"}],
                             fieldnames=["asset_tag", "name", "category", "nope"])
        res = self.post_file(upload, {"preview": "true"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertIn("unknown columns", str(res.data["file"]))

    def test_missing_or_incorrectly_named_columns_reported(self):
        # Entirely unrecognized columns are reported clearly.
        upload = SimpleUploadedFile("badhead.csv", b"foo,bar\n1,2\n", content_type="text/csv")
        res = self.post_file(upload, {"preview": "true"})
        self.assertEqual(res.status_code, 400)
        msg = str(res.data["file"]).lower()
        self.assertTrue("unknown columns" in msg or "header" in msg)

    def test_unsupported_or_malformed_file_rejected_cleanly(self):
        for name, content in [
            ("data.bin", b"\xff\xfe\x00\x01junk\x00\xff"),
            ("assets.xlsx", b"this is not a zip archive"),
            ("empty.csv", b""),
        ]:
            res = self.post_file(SimpleUploadedFile(name, content, content_type="application/octet-stream"),
                                 {"preview": "true"})
            self.assertEqual(res.status_code, 400, name)
            self.assertIn("file", res.data, name)
            body = res.content.decode("utf-8", "replace")
            self.assertNotIn("Traceback", body)
            self.assertNotIn(".py", body)


class AssetBulkImportAuthorizationAndOutcomeTests(AssetBulkImportBase):
    def test_unauthenticated_rejected(self):
        self.c.force_authenticate(user=None)
        res = self.post_json({"rows": [{"asset_tag": "U1", "name": "N", "category": "Laptop"}],
                              "preview": True})
        self.assertIn(res.status_code, (401, 403))

    def test_employee_without_admin_permission_rejected(self):
        auth(self.c, self.emp)
        res = self.post_json({"rows": [{"asset_tag": "E1", "name": "N", "category": "Laptop"}],
                              "preview": True})
        self.assertEqual(res.status_code, 403)
        res2 = self.post_json({"rows": [{"asset_tag": "E1", "name": "N", "category": "Laptop"}],
                               "preview": False, "confirm": True})
        self.assertEqual(res2.status_code, 403)

    def test_partial_success_partial_failure_per_row_rollback(self):
        # Row-level atomic: valid row persists, invalid rows in same request do not.
        rows = [
            {"asset_tag": "OK1", "name": "Good", "category": "Laptop"},
            {"asset_tag": "BADCAT", "name": "Bad", "category": "NoSuch"},
            {"asset_tag": "OK2", "name": "Good2", "category": "Laptop", "purchase_date": "bad-date"},
            {"asset_tag": "OK3", "name": "Good3", "category": "Laptop"},
        ]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(res.data["successful"]), ["OK1", "OK3"])
        failed_tags = {f.get("asset_tag") for f in res.data["failed"]}
        self.assertEqual(failed_tags, {"BADCAT", "OK2"})
        self.assertTrue(Asset.objects.filter(asset_tag="OK1").exists())
        self.assertTrue(Asset.objects.filter(asset_tag="OK3").exists())
        self.assertFalse(Asset.objects.filter(asset_tag="BADCAT").exists())
        self.assertFalse(Asset.objects.filter(asset_tag="OK2").exists())

    def test_per_row_error_reporting_includes_row_and_key(self):
        Asset.objects.create(asset_tag="EX", name="Old", category=self.cat)
        rows = [
            {"asset_tag": "EX", "name": "Dup", "category": "Laptop"},  # skip
            {"asset_tag": "MISS", "name": "NoCat", "category": "Missing"},  # fail
        ]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(len(res.data["skipped"]), 1)
        self.assertEqual(res.data["skipped"][0]["row"], 2)
        self.assertEqual(res.data["skipped"][0]["asset_tag"], "EX")
        self.assertEqual(len(res.data["failed"]), 1)
        self.assertEqual(res.data["failed"][0]["row"], 3)
        self.assertEqual(res.data["failed"][0]["asset_tag"], "MISS")
        self.assertIn("unknown category", res.data["failed"][0]["errors"])

    def test_system_admin_can_bulk_import(self):
        auth(self.c, self.admin)
        rows = [{"asset_tag": "ADM1", "name": "Admin", "category": "Laptop"}]
        res = self.post_json({"rows": rows, "preview": False, "confirm": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["successful"], ["ADM1"])
        self.assertTrue(Asset.objects.filter(asset_tag="ADM1").exists())
