"""Phase E.4 — inbound reply-note idempotency, recovery, and concurrency.

Focuses on reply processing: the same inbound reply email must not create
duplicate notes, tickets, or attachments on retries/replays, while different
legitimate replies remain distinct. Also protects existing Phase E.3 behavior.
"""
import os
import shutil
import tempfile
import threading
from email import message_from_bytes
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.tests import make_users
from common import inbound
from common.models import EmailProcessing
from tickets.models import Ticket, TicketAttachment, TicketCategory, TicketNote


LOC = {
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "INBOUND_ALLOWED_SENDER_DOMAINS": "example.com",
    "ATTACHMENT_MAX_SIZE_MB": 10,
    "ATTACHMENT_ALLOWED_EXTENSIONS": "pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx",
}


def build_raw_email(message_id, sender, recipient, subject, body,
                    in_reply_to="", attachments=None):
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["Message-ID"] = message_id
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for att in (attachments or []):
        data = att.get("data", b"x")
        filename = att.get("filename") or "file.bin"
        ctype = att.get("content_type") or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        part = MIMEApplication(data, _subtype=subtype)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        part.set_type(ctype)
        msg.attach(part)
    return msg.as_bytes()


def _ingest_raw(raw, mailbox="support", attachments=None):
    msg = message_from_bytes(raw)
    msg_dict = inbound.build_inbound_message(msg, mailbox=mailbox)
    if attachments is not None:
        msg_dict["attachments"] = attachments
    return inbound.process_inbound_email(msg_dict, mailbox=mailbox)


