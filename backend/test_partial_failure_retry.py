"""Regression tests: partial-failure retry for inbound email attachments.

Covers true idempotent retry: ticket reuse across retryable states, stable
MIME-part identity, exact dedup/recovery, and preservation of storage.
"""
import os
import shutil
import tempfile

from email.message import EmailMessage

from django.db import IntegrityError
from django.test import TestCase, override_settings
from unittest.mock import patch

from common import inbound
from common.models import EmailProcessing
from tickets.models import Ticket, TicketAttachment


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


class PartialFailureRetryTests(TestCase):
    """Partial-failure retry scenario for inbound email attachments."""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="inbound-retry-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(
            MEDIA_ROOT=self.media_root,
            **_SETTINGS)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _stored(self):
        base = os.path.join(self.media_root, "ticket_attachments")
        if not os.path.isdir(base):
            return {}
        stored = {}
        for name in os.listdir(base):
            with open(os.path.join(base, name), "rb") as fh:
                stored[name] = fh.read()
        return stored

    def _is_integrity_error(self, error):
        return isinstance(error, str) and error.startswith("IntegrityError:")

    def test_partial_failure_retry_workflow(self):
        """Failure on 3rd attachment, retry reuses ticket and completes exactly once.

        First attempt: one email creates one ticket, processing stores ticket
        relationship, 3 parts extracted, first two saved, third DB persist fails
        and its stored file is cleaned up. Retry reuses original ticket, saves
        only the missing third part, and finishes with exactly 3 attachments.
        """
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

        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        self.assertEqual(proc.status, "failed")
        self.assertIsNotNone(proc.ticket_id)
        ticket_id = proc.ticket_id

        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(
            {a.original_filename for a in TicketAttachment.objects.all()},
            {"att1.txt", "att2.txt"})
        self.assertEqual(
            sorted(self._stored().values()), [b"content1", b"content2"])

        ticket2, created2, error2 = _ingest(attachments)

        self.assertIsNone(error2)
        self.assertFalse(created2)
        self.assertEqual(ticket2.pk, ticket_id)

        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(
            {a.original_filename for a in TicketAttachment.objects.all()},
            {"att1.txt", "att2.txt", "att3.txt"})
        self.assertEqual(
            sorted(self._stored().values()),
            [b"content1", b"content2", b"content3"])

        proc = EmailProcessing.objects.get(
            message_id="<inbound-attach@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertIsNotNone(proc.processed_at)
        self.assertEqual(proc.ticket_id, ticket_id)

        # Repeated successful replay: no additional tickets/rows/files.
        for _ in range(3):
            t3, c3, e3 = _ingest(attachments)
            self.assertIsNone(e3)
            self.assertFalse(c3)
            self.assertEqual(t3.pk, ticket_id)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(
            sorted(self._stored().values()),
            [b"content1", b"content2", b"content3"])

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