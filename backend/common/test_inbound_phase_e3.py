"""Phase E.3 — inbound email processing reliability and true idempotency.

Covers ticket reuse across retryable states, stable MIME attachment identity,
partial-failure recovery, replay idempotency, legacy/manual compatibility, and
concurrency where supported by the database.
"""
import os
import shutil
import tempfile
import threading
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature

from common import inbound
from common.models import EmailProcessing
from tickets.models import Ticket, TicketAttachment

_SETTINGS = {
    "INBOUND_ALLOWED_SENDER_DOMAINS": "example.com",
    "ATTACHMENT_MAX_SIZE_MB": 10,
    "ATTACHMENT_ALLOWED_EXTENSIONS": "pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx",
}


def _message(attachments=(), body="Printer is broken",
             message_id="<phase-e3@example.com>",
             subject="Printer broken", sender="user@example.com"):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "support@example.com"
    msg["Message-ID"] = message_id
    msg.set_content(body)
    for name, data, ctype in attachments:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=name)
    return msg


def _ingest(attachments=(), message_id="<phase-e3@example.com>",
            subject="Printer broken", sender="user@example.com", body="Printer is broken"):
    msg = _message(attachments=attachments, message_id=message_id,
                   subject=subject, sender=sender, body=body)
    return inbound.process_inbound_email(inbound.build_inbound_message(msg))


def _raw_bytes(attachments=(), body="Printer is broken",
               message_id="<phase-e3@example.com>",
               subject="Printer broken", sender="user@example.com"):
    return _message(attachments=attachments, body=body, message_id=message_id,
                    subject=subject, sender=sender).as_bytes()


