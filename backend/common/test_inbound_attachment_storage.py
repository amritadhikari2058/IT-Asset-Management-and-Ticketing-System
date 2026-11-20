"""Phase E regression tests: email-ingested attachment storage reliability.

These drive ``common.inbound.process_inbound_email`` with real MIME messages
(parsed by ``build_inbound_message``), so the production ingestion path is
exercised end to end -- attachment policy, ticket creation, the
``EmailProcessing`` bookkeeping and the physical storage write.

The invariant under test: once the file has been written to storage, a
database failure must leave neither a row nor an orphaned file behind, and
cleanup may only ever touch the object created by the failing call -- never
an existing attachment's file and never another message's file.
"""
import os
import shutil
import tempfile
from email.message import EmailMessage
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError
from django.test import TestCase, override_settings

from common import inbound
from common.models import EmailProcessing
from tickets.models import Ticket, TicketAttachment

#: Sender domain is allowed, so ``user@example.com`` is eligible without a
#: pre-existing user account (mirrors the parser test settings).
_SETTINGS = {
    "INBOUND_ALLOWED_SENDER_DOMAINS": "example.com",
    "ATTACHMENT_MAX_SIZE_MB": 10,
    "ATTACHMENT_ALLOWED_EXTENSIONS": "pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx",
}