class InboundReplyPhaseE4Base(TestCase):
    def setUp(self):
        cache.clear()
        self.media_root = tempfile.mkdtemp(prefix="phase-e4-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(MEDIA_ROOT=self.media_root, **LOC)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="HW")

    def create_source_ticket(self, message_id="<src-ticket@example.com>",
                             subject="Broken laptop",
                             body="Screen will not turn on.",
                             sender="Employee <e@x>"):
        raw = build_raw_email(
            message_id, sender, "support@example.com", subject, body)
        ticket, created, error = _ingest_raw(raw)
        self.assertIsNone(error)
        self.assertTrue(created)
        self.assertIsNotNone(ticket)
        return ticket

    def reply_raw(self, message_id, ticket, body="Reply body",
                  subject=None, sender="Employee <e@x>",
                  in_reply_to="<src-ticket@example.com>",
                  attachments=None):
        return build_raw_email(
            message_id,
            sender,
            "support@example.com",
            subject or f"Re: {ticket.title} #{ticket.pk}",
            body,
            in_reply_to=in_reply_to,
            attachments=attachments,
        )

    def ingest_reply(self, message_id, ticket, body="Reply body",
                     subject=None, sender="Employee <e@x>",
                     in_reply_to="<src-ticket@example.com>",
                     attachments=None):
        return _ingest_raw(self.reply_raw(
            message_id, ticket, body=body, subject=subject, sender=sender,
            in_reply_to=in_reply_to, attachments=attachments))

    def stored_files(self):
        base = os.path.join(self.media_root, "ticket_attachments")
        if not os.path.isdir(base):
            return []
        return sorted(os.listdir(base))


class ReplyIdempotencyTests(InboundReplyPhaseE4Base):
    def test_successful_reply_processing(self):
        ticket = self.create_source_ticket()
        mail.outbox.clear()
        ticket2, created, error = self.ingest_reply(
            "<reply-ok@example.com>", ticket, body="The screen is now back.")
        self.assertIsNone(error)
        self.assertFalse(created)
        self.assertEqual(ticket2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        notes = TicketNote.objects.filter(ticket=ticket)
        self.assertEqual(notes.count(), 1)
        note = notes.get()
        self.assertEqual(note.body, "The screen is now back.")
        self.assertEqual(note.author, self.emp)
        self.assertFalse(note.is_internal)
        self.assertEqual(note.source_message_id, "<reply-ok@example.com>")
        proc = EmailProcessing.objects.get(message_id="<reply-ok@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, ticket.pk)
        self.assertIsNotNone(proc.processed_at)

    def test_replaying_same_successful_reply_email(self):
        ticket = self.create_source_ticket()
        t1, c1, e1 = self.ingest_reply("<reply-replay@example.com>", ticket)
        self.assertIsNone(e1)
        for _ in range(4):
            t2, c2, e2 = self.ingest_reply("<reply-replay@example.com>", ticket)
            self.assertIsNone(e2)
            self.assertFalse(c2)
            self.assertEqual(t2.pk, t1.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id="<reply-replay@example.com>").count(), 1)
        proc = EmailProcessing.objects.get(message_id="<reply-replay@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, ticket.pk)

    def test_staff_reply_is_internal_and_idempotent(self):
        ticket = self.create_source_ticket()
        t1, c1, e1 = self.ingest_reply(
            "<staff-reply@example.com>", ticket,
            body="We replaced the screen.",
            sender="IT <m@x>")
        self.assertIsNone(e1)
        self.assertFalse(c1)
        note = TicketNote.objects.get(
            ticket=ticket, source_message_id="<staff-reply@example.com>")
        self.assertTrue(note.is_internal)
        self.assertEqual(note.author, self.mgr)
        t2, c2, e2 = self.ingest_reply(
            "<staff-reply@example.com>", ticket,
            body="We replaced the screen.",
            sender="IT <m@x>")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(TicketNote.objects.filter(
            source_message_id="<staff-reply@example.com>").count(), 1)

    def test_two_different_emails_with_identical_reply_text(self):
        ticket = self.create_source_ticket()
        t1, c1, e1 = self.ingest_reply(
            "<reply-same-a@example.com>", ticket, body="Same text")
        t2, c2, e2 = self.ingest_reply(
            "<reply-same-b@example.com>", ticket, body="Same text")
        self.assertIsNone(e1)
        self.assertIsNone(e2)
        self.assertEqual(t1.pk, ticket.pk)
        self.assertEqual(t2.pk, ticket.pk)
        notes = TicketNote.objects.filter(ticket=ticket).order_by("id")
        self.assertEqual(notes.count(), 2)
        self.assertEqual([n.body for n in notes], ["Same text", "Same text"])
        self.assertEqual(
            {n.source_message_id for n in notes},
            {"<reply-same-a@example.com>", "<reply-same-b@example.com>"})

    def test_multiple_legitimate_replies_to_same_ticket(self):
        ticket = self.create_source_ticket()
        for i in range(3):
            t, c, e = self.ingest_reply(
                f"<reply-multi-{i}@example.com>", ticket, body=f"Reply {i}")
            self.assertIsNone(e)
            self.assertEqual(t.pk, ticket.pk)
            self.assertFalse(c)
        self.assertEqual(Ticket.objects.count(), 1)
        notes = TicketNote.objects.filter(ticket=ticket).order_by("id")
        self.assertEqual(notes.count(), 3)
        self.assertEqual([n.body for n in notes], ["Reply 0", "Reply 1", "Reply 2"])
        self.assertEqual(len({n.source_message_id for n in notes}), 3)

    def test_existing_manual_notes_remain_unaffected(self):
        ticket = self.create_source_ticket()
        manual = TicketNote.objects.create(
            ticket=ticket, author=self.mgr, body="Manual note",
            is_internal=True, source_message_id="")
        self.assertEqual(manual.source_message_id, "")
        t, c, e = self.ingest_reply("<reply-manual@example.com>", ticket)
        self.assertIsNone(e)
        self.assertEqual(TicketNote.objects.filter(ticket=ticket).count(), 2)
        manual.refresh_from_db()
        self.assertEqual(manual.body, "Manual note")
        self.assertEqual(manual.source_message_id, "")
        self.assertTrue(TicketNote.objects.filter(
            ticket=ticket, source_message_id="<reply-manual@example.com>").exists())
        # Reprocessing reply does not affect or duplicate manual note.
        self.ingest_reply("<reply-manual@example.com>", ticket)
        self.assertEqual(TicketNote.objects.filter(ticket=ticket).count(), 2)


class ReplyFailureRecoveryTests(InboundReplyPhaseE4Base):
    def _raise_on_processed_status(self, target_msg_id, exc=None):
        real = inbound._update_processing
        err = exc or RuntimeError("simulated failure before processed status")

        def side_effect(proc, **fields):
            if proc.message_id == target_msg_id and fields.get("status") == "processed":
                raise err
            return real(proc, **fields)

        return patch.object(inbound, "_update_processing", side_effect=side_effect)

    def test_failure_immediately_after_reply_note_creation(self):
        ticket = self.create_source_ticket()
        msg_id = "<reply-after-note@example.com>"
        with self._raise_on_processed_status(msg_id):
            ticket2, created, error = self.ingest_reply(msg_id, ticket)
        self.assertIsNone(ticket2)
        self.assertFalse(created)
        self.assertIsNotNone(error)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "failed")
        self.assertEqual(proc.ticket_id, ticket.pk)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)

        t3, c3, e3 = self.ingest_reply(msg_id, ticket)
        self.assertIsNone(e3)
        self.assertEqual(t3.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, ticket.pk)

    def test_failure_after_reply_note_creation_before_attachment_persistence_boundary(self):
        """Reply emails may include MIME attachments; current reply flow does not
        persist them as ticket attachments. A failure after note creation (before
        any reply-attachment persistence/final status) must not duplicate notes or
        tickets on retry and must not create attachment rows/files for the reply.
        """
        ticket = self.create_source_ticket()
        msg_id = "<reply-note-before-attach@example.com>"
        attachments = [
            {"filename": "reply.txt", "data": b"reply-data",
             "content_type": "text/plain"},
        ]
        with self._raise_on_processed_status(msg_id):
            ticket2, created, error = self.ingest_reply(
                msg_id, ticket, body="See attachment", attachments=attachments)
        self.assertIsNotNone(error)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)
        self.assertEqual(TicketAttachment.objects.filter(
            source_message_id=msg_id).count(), 0)

        t3, c3, e3 = self.ingest_reply(
            msg_id, ticket, body="See attachment", attachments=attachments)
        self.assertIsNone(e3)
        self.assertEqual(t3.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)
        # Reply attachments are not persisted by current reply behavior; ensure no
        # duplicates/phantom rows across retry.
        self.assertEqual(TicketAttachment.objects.filter(
            source_message_id=msg_id).count(), 0)
        self.assertEqual(self.stored_files(), [])
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "processed")

    def test_failure_after_attachment_persistence_before_final_status_new_ticket_path(self):
        """Attachment-persistence boundary regression (new-ticket/inbound-owned
        path): failure after saving attachments but before final processed status
        must not duplicate notes/tickets/attachments on retry.
        """
        msg_id = "<new-ticket-attach-status@example.com>"
        attachments = [
            ("a.txt", b"A", "text/plain"),
            ("b.txt", b"B", "text/plain"),
        ]
        real = inbound._update_processing

        def fail_on_processed(proc, **fields):
            if proc.message_id == msg_id and fields.get("status") == "processed":
                raise IntegrityError("simulated status commit failure")
            return real(proc, **fields)

        from email.message import EmailMessage
        em = EmailMessage()
        em["Subject"] = "Attach issue"
        em["From"] = "Employee <e@x>"
        em["To"] = "support@example.com"
        em["Message-ID"] = msg_id
        em.set_content("broken")
        for name, data, ctype in attachments:
            mt, st = ctype.split("/", 1)
            em.add_attachment(data, maintype=mt, subtype=st, filename=name)

        with patch.object(inbound, "_update_processing", side_effect=fail_on_processed):
            ticket, created, error = inbound.process_inbound_email(
                inbound.build_inbound_message(em))
        self.assertIsNotNone(error)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "failed")
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(TicketNote.objects.count(), 0)
        ticket_id = proc.ticket_id
        self.assertIsNotNone(ticket_id)

        ticket2, created2, error2 = inbound.process_inbound_email(
            inbound.build_inbound_message(em))
        self.assertIsNone(error2)
        self.assertFalse(created2)
        self.assertEqual(ticket2.pk, ticket_id)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 2)
        self.assertEqual(TicketNote.objects.count(), 0)

    def test_failure_during_final_status_update_on_reply(self):
        ticket = self.create_source_ticket()
        msg_id = "<reply-final-status@example.com>"
        with self._raise_on_processed_status(
                msg_id, exc=IntegrityError("status update failed")):
            t2, c2, e2 = self.ingest_reply(msg_id, ticket, body="Status fail")
        self.assertIsNotNone(e2)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "failed")
        self.assertEqual(proc.ticket_id, ticket.pk)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)

        t3, c3, e3 = self.ingest_reply(msg_id, ticket, body="Status fail")
        self.assertIsNone(e3)
        self.assertEqual(t3.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "processed")

    def test_multiple_retries_of_same_reply_email(self):
        ticket = self.create_source_ticket()
        msg_id = "<reply-multi-retry@example.com>"
        for i in range(3):
            with self._raise_on_processed_status(
                    msg_id, exc=RuntimeError(f"fail-{i}")):
                _t, _c, err = self.ingest_reply(msg_id, ticket, body="Retry me")
            self.assertIsNotNone(err)
            proc = EmailProcessing.objects.get(message_id=msg_id)
            self.assertEqual(proc.status, "failed")
            self.assertEqual(proc.ticket_id, ticket.pk)

        t2, c2, e2 = self.ingest_reply(msg_id, ticket, body="Retry me")
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "processed")

    def test_reply_retry_after_failure_preserves_ticket_linkage_and_failure_info(self):
        ticket = self.create_source_ticket()
        msg_id = "<reply-linkage@example.com>"
        with self._raise_on_processed_status(msg_id):
            _t, _c, err = self.ingest_reply(msg_id, ticket)
        self.assertIsNotNone(err)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "failed")
        self.assertEqual(proc.ticket_id, ticket.pk)
        self.assertTrue(proc.error_details)

        t2, c2, e2 = self.ingest_reply(msg_id, ticket)
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, ticket.pk)