class InboundPhaseE3Base(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="phase-e3-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(MEDIA_ROOT=self.media_root, **_SETTINGS)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def stored(self):
        base = os.path.join(self.media_root, "ticket_attachments")
        if not os.path.isdir(base):
            return {}
        stored = {}
        for name in os.listdir(base):
            with open(os.path.join(base, name), "rb") as fh:
                stored[name] = fh.read()
        return stored

    def is_integrity_error(self, error):
        return isinstance(error, str) and error.startswith("IntegrityError:")

    def fail_create_on_nth(self, n, exc=None):
        """Context manager: fail TicketAttachment.objects.create on nth call."""
        call_count = [0]
        original_create = TicketAttachment.objects.create
        err = exc or IntegrityError(f"simulated db failure on attachment {n}")

        def failing_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == n:
                raise err
            return original_create(*args, **kwargs)

        return patch.object(TicketAttachment.objects, "create", failing_create)


class AttachmentIdentityTests(InboundPhaseE3Base):
    def test_same_filename_different_content_separate_parts(self):
        attachments = [
            ("report.pdf", b"January", "application/pdf"),
            ("report.pdf", b"February", "application/pdf"),
        ]
        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        self.assertTrue(created)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        atts = list(TicketAttachment.objects.filter(ticket=ticket).order_by("source_part_index"))
        self.assertEqual([a.original_filename for a in atts], ["report.pdf", "report.pdf"])
        self.assertNotEqual(atts[0].content_hash, atts[1].content_hash)
        self.assertEqual([a.source_part_index for a in atts], [0, 1])

    def test_same_filename_identical_content_separate_mime_parts(self):
        attachments = [
            ("report.pdf", b"SAME", "application/pdf"),
            ("report.pdf", b"SAME", "application/pdf"),
        ]
        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        atts = list(TicketAttachment.objects.filter(ticket=ticket).order_by("source_part_index"))
        self.assertEqual(atts[0].content_hash, atts[1].content_hash)
        self.assertNotEqual(atts[0].source_part_index, atts[1].source_part_index)
        self.assertEqual(len(self.stored()), 2)

    def test_three_same_filename_mixed_content(self):
        attachments = [
            ("report.pdf", b"A", "application/pdf"),
            ("report.pdf", b"A", "application/pdf"),
            ("report.pdf", b"B", "application/pdf"),
        ]
        ticket, created, error = _ingest(attachments)
        self.assertIsNone(error)
        self.assertTrue(created)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(Ticket.objects.count(), 1)
        atts = list(TicketAttachment.objects.filter(ticket=ticket).order_by("source_part_index"))
        self.assertEqual([a.source_part_index for a in atts], [0, 1, 2])
        self.assertEqual(atts[0].content_hash, atts[1].content_hash)
        self.assertNotEqual(atts[0].content_hash, atts[2].content_hash)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"A", b"B"])

    def test_stable_identity_across_repeated_parsing(self):
        raw = _raw_bytes(attachments=[
            ("report.pdf", b"A", "application/pdf"),
            ("report.pdf", b"A", "application/pdf"),
            ("report.pdf", b"B", "application/pdf"),
        ])
        import email
        msg1 = email.message_from_bytes(raw)
        msg2 = email.message_from_bytes(raw)
        a1 = inbound._attachments_from_message(msg1)
        a2 = inbound._attachments_from_message(msg2)
        self.assertEqual([a["part_index"] for a in a1], [0, 1, 2])
        self.assertEqual([a["part_index"] for a in a2], [0, 1, 2])
        self.assertEqual([a["filename"] for a in a1], [a["filename"] for a in a2])
        self.assertEqual([a["data"] for a in a1], [a["data"] for a in a2])

        d1 = inbound.build_inbound_message(msg1)
        d2 = inbound.build_inbound_message(msg2)
        t1, c1, e1 = inbound.process_inbound_email(d1)
        t2, c2, e2 = inbound.process_inbound_email(d2)
        self.assertIsNone(e1)
        self.assertIsNone(e2)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(len(self.stored()), 3)

    def test_reprocessing_does_not_duplicate_attachments(self):
        attachments = [
            ("a.txt", b"1", "text/plain"),
            ("a.txt", b"1", "text/plain"),
            ("b.txt", b"2", "text/plain"),
        ]
        t1, c1, e1 = _ingest(attachments)
        self.assertIsNone(e1)
        for _ in range(4):
            t2, c2, e2 = _ingest(attachments)
            self.assertIsNone(e2)
            self.assertFalse(c2)
            self.assertEqual(t2.pk, t1.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(len(self.stored()), 3)

    def test_different_emails_not_accidentally_merged(self):
        att = [("report.pdf", b"SAME", "application/pdf")]
        t1, c1, e1 = _ingest(att, message_id="<e3-a@example.com>", subject="A")
        t2, c2, e2 = _ingest(att, message_id="<e3-b@example.com>", subject="B")
        self.assertIsNone(e1)
        self.assertIsNone(e2)
        self.assertTrue(c1)
        self.assertTrue(c2)
        self.assertNotEqual(t1.pk, t2.pk)
        self.assertEqual(Ticket.objects.count(), 2)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual({a.ticket_id for a in TicketAttachment.objects.all()}, {t1.pk, t2.pk})
        self.assertEqual(len(self.stored()), 2)


class TicketReuseTests(InboundPhaseE3Base):
    def _setup_failed_with_ticket(self, attachments=None, message_id="<reuse-fail@example.com>"):
        attachments = attachments or [("a.txt", b"1", "text/plain")]
        with self.fail_create_on_nth(1):
            _ticket, _created, error = _ingest(attachments, message_id=message_id)
        self.assertIsNotNone(error)
        proc = EmailProcessing.objects.get(message_id=message_id)
        self.assertEqual(proc.status, "failed")
        self.assertIsNotNone(proc.ticket_id)
        ticket = Ticket.objects.get(pk=proc.ticket_id)
        return ticket, proc

    def _setup_pending_with_ticket(self, attachments=None, message_id="<reuse-pending@example.com>"):
        attachments = attachments or [("a.txt", b"1", "text/plain")]
        ticket, _created, error = _ingest(attachments, message_id=message_id)
        self.assertIsNone(error)
        proc = EmailProcessing.objects.get(message_id=message_id)
        EmailProcessing.objects.filter(pk=proc.pk).update(status="pending")
        proc.refresh_from_db()
        self.assertEqual(proc.status, "pending")
        self.assertEqual(proc.ticket_id, ticket.pk)
        return ticket, proc

    def test_failed_processing_with_existing_ticket_reuses_ticket(self):
        ticket, _proc = self._setup_failed_with_ticket(
            attachments=[("a.txt", b"1", "text/plain"), ("b.txt", b"2", "text/plain")],
            message_id="<reuse-failed@example.com>")
        # first attempt failed on 1st attachment, so none saved
        t2, c2, e2 = _ingest(
            attachments=[("a.txt", b"1", "text/plain"), ("b.txt", b"2", "text/plain")],
            message_id="<reuse-failed@example.com>")
        self.assertIsNone(e2)
        self.assertFalse(c2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 2)

    def test_pending_processing_with_existing_ticket_reuses_ticket(self):
        ticket, _proc = self._setup_pending_with_ticket(
            attachments=[("a.txt", b"1", "text/plain")],
            message_id="<reuse-pending@example.com>")
        # replay after forced pending; attachments already saved idempotently
        t2, c2, e2 = _ingest(
            attachments=[("a.txt", b"1", "text/plain")],
            message_id="<reuse-pending@example.com>")
        self.assertIsNone(e2)
        self.assertFalse(c2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 1)

    def test_multiple_retries_reuse_same_ticket(self):
        attachments = [("a.txt", b"1", "text/plain"), ("b.txt", b"2", "text/plain"),
                       ("c.txt", b"3", "text/plain")]
        original_create = TicketAttachment.objects.create

        def fail_part2(*args, **kwargs):
            if kwargs.get("source_part_index") == 2:
                raise IntegrityError("simulated db failure on part 2")
            return original_create(*args, **kwargs)

        # Fail on the 3rd MIME part repeatedly (idempotent retries only attempt
        # missing parts), then succeed.
        for _ in range(2):
            with patch.object(TicketAttachment.objects, "create", side_effect=fail_part2):
                _ticket, _c, err = _ingest(attachments, message_id="<multi-retry@example.com>")
            self.assertIsNotNone(err)
            proc = EmailProcessing.objects.get(message_id="<multi-retry@example.com>")
            self.assertEqual(proc.status, "failed")
            self.assertIsNotNone(proc.ticket_id)

        ticket_id = EmailProcessing.objects.get(
            message_id="<multi-retry@example.com>").ticket_id
        t2, c2, e2 = _ingest(attachments, message_id="<multi-retry@example.com>")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket_id)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)

    def test_new_email_without_existing_ticket_creates_one_ticket(self):
        t1, c1, e1 = _ingest(message_id="<new-1@example.com>", subject="New 1")
        self.assertIsNone(e1)
        self.assertTrue(c1)
        self.assertIsNotNone(t1)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_invalid_or_deleted_ticket_reference_recovers(self):
        ticket, _c, e = _ingest(message_id="<deleted-ref@example.com>")
        self.assertIsNone(e)
        proc = EmailProcessing.objects.get(message_id="<deleted-ref@example.com>")
        # Simulate an invalid/stale reference (ticket id no longer valid for reuse).
        EmailProcessing.objects.filter(pk=proc.pk).update(
            ticket_id=999999999, status="failed")
        proc.refresh_from_db()
        self.assertEqual(proc.status, "failed")
        self.assertEqual(proc.ticket_id, 999999999)

        t2, c2, e2 = _ingest(message_id="<deleted-ref@example.com>")
        self.assertIsNone(e2)
        self.assertIsNotNone(t2)
        self.assertNotEqual(t2.pk, 999999999)
        proc = EmailProcessing.objects.get(message_id="<deleted-ref@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, t2.pk)

    def test_soft_deleted_ticket_reference_recovers(self):
        # If the linked ticket is soft-deleted (not visible via default manager),
        # retry must recover safely without crashing or duplicating on success.
        attachments = [("a.txt", b"A", "text/plain")]
        ticket, _c, e = _ingest(attachments=attachments, message_id="<softdel-ref@example.com>")
        self.assertIsNone(e)
        # Soft delete the ticket (default manager behavior).
        ticket.soft_delete(reason="test")
        EmailProcessing.objects.filter(message_id="<softdel-ref@example.com>").update(status="failed")
        t2, c2, e2 = _ingest(attachments=attachments, message_id="<softdel-ref@example.com>")
        self.assertIsNone(e2)
        self.assertIsNotNone(t2)
        proc = EmailProcessing.objects.get(message_id="<softdel-ref@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, t2.pk)


class FailureRecoveryTests(InboundPhaseE3Base):
    def test_failure_after_first_attachment(self):
        attachments = [
            ("a.txt", b"A", "text/plain"),
            ("b.txt", b"B", "text/plain"),
            ("c.txt", b"C", "text/plain"),
        ]
        with self.fail_create_on_nth(2):
            _ticket, _c, error = _ingest(attachments, message_id="<fail-1@example.com>")
        self.assertIsNotNone(error)
        proc = EmailProcessing.objects.get(message_id="<fail-1@example.com>")
        ticket = Ticket.objects.get(pk=proc.ticket_id)
        self.assertEqual(TicketAttachment.objects.count(), 1)
        self.assertEqual(sorted(self.stored().values()), [b"A"])
        self.assertEqual(proc.status, "failed")

        t2, c2, e2 = _ingest(attachments, message_id="<fail-1@example.com>")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"B", b"C"])

    def test_failure_after_second_attachment(self):
        attachments = [
            ("a.txt", b"A", "text/plain"),
            ("b.txt", b"B", "text/plain"),
            ("c.txt", b"C", "text/plain"),
        ]
        with self.fail_create_on_nth(3):
            _ticket, _c, error = _ingest(attachments, message_id="<fail-2@example.com>")
        self.assertIsNotNone(error)
        proc = EmailProcessing.objects.get(message_id="<fail-2@example.com>")
        ticket = Ticket.objects.get(pk=proc.ticket_id)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"B"])
        self.assertEqual(proc.status, "failed")

        t2, c2, e2 = _ingest(attachments, message_id="<fail-2@example.com>")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"B", b"C"])

    def test_failure_after_all_attachments_before_success_status(self):
        attachments = [
            ("a.txt", b"A", "text/plain"),
            ("b.txt", b"B", "text/plain"),
        ]
        real_update = inbound._update_processing

        def fail_on_processed(proc, **fields):
            if fields.get("status") == "processed":
                raise IntegrityError("simulated status commit failure")
            return real_update(proc, **fields)

        with patch.object(inbound, "_update_processing", side_effect=fail_on_processed):
            _ticket, _c, error = _ingest(attachments, message_id="<fail-status@example.com>")
        self.assertIsNotNone(error)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"B"])
        proc = EmailProcessing.objects.get(message_id="<fail-status@example.com>")
        ticket = Ticket.objects.get(pk=proc.ticket_id)
        self.assertEqual(proc.status, "failed")

        t2, c2, e2 = _ingest(attachments, message_id="<fail-status@example.com>")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"B"])
        proc = EmailProcessing.objects.get(message_id="<fail-status@example.com>")
        self.assertEqual(proc.status, "processed")

    def test_failure_after_ticket_creation_persists_and_reuses_ticket(self):
        attachments = [("a.txt", b"A", "text/plain")]
        original_create_ticket = Ticket.objects.create
        created_ids = []

        def tracking_create(*args, **kwargs):
            obj = original_create_ticket(*args, **kwargs)
            created_ids.append(obj.pk)
            return obj

        with patch.object(Ticket.objects, "create", side_effect=tracking_create):
            with self.fail_create_on_nth(1):
                ticket, _c, error = _ingest(attachments, message_id="<fail-after-ticket@example.com>")
        self.assertIsNotNone(error)
        self.assertEqual(len(created_ids), 1)
        proc = EmailProcessing.objects.get(message_id="<fail-after-ticket@example.com>")
        self.assertEqual(proc.ticket_id, created_ids[0])
        self.assertEqual(proc.status, "failed")

        t2, c2, e2 = _ingest(attachments, message_id="<fail-after-ticket@example.com>")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, created_ids[0])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 1)

    def test_repeated_successful_replay_no_duplicates(self):
        attachments = [
            ("report.pdf", b"A", "application/pdf"),
            ("report.pdf", b"A", "application/pdf"),
            ("report.pdf", b"B", "application/pdf"),
        ]
        t1, c1, e1 = _ingest(attachments, message_id="<replay@example.com>")
        self.assertIsNone(e1)
        for _ in range(5):
            t2, c2, e2 = _ingest(attachments, message_id="<replay@example.com>")
            self.assertIsNone(e2)
            self.assertFalse(c2)
            self.assertEqual(t2.pk, t1.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 3)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"A", b"B"])

    def test_exact_file_cleanup_after_database_failure(self):
        attachments = [
            ("a.txt", b"A", "text/plain"),
            ("b.txt", b"B", "text/plain"),
            ("c.txt", b"C", "text/plain"),
        ]
        with self.fail_create_on_nth(3):
            _ticket, _c, error = _ingest(attachments, message_id="<cleanup@example.com>")
        self.assertIsNotNone(error)
        # Third stored object must be cleaned up; first two remain paired.
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(sorted(self.stored().values()), [b"A", b"B"])
        self.assertEqual(len(self.stored()), 2)


