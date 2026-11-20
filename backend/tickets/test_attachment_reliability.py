"""Phase D regression tests: attachment storage reliability + history.

The upload path must never leave a physical file behind when the database
write (row, history, or audit) fails. These tests force a failure *after*
the storage write so the cleanup claim is actually exercised, and they
check that files belonging to other records survive untouched.

They also pin the ticket-history contract for attachments: add/remove are
recorded in the ticket timeline in the same transaction as the mutation,
with metadata only (no storage paths or file content).
"""
import os
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from common.models import AuditLog
from tickets.attachment_storage import delete_stored_file, store_upload
from tickets.models import (
    Ticket, TicketAttachment, TicketCategory, TicketHistory,
)


class AttachmentReliabilityBase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="General")
        self.ticket = Ticket.objects.create(
            title="Printer down", description="d", category=self.tcat,
            requester=self.emp, department=self.dep, status="open",
            priority="medium")
        # Isolated media root so assertions about "files on disk" are exact.
        self.media_root = tempfile.mkdtemp(prefix="ticket-attach-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        auth(self.c, self.mgr)

    # ---- helpers -----------------------------------------------------
    def _upload(self, name="report.txt", content=b"hello"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile(name, content, content_type="text/plain")
        return self.c.post(
            "/api/tickets/attachments/",
            {"ticket": self.ticket.pk, "file": up},
            format="multipart",
        )

    def _replace(self, attachment_id, name="new.txt", content=b"new"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile(name, content, content_type="text/plain")
        return self.c.patch(
            f"/api/tickets/attachments/{attachment_id}/",
            {"file": up},
            format="multipart",
        )

    def _stored(self):
        """Map of stored basename -> bytes currently present in storage."""
        base = os.path.join(self.media_root, "ticket_attachments")
        if not os.path.isdir(base):
            return {}
        stored = {}
        for name in os.listdir(base):
            with open(os.path.join(base, name), "rb") as fh:
                stored[name] = fh.read()
        return stored

    def _disk_path(self, storage_name):
        return os.path.join(self.media_root, storage_name)

    def _write_sentinel(self, name="sentinel.txt", content=b"keep me"):
        """A file that predates the failing upload."""
        base = os.path.join(self.media_root, "ticket_attachments")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, name), "wb") as fh:
            fh.write(content)
        return f"ticket_attachments/{name}"


class SuccessfulUploadTests(AttachmentReliabilityBase):
    def test_upload_writes_one_file_row_history_and_audit(self):
        res = self._upload()
        self.assertEqual(res.status_code, 201, res.data)
        att = TicketAttachment.objects.get(pk=res.data["id"])
        self.assertTrue(att.file.name.startswith("ticket_attachments/"))
        self.assertEqual(att.original_filename, "report.txt")
        self.assertEqual(att.uploaded_by, self.mgr)
        self.assertEqual(self._stored(),
                         {os.path.basename(att.file.name): b"hello"})

        hist = TicketHistory.objects.get(
            ticket=self.ticket, action="attachment_added")
        self.assertEqual(hist.actor, self.mgr)
        self.assertEqual(hist.new_values["attachment_id"], att.pk)
        self.assertEqual(hist.new_values["filename"], "report.txt")
        self.assertEqual(hist.new_values["size"], 5)
        # Metadata only: no storage path may leak into the timeline.
        self.assertNotIn("ticket_attachments/", str(hist.new_values))
        self.assertTrue(AuditLog.objects.filter(
            entity_type="tickets.ticketattachment",
            object_id=str(att.pk), action="create").exists())

    def test_download_still_serves_the_stored_file(self):
        att_id = self._upload(content=b"payload").data["id"]
        dl = self.c.get(f"/api/tickets/attachments/{att_id}/download/")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(b"".join(dl.streaming_content), b"payload")
        dl.close()


class FailedUploadCleanupTests(AttachmentReliabilityBase):
    def test_database_failure_after_storage_write_removes_only_new_file(self):
        sentinel = self._write_sentinel()
        before = self._stored()
        self.assertIn("sentinel.txt", before)

        # Failure point is *after* the physical file was written: the
        # attachment row is inserted, then the audit write fails and the
        # transaction rolls back.
        with patch("tickets.views.log_action",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self._upload()

        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(
            TicketHistory.objects.filter(action="attachment_added").count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        self.assertEqual(self._stored(), before)  # sentinel intact, no orphan
        self.assertTrue(os.path.exists(self._disk_path(sentinel)))

    def test_model_create_failure_after_storage_write_removes_new_file(self):
        before = self._stored()
        with patch.object(TicketAttachment.objects, "create",
                          side_effect=IntegrityError("db down")):
            with self.assertRaises(IntegrityError):
                self._upload()

        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), before)
        self.assertFalse(TicketHistory.objects.filter(
            action="attachment_added").exists())

    def test_storage_write_failure_creates_no_row_and_no_file(self):
        with patch.object(FileSystemStorage, "save",
                          side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self._upload()

        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), {})
        self.assertFalse(TicketHistory.objects.filter(
            action="attachment_added").exists())

    def test_failed_upload_keeps_existing_attachment_downloadable(self):
        first_id = self._upload(name="first.txt", content=b"first").data["id"]
        first = TicketAttachment.objects.get(pk=first_id)
        stored_name = first.file.name

        with patch("tickets.views.log_action",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self._upload(name="second.txt", content=b"second")

        first.refresh_from_db()
        self.assertEqual(first.file.name, stored_name)
        self.assertEqual(self._stored(),
                         {os.path.basename(stored_name): b"first"})
        dl = self.c.get(f"/api/tickets/attachments/{first_id}/download/")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(b"".join(dl.streaming_content), b"first")
        dl.close()

    def test_failed_replacement_keeps_old_file_and_cleans_new_one(self):
        att_id = self._upload(name="keep.txt", content=b"old").data["id"]
        att = TicketAttachment.objects.get(pk=att_id)
        old_name = att.file.name

        with patch("tickets.views.log_action",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self._replace(att_id)

        att.refresh_from_db()
        self.assertEqual(att.file.name, old_name)
        self.assertEqual(self._stored(),
                         {os.path.basename(old_name): b"old"})
        self.assertFalse(TicketHistory.objects.filter(
            action="attachment_updated").exists())


class CleanupHelperTests(AttachmentReliabilityBase):
    def test_cleanup_is_idempotent_and_tolerates_missing_files(self):
        name = store_upload(TicketAttachment,
                            ContentFile(b"x", name="orphan.txt"))
        self.assertTrue(name)
        self.assertTrue(os.path.exists(self._disk_path(name)))

        self.assertTrue(delete_stored_file(TicketAttachment, name))
        self.assertFalse(os.path.exists(self._disk_path(name)))
        # Repeated cleanup (retry, double error path) must not raise.
        self.assertTrue(delete_stored_file(TicketAttachment, name))
        self.assertFalse(delete_stored_file(TicketAttachment, None))
        self.assertFalse(delete_stored_file(TicketAttachment, ""))

    def test_cleanup_never_touches_an_unrelated_file(self):
        self._write_sentinel("unrelated.txt", b"untouched")
        name = store_upload(TicketAttachment,
                            ContentFile(b"y", name="mine.txt"))
        delete_stored_file(TicketAttachment, name)
        self.assertEqual(self._stored(), {"unrelated.txt": b"untouched"})


class AttachmentDeleteHistoryTests(AttachmentReliabilityBase):
    def test_delete_soft_deletes_and_records_history_with_actor(self):
        att_id = self._upload().data["id"]

        res = self.c.delete(f"/api/tickets/attachments/{att_id}/")
        self.assertEqual(res.status_code, 204)

        att = TicketAttachment.all_objects.get(pk=att_id)
        self.assertTrue(att.is_deleted)
        self.assertEqual(att.deleted_by, self.mgr)

        hist = TicketHistory.objects.get(
            ticket=self.ticket, action="attachment_removed")
        self.assertEqual(hist.actor, self.mgr)
        self.assertEqual(hist.old_values["attachment_id"], att_id)
        self.assertEqual(hist.old_values["filename"], "report.txt")
        self.assertNotIn("ticket_attachments/", str(hist.old_values))
        # Exactly one add + one remove: no duplicate timeline entries.
        self.assertEqual(TicketHistory.objects.filter(
            ticket=self.ticket,
            action__in=["attachment_added", "attachment_removed"]).count(), 2)

        # Soft delete keeps the physical file (existing retention rule).
        self.assertEqual(len(self._stored()), 1)

    def test_failed_delete_rolls_back_row_and_writes_no_history(self):
        att_id = self._upload().data["id"]

        with patch("tickets.views.log_action",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.c.delete(f"/api/tickets/attachments/{att_id}/")

        att = TicketAttachment.objects.get(pk=att_id)  # still live
        self.assertFalse(att.is_deleted)
        self.assertFalse(TicketHistory.objects.filter(
            action="attachment_removed").exists())
        self.assertEqual(TicketHistory.objects.filter(
            action="attachment_added").count(), 1)
        self.assertEqual(len(self._stored()), 1)
