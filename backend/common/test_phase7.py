"""Phase 7 — email-to-ticket ingestion, replies, ops status, task health.

Covers:
- Valid inbound email -> ticket created for the sender's employee account.
- Duplicate Message-ID -> no duplicate ticket.
- Unsupported attachments -> failed processing, safe retry.
- Replies (subject ticket ref / In-Reply-To) -> ticket note, no new ticket.
- Staff replies -> internal note.
- Unknown senders -> not eligible.
- Operations status endpoint (IT staff only).
- Celery task run recording + SLA escalation task (in-app + email).
- Outbound ticket email dedup.
"""
from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from email import message_from_bytes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from accounts import email_utils as account_email
from common import inbound
from common.models import BackgroundTaskRun, EmailProcessing, Notification
from tickets.models import Ticket, TicketCategory, TicketNote, TicketSLA

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def build_raw_email(message_id, sender, recipient, subject, body,
                   in_reply_to="", attachments=None):
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
        part = MIMEText(att.get("data") or "x", "plain", "utf-8")
        part.add_header("Content-Disposition", "attachment",
                        filename=att.get("filename") or "file.bin")
        msg.attach(part)
    return msg.as_bytes()


@override_settings(**LOC)
class InboundEmailIngestionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="HW")
        self.sender = "Employee <e@x>"

    def _ingest(self, raw, mailbox="support", attachments=None):
        msg = message_from_bytes(raw)
        msg_dict = inbound.build_inbound_message(msg, mailbox=mailbox)
        if attachments is not None:
            msg_dict["attachments"] = attachments
        return inbound.process_inbound_email(msg_dict, mailbox=mailbox)

    def test_valid_email_creates_ticket_for_sender(self):
        raw = build_raw_email(
            "<phase7-1@example.com>", self.sender, "support@example.com",
            "Broken laptop", "Screen will not turn on.")
        ticket, created, error = self._ingest(raw)
        self.assertIsNone(error)
        self.assertTrue(created)
        self.assertEqual(ticket.requester, self.emp)
        self.assertEqual(ticket.title, "Broken laptop")
        self.assertEqual(ticket.description, "Screen will not turn on.")
        proc = EmailProcessing.objects.get(message_id="<phase7-1@example.com>")
        self.assertEqual(proc.status, "processed")
        self.assertEqual(proc.ticket, ticket)
        self.assertEqual(proc.sender, "e@x")
        self.assertEqual(proc.subject, "Broken laptop")
        # Creation confirmation went out to the requester.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.emp.email])

    def test_duplicate_message_id_does_not_duplicate_ticket(self):
        raw = build_raw_email(
            "<phase7-2@example.com>", self.sender, "support@example.com",
            "Wi-Fi down", "No internet since morning.")
        t1, c1, e1 = self._ingest(raw)
        self.assertTrue(c1)
        t2, c2, e2 = self._ingest(raw)
        self.assertFalse(c2)
        self.assertEqual(t1, t2)
        self.assertIsNone(e2)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_processed_message_reingest_is_idempotent(self):
        raw = build_raw_email(
            "<phase7-3@example.com>", self.sender, "support@example.com",
            "Cannot login", "Password reset link expired.")
        ticket, created, error = self._ingest(raw)
        self.assertTrue(created)
        self.assertEqual(error, None)
        ticket2, created2, error2 = self._ingest(raw)
        self.assertFalse(created2)
        self.assertEqual(ticket2, ticket)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_unsupported_attachment_marks_failed_no_ticket(self):
        raw = build_raw_email(
            "<phase7-4@example.com>", self.sender, "support@example.com",
            "Virus scan", "Please see attachment.")
        ticket, created, error = self._ingest(raw, attachments=[
            {"filename": "evil.exe", "data": b"MZ", "content_type":
             "application/x-msdownload"}])
        self.assertIsNotNone(error)
        self.assertFalse(created)
        self.assertIsNone(ticket)
        proc = EmailProcessing.objects.get(message_id="<phase7-4@example.com>")
        self.assertEqual(proc.status, "failed")
        self.assertTrue(proc.error_details)

    def test_reply_via_ticket_ref_adds_note_not_new_ticket(self):
        raw = build_raw_email(
            "<phase7-5@example.com>", self.sender, "support@example.com",
            "Broken laptop", "Screen will not turn on.")
        ticket, created, error = self._ingest(raw)
        self.assertTrue(created)
        tid = ticket.pk
        reply_raw = build_raw_email(
            "<phase7-6@example.com>", self.sender, "support@example.com",
            f"Re: Broken laptop #{tid}", "The screen is now back.",
            in_reply_to="<phase7-5@example.com>")
        ticket2, created2, error2 = self._ingest(reply_raw)
        self.assertIsNone(error2)
        self.assertFalse(created2)
        self.assertEqual(ticket2, ticket)
        self.assertEqual(Ticket.objects.count(), 1)
        note = TicketNote.objects.filter(ticket=ticket).order_by("-id").first()
        self.assertEqual(note.author, self.emp)
        self.assertFalse(note.is_internal)
        self.assertEqual(note.body, "The screen is now back.")

    def test_staff_reply_is_internal_note(self):
        raw = build_raw_email(
            "<phase7-7@example.com>", self.sender, "support@example.com",
            "Broken laptop", "Screen will not turn on.")
        ticket, created, error = self._ingest(raw)
        tid = ticket.pk
        reply_raw = build_raw_email(
            "<phase7-8@example.com>", "IT <m@x>", "support@example.com",
            f"Re: Broken laptop #{tid}", "We replaced the screen.",
            in_reply_to="<phase7-7@example.com>")
        ticket2, created2, error2 = self._ingest(reply_raw)
        self.assertIsNone(error2)
        self.assertFalse(created2)
        note = TicketNote.objects.filter(ticket=ticket).order_by("-id").first()
        self.assertTrue(note.is_internal)

    def test_unknown_sender_not_eligible(self):
        raw = build_raw_email(
            "<phase7-9@example.com>", "stranger@external.com",
            "support@example.com", "Hello", "Need help.")
        ticket, created, error = self._ingest(raw)
        self.assertIsNotNone(error)
        self.assertFalse(created)
        self.assertEqual(Ticket.objects.count(), 0)
        proc = EmailProcessing.objects.get(message_id="<phase7-9@example.com>")
        self.assertEqual(proc.status, "failed")