class LegacyAndManualAttachmentCompatibilityTests(InboundPhaseE3Base):
    def test_manual_uploaded_attachment_unaffected(self):
        """Manual uploads (no source identity) remain valid and independent."""
        from django.core.files.base import ContentFile
        from tickets.attachment_storage import store_upload

        ticket, _c, e = _ingest(message_id="<manual@example.com>")
        self.assertIsNone(e)
        stored_name = store_upload(TicketAttachment, ContentFile(b"manual", name="manual.txt"))
        att = TicketAttachment.objects.create(
            ticket=ticket,
            file=stored_name,
            original_filename="manual.txt",
            content_hash="x" * 64,
            source_message_id="",
            source_part_index=None,
        )
        self.assertEqual(att.source_message_id, "")
        self.assertIsNone(att.source_part_index)
        # Inbound processing for a different email is unaffected.
        t2, c2, e2 = _ingest(message_id="<manual-2@example.com>", attachments=[("a.txt", b"A", "text/plain")])
        self.assertIsNone(e2)
        self.assertTrue(c2)
        self.assertEqual(TicketAttachment.objects.filter(ticket=ticket).count(), 1)

    def test_legacy_pre_identity_attachment_not_used_as_safe_identity(self):
        """Legacy rows (blank source identity) must not be treated as a dedup key.

        Two legacy rows with blank source identity should not block saving two
        distinct new inbound parts for the same email on retry/reconciliation.
        """
        from django.core.files.base import ContentFile
        from tickets.attachment_storage import store_upload

        # Create a ticket and two legacy attachments with no source identity.
        ticket, _c, e = _ingest(message_id="<legacy-owner@example.com>")
        self.assertIsNone(e)
        for i in range(2):
            name = store_upload(TicketAttachment, ContentFile(b"SAME", name="r.pdf"))
            TicketAttachment.objects.create(
                ticket=ticket, file=name, original_filename="r.pdf",
                content_hash=__import__("hashlib").sha256(b"SAME").hexdigest(),
                source_message_id="", source_part_index=None,
            )
        self.assertEqual(TicketAttachment.objects.filter(ticket=ticket).count(), 2)

        # A different email with two identical parts must save its own two parts.
        t2, c2, e2 = _ingest(
            message_id="<legacy-new@example.com>",
            attachments=[("r.pdf", b"SAME", "application/pdf"), ("r.pdf", b"SAME", "application/pdf")])
        self.assertIsNone(e2)
        self.assertTrue(c2)
        self.assertNotEqual(t2.pk, ticket.pk)
        self.assertEqual(TicketAttachment.objects.filter(ticket=t2).count(), 2)