def _message(attachments=(), body="Printer is broken",
             message_id="<inbound-attach@example.com>",
             subject="Printer broken"):
    """Build a real MIME message; ``attachments`` is (name, bytes, ctype)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "user@example.com"
    msg["To"] = "support@example.com"
    msg["Message-ID"] = message_id
    msg.set_content(body)
    for name, data, ctype in attachments:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=name)
    return msg


class InboundAttachmentBase(TestCase):
    def setUp(self):
        # Isolated media root so "files on disk" assertions are exact and the
        # shared media directory is never touched.
        self.media_root = tempfile.mkdtemp(prefix="inbound-attach-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        override = override_settings(MEDIA_ROOT=self.media_root, **_SETTINGS)
        override.enable()
        self.addCleanup(override.disable)

    # ---- helpers -----------------------------------------------------
    def _ingest(self, attachments=(), message_id="<inbound-attach@example.com>",
                subject="Printer broken"):
        msg = _message(attachments=attachments, message_id=message_id,
                       subject=subject)
        return inbound.process_inbound_email(inbound.build_inbound_message(msg))

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

    def _attachment_dir(self):
        return os.path.join(self.media_root, "ticket_attachments")


class SuccessfulIngestionTests(InboundAttachmentBase):
    def test_attachment_row_and_stored_object_created(self):
        ticket, created, error = self._ingest(
            attachments=[("logs.txt", b"line one", "text/plain")])
        self.assertIsNotNone(ticket)
        self.assertTrue(created)
        self.assertIsNone(error)

        att = TicketAttachment.objects.get()
        self.assertEqual(att.ticket_id, ticket.pk)
        self.assertEqual(att.original_filename, "logs.txt")
        # Existing inbound behaviour: no actor is recorded for email uploads.
        self.assertIsNone(att.uploaded_by)
        # Stored name comes from the model's upload_to (uuid + extension).
        self.assertTrue(att.file.name.startswith("ticket_attachments/"))
        self.assertTrue(att.file.name.endswith(".txt"))
        self.assertNotIn("logs", os.path.basename(att.file.name))

        self.assertIn(att.file.name, [f"ticket_attachments/{n}"
                                      for n in self._stored()])
        self.assertEqual(self._stored(),
                         {os.path.basename(att.file.name): b"line one"})

    def test_multiple_attachments_get_distinct_stored_objects(self):
        ticket, _created, error = self._ingest(attachments=[
            ("one.txt", b"first", "text/plain"),
            ("two.csv", b"second", "text/csv"),
        ])
        self.assertIsNone(error)
        atts = list(TicketAttachment.objects.filter(ticket=ticket))
        self.assertEqual(len(atts), 2)
        names = {att.file.name for att in atts}
        self.assertEqual(len(names), 2)
        self.assertEqual(
            {att.original_filename for att in atts}, {"one.txt", "two.csv"})
        self.assertEqual(
            sorted(self._stored().values()), [b"first", b"second"])

    def test_attachment_ingestion_marks_email_processed(self):
        self._ingest(attachments=[("ok.pdf", b"%PDF", "application/pdf")])
        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertIsNotNone(proc.ticket_id)
        self.assertIsNotNone(proc.processed_at)
        self.assertEqual(proc.error_details, "")

    def test_email_without_attachments_unchanged(self):
        ticket, created, error = self._ingest()
        self.assertTrue(created)
        self.assertIsNone(error)
        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), {})
        self.assertEqual(EmailProcessing.objects.get().status, "processed")

    def test_traversal_filename_stays_inside_attachment_dir(self):
        _ticket, _created, error = self._ingest(
            attachments=[("../../../etc/passwd.txt", b"nope", "text/plain")])
        self.assertIsNone(error)
        att = TicketAttachment.objects.get()
        self.assertTrue(att.file.name.startswith("ticket_attachments/"))
        self.assertNotIn("..", att.file.name)
        self.assertTrue(os.path.isfile(
            os.path.join(self.media_root, att.file.name)))
        # Nothing escaped the sandbox media root.
        self.assertFalse(os.path.exists(
            os.path.join(self.media_root, "..", "etc", "passwd.txt")))


class FailureCleanupTests(InboundAttachmentBase):
    def test_database_failure_after_storage_write_removes_new_file(self):
        """Non-vacuity: the file must exist *before* the simulated DB failure."""
        seen = {}

        def failing_save(_self, *args, **kwargs):
            seen["files"] = dict(self._stored())
            raise IntegrityError("db write failed")

        with patch.object(TicketAttachment, "save", failing_save):
            ticket, created, error = self._ingest(
                attachments=[("data.txt", b"payload", "text/plain")])

        self.assertTrue(
            seen.get("files"),
            "storage write must happen before the DB failure is simulated")
        self.assertEqual(list(seen["files"].values()), [b"payload"])
        # Original exception surfaces through the existing error path.
        self.assertIsNone(ticket)
        self.assertFalse(created)
        self.assertTrue(error.startswith("IntegrityError:"), error)
        # No row and no orphaned object remain.
        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), {})
        self.assertEqual(
            EmailProcessing.objects.get().status, "failed")

    def test_model_creation_failure_removes_new_file(self):
        seen = {}

        def failing_create(*args, **kwargs):
            seen["files"] = dict(self._stored())
            raise ValueError("could not build attachment row")

        with patch.object(TicketAttachment.objects, "create",
                          side_effect=failing_create):
            _ticket, _created, error = self._ingest(
                attachments=[("data.txt", b"payload", "text/plain")])

        self.assertTrue(seen.get("files"))
        self.assertTrue(error.startswith("ValueError:"), error)
        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), {})
        self.assertEqual(EmailProcessing.objects.get().status, "failed")

    def test_storage_write_failure_leaves_no_partial_state(self):
        with patch.object(FileSystemStorage, "save",
                          side_effect=OSError("disk full")):
            _ticket, _created, error = self._ingest(
                attachments=[("data.txt", b"payload", "text/plain")])

        self.assertTrue(error.startswith("OSError:"), error)
        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), {})
        self.assertEqual(EmailProcessing.objects.get().status, "failed")

    def test_cleanup_failure_does_not_replace_original_exception(self):
        def failing_save(_self, *args, **kwargs):
            raise IntegrityError("db write failed")

        with patch.object(TicketAttachment, "save", failing_save), \
                patch.object(FileSystemStorage, "delete",
                             side_effect=OSError("storage unreachable")):
            _ticket, _created, error = self._ingest(
                attachments=[("data.txt", b"payload", "text/plain")])

        # The database error is reported, not the cleanup error.
        self.assertTrue(error.startswith("IntegrityError:"), error)
        self.assertNotIn("storage unreachable", error)
        self.assertEqual(TicketAttachment.objects.count(), 0)
        # Best effort: an unreachable backend cannot delete, so the file
        # stays behind -- the documented limitation, not a silent success.
        self.assertEqual(list(self._stored().values()), [b"payload"])

    def test_later_attachment_failure_keeps_earlier_attachment_intact(self):
        calls = {"n": 0}
        original_save = TicketAttachment.save

        def fail_second(instance, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise IntegrityError("second row failed")
            return original_save(instance, *args, **kwargs)

        with patch.object(TicketAttachment, "save", fail_second):
            _ticket, _created, error = self._ingest(attachments=[
                ("first.txt", b"keep me", "text/plain"),
                ("second.txt", b"drop me", "text/plain"),
            ])

        self.assertTrue(error.startswith("IntegrityError:"), error)
        # The first attachment committed on its own (inbound processing is not
        # wrapped in an outer transaction), so its row and file stay paired.
        self.assertEqual(TicketAttachment.objects.count(), 1)
        att = TicketAttachment.objects.get()
        self.assertEqual(att.original_filename, "first.txt")
        self.assertEqual(self._stored(),
                         {os.path.basename(att.file.name): b"keep me"})
        self.assertEqual(EmailProcessing.objects.get().status, "failed")

    def test_failed_ingestion_does_not_delete_existing_attachment_file(self):
        ticket, _created, _error = self._ingest(
            message_id="<first@example.com>",
            attachments=[("report.txt", b"original", "text/plain")])
        existing = TicketAttachment.objects.get()
        existing_name = existing.file.name

        def failing_save(_self, *args, **kwargs):
            raise IntegrityError("db write failed")

        with patch.object(TicketAttachment, "save", failing_save):
            _ticket, _created, error = self._ingest(
                message_id="<second@example.com>",
                attachments=[("report.txt", b"replacement", "text/plain")])

        self.assertTrue(error.startswith("IntegrityError:"), error)
        self.assertEqual(TicketAttachment.objects.count(), 1)
        self.assertTrue(FileSystemStorage().exists(existing_name))
        self.assertEqual(self._stored(),
                         {os.path.basename(existing_name): b"original"})
        self.assertEqual(existing.ticket_id, ticket.pk)

    def test_similar_filenames_from_separate_emails_keep_own_files(self):
        _t1, _c1, e1 = self._ingest(
            message_id="<a@example.com>",
            attachments=[("report.txt", b"first body", "text/plain")])
        _t2, _c2, e2 = self._ingest(
            message_id="<b@example.com>",
            attachments=[("report.txt", b"second body", "text/plain")])
        self.assertIsNone(e1)
        self.assertIsNone(e2)

        atts = list(TicketAttachment.objects.order_by("pk"))
        self.assertEqual(len(atts), 2)
        self.assertNotEqual(atts[0].file.name, atts[1].file.name)
        self.assertEqual(self._stored(), {
            os.path.basename(atts[0].file.name): b"first body",
            os.path.basename(atts[1].file.name): b"second body",
        })

        # A later failing message with the same filename leaves both alone.
        def failing_save(_self, *args, **kwargs):
            raise IntegrityError("db write failed")

        with patch.object(TicketAttachment, "save", failing_save):
            self._ingest(message_id="<c@example.com>",
                         attachments=[("report.txt", b"third", "text/plain")])

        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(self._stored(), {
            os.path.basename(atts[0].file.name): b"first body",
            os.path.basename(atts[1].file.name): b"second body",
        })


class IdempotencyAndValidationTests(InboundAttachmentBase):
    def test_reprocessing_same_message_does_not_duplicate_attachments(self):
        first, created_first, _err = self._ingest(
            attachments=[("report.txt", b"body", "text/plain")])
        second, created_second, error = self._ingest(
            attachments=[("report.txt", b"body", "text/plain")])

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertIsNone(error)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TicketAttachment.objects.count(), 1)
        self.assertEqual(len(self._stored()), 1)

    def test_blocked_extension_behaviour_preserved(self):
        ticket, created, error = self._ingest(
            attachments=[("evil.exe", b"MZ", "application/x-msdownload")])

        self.assertIsNone(ticket)
        self.assertFalse(created)
        self.assertIn("not allowed", error)
        # Rejected before any ticket or attachment row exists.
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(TicketAttachment.objects.count(), 0)
        self.assertEqual(self._stored(), {})
        proc = EmailProcessing.objects.get()
        self.assertEqual(proc.status, "failed")
        self.assertIn("Unsupported attachment", proc.error_details)

    def test_empty_attachment_still_creates_its_row_and_object(self):
        _ticket, _created, error = self._ingest(
            attachments=[("empty.txt", b"", "text/plain")])
        self.assertIsNone(error)
        att = TicketAttachment.objects.get()
        self.assertEqual(self._stored(),
                         {os.path.basename(att.file.name): b""})
