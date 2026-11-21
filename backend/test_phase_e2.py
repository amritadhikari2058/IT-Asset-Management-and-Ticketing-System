"""Phase E.2 regression tests: attachment identity and ticket reuse."""

import os
import shutil
import tempfile

from email.message import EmailMessage

from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError
from django.test import TestCase, override_settings
from unittest.mock import patch

from common import inbound
from common.models import EmailProcessing
from tickets.models import Ticket, TicketAttachment
from tickets.attachment_storage import store_upload, delete_stored_file


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


def _ingest(attachments, message_id="<inbound-attach@example.com>",
            subject="Printer broken"):
    msg = _message(attachments=attachments, message_id=message_id,
                   subject=subject)
    return inbound.process_inbound_email(inbound.build_inbound_message(msg))


class PhaseE2Tests(TestCase):
    """Phase E.2: attachment identity and ticket reuse tests."""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="phase-e2-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(
            MEDIA_ROOT=self.media_root,
            **_SETTINGS)
        self.override.enable()
        self.addCleanup(self.override.disable)

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

    def _is_integrity_error(self, error):
        """Check if error string starts with 'IntegrityError'."""
        return (isinstance(error, str) and
                error.startswith("IntegrityError:"))

    def test_attachment_same_filename_different_content(self):
        """Two attachments with the same filename but different contents in one email.

        Both attachments must be preserved; deduplication should use content hash,
        not just filename.
        """
        attachments = [
            ("report.pdf", b"January data content", "application/pdf"),
            ("report.pdf", b"February data content", "application/pdf"),
        ]

        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        self.assertIsNotNone(ticket)

        # Both attachments should be stored
        self.assertEqual(TicketAttachment.objects.count(), 2,
                         f"Expected 2 attachments, got {TicketAttachment.objects.count()}")

        # Get both attachments
        atts = list(TicketAttachment.objects.filter(ticket=ticket).order_by("pk"))
        self.assertEqual(len(atts), 2)

        # They should have different content hashes
        self.assertNotEqual(atts[0].content_hash, atts[1].content_hash)

        # They should have the same original filename but different content
        self.assertEqual(atts[0].original_filename, atts[1].original_filename)
        self.assertNotEqual(atts[0].file.name, atts[1].file.name)  # different stored names

        # Both should be in storage
        self.assertEqual(len(self._stored()), 2)

    def test_attachment_same_filename_identical_content(self):
        """Two separate MIME parts with same filename and identical contents.

        Distinct MIME attachment parts must remain separate records even when
        filename and bytes are identical.
        """
        attachments = [
            ("report.pdf", b"same data", "application/pdf"),
            ("report.pdf", b"same data", "application/pdf"),
        ]

        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        self.assertIsNotNone(ticket)

        self.assertEqual(TicketAttachment.objects.count(), 2,
                         f"Expected 2 distinct parts, got {TicketAttachment.objects.count()}")

        atts = list(TicketAttachment.objects.filter(ticket=ticket).order_by("pk"))
        self.assertEqual({a.original_filename for a in atts}, {"report.pdf"})
        self.assertEqual(atts[0].content_hash, atts[1].content_hash)
        self.assertNotEqual(atts[0].source_part_index, atts[1].source_part_index)
        self.assertEqual(len(self._stored()), 2)

    def test_partial_failure_retry_workflow(self):
        """Partial failure on 3rd attachment recovers to exactly 3 parts on one ticket."""
        attachments = [
            ("att1.txt", b"content1", "text/plain"),
            ("att2.txt", b"content2", "text/plain"),
            ("att3.txt", b"content3", "text/plain"),
        ]

        call_count = [0]
        original_create = TicketAttachment.objects.create

        def failing_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:
                raise IntegrityError("simulated db failure on 3rd attachment")
            return original_create(*args, **kwargs)

        with patch.object(TicketAttachment.objects, "create", failing_create):
            _ticket, _created, error = _ingest(attachments)

        self.assertIsNotNone(error)
        self.assertTrue(self._is_integrity_error(error))
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(Ticket.objects.count(), 1)
        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        ticket_id = proc.ticket_id
        self.assertEqual(proc.status, "failed")
        self.assertIsNotNone(ticket_id)
        self.assertEqual(
            sorted(self._stored().values()), [b"content1", b"content2"])

        ticket2, created2, error2 = _ingest(attachments)

        self.assertIsNone(error2)
        self.assertFalse(created2)
        self.assertEqual(ticket2.pk, ticket_id)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(
            sorted(self._stored().values()),
            [b"content1", b"content2", b"content3"])
        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertIsNotNone(proc.processed_at)

    def test_partial_failure_retry_no_crash(self):
        """Retry after partial failure completes successfully without duplicates."""
        attachments = [
            ("att1.txt", b"content1", "text/plain"),
            ("att2.txt", b"content2", "text/plain"),
            ("att3.txt", b"content3", "text/plain"),
        ]

        call_count = [0]
        original_create = TicketAttachment.objects.create

        def failing_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:
                raise IntegrityError("simulated db failure")
            return original_create(*args, **kwargs)

        with patch.object(TicketAttachment.objects, "create", failing_create):
            _ticket, _created, error = _ingest(attachments)

        self.assertIsNotNone(error)
        ticket_id = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>").ticket_id
        self.assertIsNotNone(ticket_id)

        ticket2, created2, error2 = _ingest(attachments)
        self.assertIsNone(error2)
        self.assertIsNotNone(ticket2)
        self.assertEqual(ticket2.pk, ticket_id)
        self.assertFalse(created2)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)

    def test_ticket_reuse_no_duplicate_tickets(self):
        """Multiple retries should not create duplicate tickets.

        The same email should always reference the same ticket.
        """
        attachments = [
            ("report.pdf", b"data", "application/pdf"),
        ]

        # First processing
        ticket1, created1, error1 = _ingest(attachments)
        self.assertIsNone(error1)
        self.assertIsNotNone(ticket1)

        # Second processing (replay) - should reuse same ticket
        ticket2, created2, error2 = _ingest(attachments)
        self.assertIsNone(error2)
        self.assertIsNotNone(ticket2)
        self.assertEqual(ticket1.pk, ticket2.pk,
                         "Replay should reuse the same ticket, not create a new one")

        # Third processing
        ticket3, created3, error3 = _ingest(attachments)
        self.assertIsNone(error3)
        self.assertEqual(ticket1.pk, ticket3.pk,
                         "Third replay should also reuse the same ticket")

    def test_attachment_dedup_on_retry(self):
        """Deduplication should work correctly on retry after partial failure.

        The same attachment (same filename + same content) should not be
        duplicated on retry.
        """
        attachments = [
            ("report.pdf", b"persistent data", "application/pdf"),
            ("summary.pdf", b"summary data", "application/pdf"),
        ]

        # First attempt: both succeed
        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        self.assertEqual(TicketAttachment.objects.count(), 2)

        # Get the content hash of the first attachment
        att1_hash = TicketAttachment.objects.get(
            original_filename="report.pdf").content_hash

        # Reset EmailProcessing to failed (simulating partial failure scenario)
        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        EmailProcessing.objects.filter(pk=proc.pk).update(status="failed")

        # Retry the same email
        ticket2, created2, error2 = _ingest(attachments)
        self.assertIsNone(error2)

        # Deduplication should prevent a new row for the same content
        self.assertEqual(TicketAttachment.objects.count(), 2,
                         f"Expected 2 attachments (deduplicated), got {TicketAttachment.objects.count()}")

        # The content hash should be the same
        att1 = TicketAttachment.objects.get(original_filename="report.pdf")
        self.assertEqual(att1.content_hash, att1_hash)

    def test_attachment_same_filename_different_content_retry(self):
        """Two attachments with same filename but different contents, followed by retry.

        Both attachments from the first attempt should be preserved, and the
        retry should not duplicate them.
        """
        attachments = [
            ("report.pdf", b"January data", "application/pdf"),
            ("report.pdf", b"February data", "application/pdf"),
            ("summary.pdf", b"Summary data", "application/pdf"),
        ]

        # First attempt: all 3 attachments succeed (2 report.pdf with different content + 1 summary.pdf)
        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        # 3 attachments total: 2 report.pdf (different content) + 1 summary.pdf
        self.assertEqual(TicketAttachment.objects.count(), 3,

                         f"Expected 3 attachments (2 report.pdf + 1 summary), got {TicketAttachment.objects.count()}")

        # Get the content hashes
        report_atts = TicketAttachment.objects.filter(
            original_filename="report.pdf").order_by("pk")
        self.assertEqual(report_atts.count(), 2,
                         "Expected two report.pdf attachments with different content")

        att1_hash = report_atts[0].content_hash

        # Reset EmailProcessing to failed (simulating partial failure scenario)
        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        EmailProcessing.objects.filter(pk=proc.pk).update(status="failed")

        # Retry the same email
        ticket2, created2, error2 = _ingest(attachments)
        self.assertIsNone(error2)

        # Both report.pdf attachments should still be present (deduplicated by content hash)
        report_atts = TicketAttachment.objects.filter(
            original_filename="report.pdf").order_by("pk")
        self.assertEqual(report_atts.count(), 2,
                         f"Expected two report.pdf attachments after retry, got {report_atts.count()}")

        # The content hashes should be preserved (different from each other, and from summary.pdf)
        self.assertNotEqual(
            report_atts[0].content_hash, report_atts[1].content_hash)
        summary_att = TicketAttachment.objects.get(original_filename="summary.pdf")
        self.assertNotEqual(
            summary_att.content_hash, report_atts[0].content_hash)