class ConcurrencyTests(TransactionTestCase):
    """Concurrency-sensitive tests.

    Row-locking guarantees are database-dependent; PostgreSQL-specific claims
    are only verifiable on PostgreSQL. These tests still exercise the
    DB-level uniqueness/race handling paths where supported.
    """
    serialized_rollback = True

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="phase-e3-conc-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(MEDIA_ROOT=self.media_root, **_SETTINGS)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_concurrent_processing_same_email_no_duplicate_ticket_or_attachments(self):
        if connection.vendor == "sqlite":
            self.skipTest(
                "Concurrent same-email processing stress is not reliable on SQLite; "
                "DB-level locking correctness must be verified on PostgreSQL.")
        attachments = [
            ("a.txt", b"A", "text/plain"),
            ("b.txt", b"B", "text/plain"),
        ]
        message_id = "<conc-same@example.com>"
        results = []
        errors = []

        def worker():
            try:
                connection.close()
                res = _ingest(attachments=attachments, message_id=message_id)
                results.append(res)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        successful = [r for r in results if r[2] is None]
        self.assertGreaterEqual(len(successful), 1)
        # Core invariants: never more than one ticket, never duplicate source parts.
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        ticket = Ticket.objects.get()
        self.assertEqual(
            {(a.source_message_id, a.source_part_index) for a in TicketAttachment.objects.all()},
            {(message_id, 0), (message_id, 1)})
        proc = EmailProcessing.objects.get(message_id=message_id)
        self.assertEqual(proc.ticket_id, ticket.pk)
        self.assertEqual(proc.status, "processed")

    @skipUnlessDBFeature("has_select_for_update")
    def test_select_for_update_supported_serializes_processing(self):
        """On DBs with row locking, concurrent same-email processing is serialized.

        This is a stronger claim than the basic concurrency test and is not
        evidence for PostgreSQL unless executed on PostgreSQL.
        """
        if connection.vendor == "sqlite":
            self.skipTest(
                "SQLite row-locking serialization evidence is not equivalent to PostgreSQL.")
        attachments = [("a.txt", b"A", "text/plain")]
        message_id = "<conc-lock@example.com>"
        results = []
        errors = []

        def worker():
            try:
                connection.close()
                results.append(_ingest(attachments=attachments, message_id=message_id))
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 1)
        self.assertTrue(any(r[2] is None for r in results))

    def test_concurrent_attempts_to_create_same_source_attachment_identity(self):
        """Unique source-part identity prevents duplicate rows under races."""
        attachments = [("a.txt", b"A", "text/plain")]
        message_id = "<conc-part@example.com>"
        # Create ticket/processing context first.
        ticket, _c, e = _ingest(attachments=attachments, message_id=message_id)
        self.assertIsNone(e)
        self.assertEqual(TicketAttachment.objects.count(), 1)

        # Simulate concurrent re-saves of the same source part: all should resolve
        # to the single existing row (idempotent) without creating duplicates.
        att_dict = {"filename": "a.txt", "content_type": "text/plain", "data": b"A", "part_index": 0}
        results = []
        errs = []

        def worker():
            try:
                connection.close()
                results.append(inbound._save_attachment(ticket, att_dict, message_id, 0))
            except Exception as exc:
                errs.append(exc)
            finally:
                connection.close()

        if connection.vendor == "sqlite":
            # SQLite write locking makes threaded stress unreliable; exercise the
            # idempotent path sequentially as a compatibility check.
            for _ in range(4):
                results.append(inbound._save_attachment(ticket, att_dict, message_id, 0))
        else:
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errs, [])
        self.assertEqual(TicketAttachment.objects.count(), 1)
        self.assertTrue(all(r.pk == results[0].pk for r in results))