@override_settings(**LOC)
class OperationsStatusTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def test_status_requires_it_staff(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/operations/status/")
        self.assertEqual(res.status_code, 403)

    def test_status_returns_email_and_task_health(self):
        EmailProcessing.objects.create(
            message_id="<phase7-x@example.com>", mailbox="support",
            recipient="support@example.com", sender="e@x",
            subject="s", body_preview="b", status="processed",
            processed_at=timezone.now(), ticket_id=None)
        res = self.c.get("/api/common/operations/status/")
        self.assertEqual(res.status_code, 200)
        data = res.data
        self.assertIn("email", data)
        self.assertIn("tasks", data)
        self.assertIn("inbound", data)
        self.assertEqual(data["email"]["pending"], 0)
        self.assertEqual(data["email"]["failed"], 0)
        self.assertEqual(data["email"]["total"], 1)
        self.assertTrue(data["tasks"]["celery_healthy"] is False or
                        isinstance(data["tasks"]["celery_healthy"], bool))
        self.assertIn("recent_runs", data["tasks"])


@override_settings(**LOC)
class OutboundDedupTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_same_ticket_subject_not_sent_twice(self):
        to = self_m = User.objects.create_user(
            username="n@x", email="n@example.com", employee_id="N1",
            password="pw12345678")
        ok1 = account_email.send_ticket_notification(
            to.email, "Ticket #7 created: Broken laptop",
            "Your ticket was created.", ticket_id=7)
        ok2 = account_email.send_ticket_notification(
            to.email, "Ticket #7 created: Broken laptop",
            "Your ticket was created.", ticket_id=7)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertEqual(len(mail.outbox), 1)


@override_settings(**LOC)
class TaskHealthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="HW2")

    def _open_ticket_with_sla(self, priority="high"):
        ticket = Ticket.objects.create(
            title="t", description="d", category=self.tcat, priority=priority,
            status="open", requester=self.emp, sla_due_at=timezone.now()
            + timedelta(hours=1))
        TicketSLA.objects.create(
            priority=priority, target_resolution_hours=24, is_active=True)
        return ticket

    def test_sla_task_records_run_and_sends_breach_email(self):
        from tickets.tasks import check_sla_escalations
        ticket = self._open_ticket_with_sla("high")
        ticket.sla_due_at = timezone.now() - timedelta(hours=30)
        ticket.save(update_fields=["sla_due_at"])
        result = check_sla_escalations.apply(args=[], kwargs={}).get()
        self.assertEqual(result["checked"], 1)
        self.assertTrue(
            BackgroundTaskRun.objects.filter(task_name="tickets.tasks.check_sla_escalations").exists())
        # In-app breach notification + email were created exactly once.
        self.assertTrue(Notification.objects.filter(
            object_id=str(ticket.pk), entity_type="tickets.SLA").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("SLA breached", mail.outbox[0].subject)

    def test_inbound_mailbox_task_disabled_path(self):
        from common.tasks import process_inbound_mailbox
        with override_settings(INBOUND_MAILBOX_ENABLED=False):
            result = process_inbound_mailbox.apply(args=[], kwargs={}).get()
        self.assertEqual(result, {"status": "disabled", "processed": 0,
                                 "fetched": 0})
        self.assertTrue(
            BackgroundTaskRun.objects.filter(
                task_name="common.tasks.process_inbound_mailbox",
                status="succeeded").exists())