class ReplyCompatibilityTests(InboundReplyPhaseE4Base):
    def test_existing_inbound_attachment_identity_behavior_intact(self):
        """Reply-note idempotency must not regress Phase E.3 attachment identity."""
        from email.message import EmailMessage
        msg_id = "<e4-attach-compat@example.com>"
        em = EmailMessage()
        em["Subject"] = "Attach compat"
        em["From"] = "Employee <e@x>"
        em["To"] = "support@example.com"
        em["Message-ID"] = msg_id
        em.set_content("body")
        for name, data in [("r.pdf", b"SAME"), ("r.pdf", b"SAME"), ("r.pdf", b"DIFF")]:
            em.add_attachment(data, maintype="application", subtype="pdf",
                              filename=name)
        t1, c1, e1 = inbound.process_inbound_email(inbound.build_inbound_message(em))
        self.assertIsNone(e1)
        self.assertTrue(c1)
        self.assertEqual(TicketAttachment.objects.filter(source_message_id=msg_id).count(), 3)
        t2, c2, e2 = inbound.process_inbound_email(inbound.build_inbound_message(em))
        self.assertIsNone(e2)
        self.assertFalse(c2)
        self.assertEqual(t2.pk, t1.pk)
        self.assertEqual(TicketAttachment.objects.count(), 3)

    def test_reply_resolved_by_subject_ref(self):
        ticket = self.create_source_ticket(message_id="<src-subject@example.com>")
        t2, c2, e2 = _ingest_raw(build_raw_email(
            "<reply-subject@example.com>", "Employee <e@x>",
            "support@example.com", f"Re: {ticket.title} #{ticket.pk}",
            "Via subject", in_reply_to=""))
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(TicketNote.objects.filter(
            source_message_id="<reply-subject@example.com>").count(), 1)

    def test_reply_after_ticket_creation_failure_reuses_ticket_no_duplicate_note(self):
        """Failure after ticket creation (new-ticket path) must not affect later
        reply idempotency; and reply retries themselves remain idempotent.
        """
        from email.message import EmailMessage
        msg_id = "<new-fail-then-reply@example.com>"
        em = EmailMessage()
        em["Subject"] = "Initial"
        em["From"] = "Employee <e@x>"
        em["To"] = "support@example.com"
        em["Message-ID"] = msg_id
        em.set_content("initial")
        em.add_attachment(b"A", maintype="text", subtype="plain", filename="a.txt")

        original_create = TicketAttachment.objects.create

        def fail_once(*args, **kwargs):
            raise IntegrityError("fail attachment")

        with patch.object(TicketAttachment.objects, "create", side_effect=fail_once):
            ticket, _c, err = inbound.process_inbound_email(
                inbound.build_inbound_message(em))
        self.assertIsNotNone(err)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        ticket = Ticket.objects.get(pk=proc.ticket_id)

        t2, c2, e2 = inbound.process_inbound_email(inbound.build_inbound_message(em))
        self.assertIsNone(e2)
        self.assertEqual(t2.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAttachment.objects.count(), 1)

        # Now process a reply to that ticket with failure/retry.
        reply_id = "<reply-after-recovered-ticket@example.com>"
        with self._raise_on_processed_status(reply_id):
            _rt, _rc, rerr = self.ingest_reply(reply_id, ticket)
        self.assertIsNotNone(rerr)
        t3, c3, e3 = self.ingest_reply(reply_id, ticket)
        self.assertIsNone(e3)
        self.assertEqual(t3.pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            source_message_id=reply_id).count(), 1)

    def _raise_on_processed_status(self, target_msg_id, exc=None):
        real = inbound._update_processing
        err = exc or RuntimeError("simulated failure before processed status")

        def side_effect(proc, **fields):
            if proc.message_id == target_msg_id and fields.get("status") == "processed":
                raise err
            return real(proc, **fields)

        return patch.object(inbound, "_update_processing", side_effect=side_effect)


class ReplyConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        cache.clear()
        self.media_root = tempfile.mkdtemp(prefix="phase-e4-conc-")
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(MEDIA_ROOT=self.media_root, **LOC)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.dep, self.admin, self.mgr, self.emp = make_users()
        TicketCategory.objects.create(name="HW")

    def _create_ticket(self):
        raw = build_raw_email(
            "<conc-src@example.com>", "Employee <e@x>", "support@example.com",
            "Source", "body")
        ticket, created, error = _ingest_raw(raw)
        self.assertIsNone(error)
        self.assertTrue(created)
        return ticket

    def test_same_reply_email_processed_concurrently_no_duplicate_notes(self):
        if connection.vendor == "sqlite":
            self.skipTest(
                "Concurrent same-reply processing stress is not reliable on SQLite; "
                "DB-level locking/uniqueness correctness must be verified on PostgreSQL.")
        ticket = self._create_ticket()
        msg_id = "<conc-reply@example.com>"
        raw = build_raw_email(
            msg_id, "Employee <e@x>", "support@example.com",
            f"Re: {ticket.title} #{ticket.pk}", "Concurrent reply",
            in_reply_to="<conc-src@example.com>")
        results = []
        errors = []

        def worker():
            try:
                connection.close()
                results.append(_ingest_raw(raw))
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
        self.assertGreaterEqual(len([r for r in results if r[2] is None]), 1)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNote.objects.filter(
            ticket=ticket, source_message_id=msg_id).count(), 1)
        proc = EmailProcessing.objects.get(message_id=msg_id)
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket_id, ticket.pk)
