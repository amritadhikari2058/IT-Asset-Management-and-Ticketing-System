"""Asset attachment filename contract + cross-asset IDOR regression tests.

The asset attachment API previously omitted ``original_filename`` even though
the model stores it. These tests pin the contract and verify that filters,
ownership and download headers behave safely.
"""
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import _make_user, auth, make_users
from assets.models import Asset, AssetAttachment, AssetCategory
from common.attachment_security import safe_original_filename

LIST_URL = "/api/assets/attachments/"


def rows(res):
    data = res.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


class AssetAttachmentContractBase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.other_dep = Department.objects.create(name="HR", code="HR1")
        self.outsider = _make_user("E3", "e3@x", "e3@x", "employee",
                                   self.other_dep)
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.asset_mine = Asset.objects.create(
            asset_tag="A-1", name="Laptop 1", category=self.cat,
            department=self.dep, status="assigned", assigned_to=self.emp)
        self.asset_other = Asset.objects.create(
            asset_tag="A-2", name="Laptop 2", category=self.cat,
            department=self.other_dep, status="assigned",
            assigned_to=self.outsider)
        self.media_root = tempfile.mkdtemp(prefix="asset-attach-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.c = APIClient()


class AssetAttachmentFilenameContractTests(AssetAttachmentContractBase):
    def test_upload_response_exposes_original_filename(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("Quarterly Report (final).pdf",
                                b"%PDF-1.4", content_type="application/pdf")
        res = self.c.post(LIST_URL, {"asset": self.asset_mine.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        self.assertEqual(res.data["original_filename"],
                         "Quarterly Report (final).pdf")
        self.assertTrue(AssetAttachment.objects.filter(
            pk=res.data["id"], original_filename="Quarterly Report (final).pdf")
            .exists())

    def test_list_and_detail_include_original_filename(self):
        att = AssetAttachment.objects.create(
            asset=self.asset_mine, file=SimpleUploadedFile(
                "notes.txt", b"hi", content_type="text/plain"),
            uploaded_by=self.mgr, original_filename="notes.txt")
        auth(self.c, self.mgr)
        res = self.c.get(LIST_URL, {"asset": self.asset_mine.pk})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(rows(res)[0]["original_filename"], "notes.txt")
        detail = self.c.get(f"{LIST_URL}{att.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["original_filename"], "notes.txt")

    def test_download_suggests_original_filename(self):
        att = AssetAttachment.objects.create(
            asset=self.asset_mine, file=SimpleUploadedFile(
                "report.txt", b"hi", content_type="text/plain"),
            uploaded_by=self.mgr, original_filename="Report 2024 (draft).txt")
        auth(self.c, self.mgr)
        res = self.c.get(f"{LIST_URL}{att.pk}/download/")
        self.assertEqual(res.status_code, 200)
        self.assertIn('filename="Report 2024 (draft).txt"',
                      res["Content-Disposition"])
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")

    def test_legacy_blank_filename_returns_blank_and_falls_back(self):
        att = AssetAttachment.objects.create(
            asset=self.asset_mine, file=SimpleUploadedFile(
                "legacy.bin", b"hi", content_type="application/octet-stream"),
            uploaded_by=self.mgr, original_filename="")
        auth(self.c, self.mgr)
        res = self.c.get(f"{LIST_URL}{att.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["original_filename"], "")
        download = self.c.get(f"{LIST_URL}{att.pk}/download/")
        self.assertEqual(download.status_code, 200)
        # falls back to the stored file's basename; never a path
        header = download["Content-Disposition"]
        self.assertNotIn("/", header)
        self.assertNotIn("\\", header)

    def test_path_components_and_control_chars_are_stripped(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("evil.txt", b"x", content_type="text/plain")
        up.name = "..\\..\\evil.txt"
        res = self.c.post(LIST_URL, {"asset": self.asset_mine.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        self.assertEqual(res.data["original_filename"], "evil.txt")

        # Direct legacy value with traversal/control chars: stored verbatim
        # but the download header is sanitised.
        att = AssetAttachment.objects.create(
            asset=self.asset_mine, file=SimpleUploadedFile(
                "x.txt", b"x", content_type="text/plain"),
            uploaded_by=self.mgr,
            original_filename="../../etc/pa\r\nsswd.txt")
        download = self.c.get(f"{LIST_URL}{att.pk}/download/")
        self.assertEqual(download.status_code, 200)
        header = download["Content-Disposition"]
        self.assertNotIn("..", header)
        self.assertNotIn("/", header)
        self.assertNotIn("\\", header)
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)

    def test_unicode_and_multiple_dots_preserved(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("résumé.v2.final.txt",
                                b"x", content_type="text/plain")
        res = self.c.post(LIST_URL, {"asset": self.asset_mine.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        self.assertEqual(res.data["original_filename"],
                         "résumé.v2.final.txt")

    def test_create_ignores_client_supplied_owner_and_filename(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("real.txt", b"x", content_type="text/plain")
        res = self.c.post(
            LIST_URL,
            {"asset": self.asset_mine.pk, "file": up,
             "original_filename": "forged.exe",
             "uploaded_by": self.outsider.pk},
            format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        created = AssetAttachment.objects.get(pk=res.data["id"])
        self.assertEqual(created.original_filename, "real.txt")
        self.assertEqual(created.uploaded_by_id, self.mgr.pk)


class AssetAttachmentFilterTests(AssetAttachmentContractBase):
    def setUp(self):
        super().setUp()
        self.att_mine = AssetAttachment.objects.create(
            asset=self.asset_mine,
            file=SimpleUploadedFile("mine.txt", b"mine", content_type="text/plain"),
            uploaded_by=self.mgr, original_filename="mine.txt")
        self.att_other = AssetAttachment.objects.create(
            asset=self.asset_other,
            file=SimpleUploadedFile("other.txt", b"other", content_type="text/plain"),
            uploaded_by=self.mgr, original_filename="other.txt")

    def test_filter_scopes_to_requested_asset(self):
        auth(self.c, self.mgr)
        res = self.c.get(LIST_URL, {"asset": self.asset_mine.pk})
        self.assertEqual({r["id"] for r in rows(res)}, {self.att_mine.pk})
        res2 = self.c.get(LIST_URL, {"asset": self.asset_other.pk})
        self.assertEqual({r["id"] for r in rows(res2)}, {self.att_other.pk})

    def test_malformed_asset_id_returns_empty_not_error(self):
        auth(self.c, self.mgr)
        for raw in ("abc", "1.5", "-1", "0", "99999999"):
            with self.subTest(raw=raw):
                res = self.c.get(LIST_URL, {"asset": raw})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(rows(res), [])

    def test_employee_cannot_list_other_department_asset_attachments(self):
        auth(self.c, self.emp)
        res = self.c.get(LIST_URL, {"asset": self.asset_other.pk})
        self.assertEqual(rows(res), [])
        direct = self.c.get(f"{LIST_URL}{self.att_other.pk}/")
        self.assertEqual(direct.status_code, 404)
        download = self.c.get(f"{LIST_URL}{self.att_other.pk}/download/")
        self.assertEqual(download.status_code, 404)


class AssetAttachmentAuthorizationTests(AssetAttachmentContractBase):
    def test_employee_cannot_upload_asset_attachment(self):
        auth(self.c, self.emp)
        up = SimpleUploadedFile("x.txt", b"x", content_type="text/plain")
        res = self.c.post(LIST_URL, {"asset": self.asset_mine.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(AssetAttachment.objects.filter(
            asset=self.asset_mine, original_filename="x.txt").exists())

    def test_employee_cannot_delete_asset_attachment(self):
        att = AssetAttachment.objects.create(
            asset=self.asset_mine,
            file=SimpleUploadedFile("d.txt", b"d", content_type="text/plain"),
            uploaded_by=self.mgr, original_filename="d.txt")
        auth(self.c, self.emp)
        res = self.c.delete(f"{LIST_URL}{att.pk}/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(AssetAttachment.objects.filter(pk=att.pk).exists())


class SafeOriginalFilenameUnitTests(TestCase):
    def test_none_and_empty_return_blank(self):
        self.assertEqual(safe_original_filename(None), "")
        self.assertEqual(safe_original_filename(""), "")

    def test_strips_both_separators_and_control_chars(self):
        self.assertEqual(safe_original_filename("..\\..\\x.txt"), "x.txt")
        self.assertEqual(safe_original_filename("../../x.txt"), "x.txt")
        self.assertEqual(safe_original_filename("a\x00b\nc.txt"), "abc.txt")
        self.assertEqual(safe_original_filename("  spaced  "), "spaced")

    def test_preserves_spaces_dots_unicode_and_caps_length(self):
        self.assertEqual(safe_original_filename("a.b.c d"), "a.b.c d")
        self.assertEqual(safe_original_filename("résumé.txt"), "résumé.txt")
        long_name = "x" * 300 + ".txt"
        self.assertEqual(len(safe_original_filename(long_name)), 255)
