"""Attachment list filtering + cross-ticket IDOR regression tests.

Covers the confirmed defect where ``GET /api/tickets/attachments/?ticket=<id>``
ignored the filter and returned every attachment the caller could see (and,
before the visibility scope existed, every attachment in the system).

The invariant under test: an attachment is listed/retrieved/downloaded only
when its *ticket* is visible to the caller, and ``?ticket=`` can only narrow
that set — never widen it or leak other tickets' files.
"""
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import _make_user, auth, make_users
from tickets.models import Ticket, TicketAttachment, TicketCategory

LIST_URL = "/api/tickets/attachments/"


def rows(res):
    """Return the list of records from a (possibly paginated) response."""
    data = res.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


class AttachmentFilterBase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        # Same-department colleague (sees home-department tickets) …
        self.colleague = _make_user("E2", "e2@x", "e2@x", "employee", self.dep)
        # … and an employee in a different department (must see nothing).
        self.other_dep = Department.objects.create(name="HR", code="HR1")
        self.outsider = _make_user("E3", "e3@x", "e3@x", "employee",
                                   self.other_dep)
        self.cat = TicketCategory.objects.create(name="General")

        self.t_mine = self._ticket("Mine", "Printer", self.emp, self.dep)
        self.t_colleague = self._ticket("Colleague", "VPN", self.colleague,
                                        self.dep)
        self.t_secret = self._ticket("Secret", "Payroll", self.outsider,
                                     self.other_dep)

        self.media_root = tempfile.mkdtemp(prefix="ticket-attach-idor-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)

        self.a_mine = self._attachment(self.t_mine, "mine-only.txt", b"mine")
        self.a_colleague = self._attachment(
            self.t_colleague, "colleague-only.txt", b"colleague")
        self.a_secret = self._attachment(
            self.t_secret, "secret-payroll.txt", b"secret")

        self.c = APIClient()

    def _ticket(self, title, description, requester, department):
        return Ticket.objects.create(
            title=title, description=description, category=self.cat,
            requester=requester, department=department, status="open",
            priority="medium")

    def _attachment(self, ticket, name, content):
        up = SimpleUploadedFile(name, content, content_type="text/plain")
        return TicketAttachment.objects.create(
            ticket=ticket, file=up, original_filename=name,
            uploaded_by=self.mgr)

    def _ids(self, res):
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        return {row["id"] for row in rows(res)}

    def _files_on_disk(self):
        found = []
        for root, _dirs, files in os.walk(self.media_root):
            found.extend(os.path.join(root, f) for f in files)
        return found


class TicketAttachmentFilterTests(AttachmentFilterBase):
    def test_filter_returns_only_that_tickets_attachments(self):
        auth(self.c, self.admin)
        res = self.c.get(LIST_URL, {"ticket": self.t_mine.pk})
        self.assertEqual(self._ids(res), {self.a_mine.pk})
        body = res.content.decode()
        self.assertIn("mine-only.txt", body)
        self.assertNotIn("colleague-only.txt", body)
        self.assertNotIn("secret-payroll.txt", body)

    def test_filter_returns_each_ticket_independently(self):
        auth(self.c, self.admin)
        self.assertEqual(
            self._ids(self.c.get(LIST_URL, {"ticket": self.t_colleague.pk})),
            {self.a_colleague.pk})
        self.assertEqual(
            self._ids(self.c.get(LIST_URL, {"ticket": self.t_secret.pk})),
            {self.a_secret.pk})

    def test_unfiltered_list_keeps_staff_operational_scope(self):
        auth(self.c, self.admin)
        self.assertEqual(self._ids(self.c.get(LIST_URL)),
                         {self.a_mine.pk, self.a_colleague.pk,
                          self.a_secret.pk})

    def test_employee_unfiltered_list_is_ticket_visibility_scoped(self):
        # Employees see their own tickets + home-department tickets, so the
        # colleague's (same-department) ticket is visible by policy; the
        # other department's ticket is not.
        auth(self.c, self.emp)
        self.assertEqual(self._ids(self.c.get(LIST_URL)),
                         {self.a_mine.pk, self.a_colleague.pk})

    def test_employee_cannot_list_other_departments_ticket_attachments(self):
        auth(self.c, self.emp)
        res = self.c.get(LIST_URL, {"ticket": self.t_secret.pk})
        self.assertEqual(self._ids(res), set())
        self.assertNotIn("secret-payroll.txt", res.content.decode())

    def test_employee_cannot_retrieve_or_download_foreign_attachment(self):
        auth(self.c, self.emp)
        detail = self.c.get(f"{LIST_URL}{self.a_secret.pk}/")
        self.assertEqual(detail.status_code, 404)
        download = self.c.get(f"{LIST_URL}{self.a_secret.pk}/download/")
        self.assertEqual(download.status_code, 404)

    def test_filter_cannot_widen_scope_via_known_ticket_id(self):
        auth(self.c, self.emp)
        # Naming a visible ticket alongside the secret one must not union.
        res = self.c.get(f"{LIST_URL}?ticket={self.t_mine.pk}"
                         f"&ticket={self.t_secret.pk}")
        self.assertEqual(self._ids(res), set())
        self.assertNotIn("secret-payroll.txt", res.content.decode())

    def test_malformed_and_unknown_ids_are_empty_not_errors(self):
        auth(self.c, self.admin)
        for raw in ("abc", "1.5", "-1", "0", "  ", "99999999",
                    "1 or 1=1", "%00"):
            with self.subTest(raw=raw):
                res = self.c.get(LIST_URL, {"ticket": raw})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(self._ids(res), set())

    def test_soft_deleted_attachment_is_not_listed(self):
        auth(self.c, self.admin)
        self.a_mine.soft_delete(by_user=self.admin, reason="removed")
        self.assertEqual(
            self._ids(self.c.get(LIST_URL, {"ticket": self.t_mine.pk})),
            set())

    def test_unauthenticated_and_inactive_users_are_denied(self):
        anon = APIClient()
        res = anon.get(LIST_URL, {"ticket": self.t_mine.pk})
        self.assertIn(res.status_code, (401, 403))

        auth(self.c, self.emp)
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        res = self.c.get(LIST_URL, {"ticket": self.t_mine.pk})
        self.assertIn(res.status_code, (401, 403))


class TicketAttachmentMutationTests(AttachmentFilterBase):
    def test_upload_to_inaccessible_ticket_is_denied_without_storage_write(self):
        before = self._files_on_disk()
        auth(self.c, self.emp)
        up = SimpleUploadedFile("leak.txt", b"nope", content_type="text/plain")
        res = self.c.post(LIST_URL,
                          {"ticket": self.t_secret.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(
            TicketAttachment.objects.filter(
                ticket=self.t_secret, original_filename="leak.txt").exists())
        self.assertEqual(self._files_on_disk(), before)

    def test_denied_delete_leaves_row_and_file_untouched(self):
        auth(self.c, self.emp)  # employees cannot delete attachments
        stored = self.a_mine.file.name
        res = self.c.delete(f"{LIST_URL}{self.a_mine.pk}/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(
            TicketAttachment.objects.filter(pk=self.a_mine.pk).exists())
        self.assertTrue(os.path.exists(
            os.path.join(self.media_root, stored)))

    def test_update_cannot_rebind_ticket_or_relabel_file(self):
        auth(self.c, self.mgr)
        res = self.c.patch(
            f"{LIST_URL}{self.a_mine.pk}/",
            {"ticket": self.t_secret.pk, "original_filename": "renamed.exe"},
            format="json")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.a_mine.refresh_from_db()
        self.assertEqual(self.a_mine.ticket_id, self.t_mine.pk)
        self.assertEqual(self.a_mine.original_filename, "mine-only.txt")

    def test_create_ignores_client_supplied_filename_and_owner(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("real.txt", b"data", content_type="text/plain")
        res = self.c.post(
            LIST_URL,
            {"ticket": self.t_mine.pk, "file": up,
             "original_filename": "forged.exe",
             "uploaded_by": self.outsider.pk},
            format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        created = TicketAttachment.objects.get(pk=res.data["id"])
        self.assertEqual(created.original_filename, "real.txt")
        self.assertEqual(created.uploaded_by_id, self.mgr.pk)

    def test_ticket_upload_and_download_use_original_filename(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("Quarterly Report (final).txt", b"report",
                                content_type="text/plain")
        res = self.c.post(LIST_URL, {"ticket": self.t_mine.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        self.assertEqual(res.data["original_filename"],
                         "Quarterly Report (final).txt")

        download = self.c.get(f"{LIST_URL}{res.data['id']}/download/")
        self.assertEqual(download.status_code, 200)
        self.assertIn('filename="Quarterly Report (final).txt"',
                      download["Content-Disposition"])
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")


class TicketAttachmentFilenameSecurityTests(AttachmentFilterBase):
    def test_path_components_are_stripped_from_stored_name(self):
        auth(self.c, self.mgr)
        up = SimpleUploadedFile("evil.txt", b"x", content_type="text/plain")
        # Simulate a client that supplied a traversal path (Django strips the
        # host-OS separator only; the shared helper strips both).
        up.name = "..\\..\\windows\\evil.txt"
        res = self.c.post(LIST_URL, {"ticket": self.t_mine.pk, "file": up},
                          format="multipart")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        name = res.data["original_filename"]
        self.assertEqual(name, "evil.txt")
        self.assertNotIn("\\", name)
        self.assertNotIn("/", name)

    def test_download_header_sanitises_legacy_traversal_name(self):
        # Legacy/ingested rows may hold an unsanitised value: the download
        # header must still never carry a path or CRLF.
        self.a_mine.original_filename = "../../etc/pa\r\nsswd.txt"
        self.a_mine.save(update_fields=["original_filename"])
        auth(self.c, self.mgr)
        res = self.c.get(f"{LIST_URL}{self.a_mine.pk}/download/")
        self.assertEqual(res.status_code, 200)
        header = res["Content-Disposition"]
        self.assertNotIn("..", header)
        self.assertNotIn("/", header)
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
