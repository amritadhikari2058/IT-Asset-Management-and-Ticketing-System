"""Email, privacy-erasure, and attachment-storage tests."""
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from common.models import Notification
from tickets.models import Ticket, TicketCategory

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


@override_settings(**LOC)
class EmailFlowTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_reset_request_generic_for_unknown(self):
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "nobody@nowhere"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("If an account exists", res.data["detail"])
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_request_sends_for_known(self):
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["detail"],
                         "If an account exists for that email, a reset link "
                         "has been sent.")
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_confirm_invalid_then_valid(self):
        from accounts.email_utils import (
            decode_uid,  # noqa (ensures helpers import cleanly)
        )
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.emp.pk))
        bad = self.c.post("/api/accounts/password-reset/confirm/",
                          {"uid": uid, "token": "bad",
                           "new_password": "newpass123"}, format="json")
        self.assertEqual(bad.status_code, 400)
        token = PasswordResetTokenGenerator().make_token(self.emp)
        ok = self.c.post("/api/accounts/password-reset/confirm/",
                         {"uid": uid, "token": token,
                          "new_password": "newpass123"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("newpass123"))

    def test_verification_flow(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        import re
        m = re.search(r"uid=(\S+)&token=(\S+)", body)
        uid, token = m.group(1), m.group(2)
        res = self.c.get(
            f"/api/accounts/verify-email/confirm/?uid={uid}&token={token}")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.email_verified)
        bad = self.c.get(
            "/api/accounts/verify-email/confirm/?uid=x&token=y")
        self.assertEqual(bad.status_code, 400)

    def test_ticket_create_sends_notification_but_never_blocks(self):
        auth(self.c, self.mgr)
        tcat = TicketCategory.objects.create(name="EM")
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": tcat.pk,
                           "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(len(mail.outbox) >= 1)


class PrivacyErasureTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/common/privacy-erasures/",
                          {"entity_type": "accounts.User",
                           "object_id": str(self.emp.pk),
                           "scope": "email", "reason": "x",
                           "confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_create_requires_confirm_reason_scope(self):
        auth(self.c, self.admin)
        base = {"entity_type": "accounts.User",
                "object_id": str(self.emp.pk)}
        r1 = self.c.post("/api/common/privacy-erasures/",
                         {**base, "scope": "email", "reason": "r"},
                         format="json")
        self.assertEqual(r1.status_code, 400)
        r2 = self.c.post("/api/common/privacy-erasures/",
                         {**base, "scope": "", "reason": "r",
                          "confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(r2.status_code, 400)

    def test_execute_anonymizes_without_logging_pii(self):
        from common.models import AuditLog
        auth(self.c, self.admin)
        original_email = self.emp.email
        res = self.c.post("/api/common/privacy-erasures/",
                          {"entity_type": "accounts.User",
                           "object_id": str(self.emp.pk),
                           "scope": "email, name, phone",
                           "reason": "privacy request #1",
                           "confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(res.status_code, 201)
        rid = res.data["id"]
        detail = self.c.get(f"/api/common/privacy-erasures/{rid}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("dependency_check", detail.data)
        ex = self.c.post(f"/api/common/privacy-erasures/{rid}/execute/",
                         {"confirm": str(self.emp.pk)}, format="json")
        self.assertEqual(ex.status_code, 200)
        self.emp.refresh_from_db()
        self.assertNotEqual(self.emp.email, original_email)
        self.assertFalse(self.emp.is_active)
        # Audit trail holds IDs + scope, never the erased address.
        logs = AuditLog.objects.filter(
            entity_type="common.PrivacyErasureRequest")
        self.assertTrue(logs.exists())
        for log in logs:
            blob = f"{log.details}{log.reason}{log.object_repr}"
            self.assertNotIn(original_email, blob)


@override_settings(**LOC)
class AttachmentStorageTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=self.mgr, department=self.dep)

    def tearDown(self):
        # Remove backing files uploaded during the test. This only touches
        # files referenced by rows in the *test* database, never real user
        # uploads in the dev/prod media directory. gc + retries handle
        # Windows file locks from just-closed download responses.
        import gc
        import time
        gc.collect()
        from tickets.models import TicketAttachment
        for att in TicketAttachment.all_objects.all():
            try:
                if att.file:
                    name = att.file.name
                    try:
                        att.file.close()
                    except Exception:
                        pass
                    for _ in range(5):
                        try:
                            att.file.storage.delete(name)
                        except Exception:
                            time.sleep(0.05)
                            continue
                        break
            except Exception:
                pass

    def test_executable_and_bad_extension_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        auth(self.c, self.mgr)
        t = self._ticket()
        bad = SimpleUploadedFile("evil.exe", b"data",
                                 content_type="application/octet-stream")
        res = self.c.post("/api/tickets/attachments/",
                          {"ticket": t.pk, "file": bad}, format="multipart")
        self.assertEqual(res.status_code, 400)

    def test_safe_filename_and_private_download(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        auth(self.c, self.mgr)
        t = self._ticket()
        up = SimpleUploadedFile("../../note.txt", b"hello",
                                content_type="text/plain")
        res = self.c.post("/api/tickets/attachments/",
                          {"ticket": t.pk, "file": up}, format="multipart")
        self.assertEqual(res.status_code, 201)
        aid = res.data["id"]
        from tickets.models import TicketAttachment
        att = TicketAttachment.objects.get(pk=aid)
        # No traversal, uuid name under ticket_attachments/. (Browsers and
        # Django strip client paths, so the stored name is what matters.)
        self.assertTrue(att.file.name.startswith("ticket_attachments/"))
        self.assertNotIn("..", att.file.name)
        self.assertTrue(att.original_filename.endswith("note.txt"))
        # Owner-side download works with permission check.
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        dl.close()  # release the file handle (Windows locks open files)
        # Employee from another scope cannot list/download it.
        from accounts.models import Department
        other = Department.objects.create(name="Other", code="OTH")
        self.emp.home_department = other
        self.emp.save()
        auth(self.c, self.emp)
        dl2 = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl2.status_code, 404)
        # Soft delete keeps the physical file.
        auth(self.c, self.mgr)
        self.c.delete(f"/api/tickets/attachments/{aid}/")
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)
        self.assertTrue(att.file.storage.exists(att.file.name))


class NotificationReadTests(TestCase):
    """mark_all_read: own notifications only, idempotent, no dismissal."""

    def setUp(self):
        from common.models import Notification
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        for i in range(2):
            Notification.objects.create(recipient=self.emp, title=f"e{i}")
        Notification.objects.create(recipient=self.emp, title="read",
                                    is_read=True)
        Notification.objects.create(recipient=self.mgr, title="m0")
        dismissed = Notification.objects.create(recipient=self.emp,
                                                title="gone")
        dismissed.soft_delete(by_user=self.emp, reason="dismissed")

    def _unread(self, user):
        from common.models import Notification
        return Notification.objects.filter(recipient=user,
                                           is_read=False).count()

    def test_mark_all_read_updates_own_unread(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/common/notifications/mark_all_read/",
                          {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {"updated": 2})
        self.assertEqual(self._unread(self.emp), 0)
        # Another user's notifications untouched.
        self.assertEqual(self._unread(self.mgr), 1)

    def test_mark_all_read_idempotent(self):
        auth(self.c, self.emp)
        self.c.post("/api/common/notifications/mark_all_read/",
                    {}, format="json")
        res = self.c.post("/api/common/notifications/mark_all_read/",
                          {}, format="json")
        self.assertEqual(res.data, {"updated": 0})

    def test_mark_all_read_is_not_dismissal(self):
        from common.models import Notification
        auth(self.c, self.emp)
        self.c.post("/api/common/notifications/mark_all_read/",
                    {}, format="json")
        mine = Notification.objects.filter(recipient=self.emp)
        self.assertEqual(mine.count(), 3)  # dismissed row stays deleted
        self.assertTrue(all(n.is_read for n in mine))

    def test_mark_all_read_requires_auth(self):
        res = self.c.post("/api/common/notifications/mark_all_read/",
                          {}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_single_mark_read_still_works(self):
        from common.models import Notification
        auth(self.c, self.emp)
        n = Notification.objects.filter(recipient=self.emp,
                                        is_read=False).first()
        res = self.c.patch(f"/api/common/notifications/{n.pk}/",
                           {"is_read": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._unread(self.emp), 1)


@override_settings(**LOC)
class TicketEmailPreferenceTests(TestCase):
    """Opt out of ticket-event emails only; nothing else changes."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="AT")

    def _ticket(self, requester=None):
        return Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=requester or self.emp, department=self.dep)

    def test_default_enabled_for_new_and_existing(self):
        self.assertTrue(User._meta.get_field(
            "receive_ticket_emails").default)
        for u in (self.admin, self.mgr, self.emp):
            u.refresh_from_db()
            self.assertTrue(u.receive_ticket_emails)
        fresh = User.objects.create_user(
            username="n@x", email="n@example.com", employee_id="N1",
            password="pw12345678")
        self.assertTrue(fresh.receive_ticket_emails)

    def test_opted_in_assignee_gets_create_email(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": self.tcat.pk,
                           "department": self.dep.pk,
                           "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee

    def test_opted_out_assignee_skips_email_only(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": self.tcat.pk,
                           "department": self.dep.pk,
                           "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(len(mail.outbox), 1)  # requester only
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])
        # In-app notification still created for the assignee.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_opted_out_requester_skips_status_email(self):
        t = self._ticket()
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())

    def test_bulk_update_sends_no_email_but_notifies(self):
        t1 = self._ticket()
        e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)
        t2 = Ticket.objects.create(
            title="u", description="d", category=self.tcat,
            requester=e2, department=self.dep)
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t1.pk, t2.pk],
                           "changes": {"status": "in_progress"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t1.pk)).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=e2, object_id=str(t2.pk)).exists())

    def test_self_service_only_and_no_mass_assignment(self):
        auth(self.c, self.emp)
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["receive_ticket_emails"])
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)
        self.mgr.refresh_from_db()
        self.assertTrue(self.mgr.receive_ticket_emails)
        # Protected fields cannot ride along; invalid values rejected.
        res = self.c.patch("/api/accounts/me/", {"role": "system_admin"},
                           format="json")
        self.assertEqual(res.status_code, 400)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.role, "employee")
        res = self.c.patch("/api/accounts/me/",
                           {"receive_ticket_emails": "maybe"},
                           format="json")
        self.assertEqual(res.status_code, 400)

    def test_other_flows_do_not_reset_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.admin)
        res = self.c.post(f"/api/accounts/users/{self.emp.pk}/change_role/",
                          {"role": "employee",
                           "can_create_tickets": True}, format="json")
        self.assertEqual(res.status_code, 200)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/accounts/users/{self.emp.pk}/",
                           {"phone": "111"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_update/",
                          {"rows": [{"employee_id": "E1", "phone": "222"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.c.post("/api/accounts/users/bulk_import/",
                          {"rows": [{"employee_id": "E1",
                                      "email": "newmail@example.com",
                                      "phone": "333"}],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.receive_ticket_emails)

    def test_verification_and_reset_ignore_preference(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.emp)
        res = self.c.post("/api/accounts/verify-email/request/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        res = self.c.post("/api/accounts/password-reset/request/",
                          {"email": "e@x"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)


class AuditLogFilterTests(TestCase):
    def setUp(self):
        from common.models import AuditLog

        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        AuditLog.objects.create(actor=self.admin, action="create",
                                entity_type="tickets.Ticket", object_id="1")
        AuditLog.objects.create(actor=self.mgr, action="update",
                                entity_type="assets.Asset", object_id="2")

    def _rows(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        return data["results"] if isinstance(data, dict) else data

    def test_admin_sees_all(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get("/api/common/audit-logs/"))
        self.assertEqual(len(rows), 2)

    def test_non_admin_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/audit-logs/")
        self.assertEqual(res.status_code, 403)

    def test_filter_action(self):
        auth(self.c, self.admin)
        rows = self._rows(
            self.c.get("/api/common/audit-logs/", {"action": "create"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "create")

    def test_filter_action_rejects_unknown(self):
        auth(self.c, self.admin)
        res = self.c.get("/api/common/audit-logs/",
                         {"action": "drop table"})
        self.assertEqual(res.status_code, 400)

    def test_filter_entity_type(self):
        auth(self.c, self.admin)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"entity_type": "assets.Asset"}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "assets.Asset")

    def test_filter_dates(self):
        from django.utils import timezone

        auth(self.c, self.admin)
        today = timezone.now().date().isoformat()
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": today}))
        self.assertEqual(len(rows), 2)
        rows = self._rows(self.c.get(
            "/api/common/audit-logs/", {"date_from": "2999-01-01"}))
        self.assertEqual(rows, [])
        res = self.c.get("/api/common/audit-logs/",
                         {"date_from": "not-a-date"})
        self.assertEqual(res.status_code, 400)
