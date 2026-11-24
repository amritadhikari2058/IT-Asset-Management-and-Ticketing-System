"""Regression tests for notification reliability (Phase 59)."""
from unittest import mock

from django.core import mail
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone as dj_timezone

from accounts.models import Department, User
from accounts.tests import make_users
from common.models import Notification, UserNotificationPreference
from common.notifications import email_enabled_for, notify_user


class EmailSendBehaviorTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_ticket_notification_returns_true_on_success(self):
        from accounts.email_utils import send_ticket_notification
        ok = send_ticket_notification(self.emp.email, "Subj", "Body", ticket_id=1, user=self.emp)
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_ticket_notification_returns_false_on_send_failure(self):
        from accounts.email_utils import send_ticket_notification
        with mock.patch("common.email.send_mail", side_effect=RuntimeError("smtp down")):
            ok = send_ticket_notification(self.emp.email, "Subj2", "Body", ticket_id=2, user=self.emp)
        self.assertFalse(ok)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_failed_send_does_not_set_dedup_cache(self):
        from accounts.email_utils import send_ticket_notification
        with mock.patch("common.email.send_mail", side_effect=RuntimeError("smtp down")):
            ok1 = send_ticket_notification(self.emp.email, "Subj3", "Body", ticket_id=3, user=self.emp)
        self.assertFalse(ok1)
        ok2 = send_ticket_notification(self.emp.email, "Subj3", "Body", ticket_id=3, user=self.emp)
        self.assertTrue(ok2)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_dedup_cache_prevents_duplicate_on_success(self):
        from accounts.email_utils import send_ticket_notification
        ok1 = send_ticket_notification(self.emp.email, "Subj4", "Body", ticket_id=4, user=self.emp)
        ok2 = send_ticket_notification(self.emp.email, "Subj4", "Body", ticket_id=4, user=self.emp)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertEqual(len(mail.outbox), 1)


class EmailPreferenceTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_essential_category_always_enabled(self):
        prefs, _ = UserNotificationPreference.objects.get_or_create(user=self.emp)
        prefs.email_enabled = False
        prefs.save()
        self.assertTrue(email_enabled_for(self.emp, category="email_verification"))
        self.assertTrue(email_enabled_for(self.emp, category="password_reset"))

    def test_master_switch_disables_non_essential(self):
        prefs, _ = UserNotificationPreference.objects.get_or_create(user=self.emp)
        prefs.email_enabled = False
        prefs.save()
        self.assertFalse(email_enabled_for(self.emp, category="ticket_assignment"))

    def test_category_opt_out_only_affects_that_category(self):
        prefs, _ = UserNotificationPreference.objects.get_or_create(user=self.emp)
        prefs.email_enabled = True
        prefs.categories = {"ticket_assignment": False, "ticket_status_change": True}
        prefs.save()
        self.assertFalse(email_enabled_for(self.emp, category="ticket_assignment"))
        self.assertTrue(email_enabled_for(self.emp, category="ticket_status_change"))

    def test_legacy_receive_ticket_emails_master_fallback(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        self.assertFalse(email_enabled_for(self.emp, category="ticket_assignment"))
        self.assertTrue(email_enabled_for(self.emp, category="password_reset"))


class NotifyUserContractTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_notify_user_post_commit_false_creates_notification(self):
        n = notify_user(self.emp, "ticket_assignment", "Title", "Body", entity_type="tickets.Ticket", object_id="1", post_commit=False)
        self.assertIsNotNone(n)
        self.assertEqual(Notification.objects.filter(recipient=self.emp, title="Title").count(), 1)

    def test_notify_user_invalid_recipient_returns_none(self):
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        n = notify_user(self.emp, "ticket_assignment", "Title", "Body", post_commit=False)
        self.assertIsNone(n)
        self.assertEqual(Notification.objects.filter(recipient=self.emp).count(), 0)

    def test_notify_user_dedupe_prevents_duplicate(self):
        notify_user(self.emp, "ticket_assignment", "Title", "Body", entity_type="tickets.Ticket", object_id="1", post_commit=False)
        notify_user(self.emp, "ticket_assignment", "Title", "Body", entity_type="tickets.Ticket", object_id="1", post_commit=False)
        self.assertEqual(Notification.objects.filter(recipient=self.emp, title="Title").count(), 1)

class NotificationTransactionTests(TransactionTestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_notify_user_post_commit_not_created_on_rollback(self):
        try:
            with transaction.atomic():
                notify_user(self.emp, "ticket_assignment", "Rollback", "Body", entity_type="tickets.Ticket", object_id="99", post_commit=True)
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        self.assertEqual(Notification.objects.filter(recipient=self.emp, title="Rollback").count(), 0)

    def test_notify_user_post_commit_created_on_commit(self):
        with transaction.atomic():
            notify_user(self.emp, "ticket_assignment", "Committed", "Body", entity_type="tickets.Ticket", object_id="100", post_commit=True)
        self.assertEqual(Notification.objects.filter(recipient=self.emp, title="Committed").count(), 1)

    def test_maintenance_reminder_notification_not_created_on_rollback(self):
        from accounts.email_utils import _notify_maintenance_reminder
        from assets.models import Asset, AssetCategory, Maintenance

        cat = AssetCategory.objects.create(name="Laptop")
        asset = Asset.objects.create(asset_tag="M1", name="A1", category=cat)
        maint = Maintenance.objects.create(
            asset=asset, title="Fix", maintenance_type="preventive",
            status="scheduled", scheduled_date=dj_timezone.now() + dj_timezone.timedelta(days=1),
            assigned_to=self.emp,
        )
        try:
            with transaction.atomic():
                _notify_maintenance_reminder(maint)
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        self.assertEqual(Notification.objects.filter(recipient=self.emp, entity_type="assets.Maintenance", object_id=str(maint.pk)).count(), 0)

    def test_notify_user_outside_transaction_runs_immediately(self):
        # In autocommit mode (no open transaction), on_commit runs immediately in Django.
        notify_user(self.emp, "ticket_assignment", "Immediate", "Body", entity_type="tickets.Ticket", object_id="101", post_commit=True)
        self.assertEqual(Notification.objects.filter(recipient=self.emp, title="Immediate").count(), 1)


class TicketEmailTransactionBoundaryTests(TransactionTestCase):
    """Phase 60: ticket emails must not be sent/scheduled for rolled-back outer transactions."""

    def setUp(self):
        from rest_framework.test import APIClient
        from tickets.models import TicketCategory
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="General")
        self.client = APIClient()

    def _create_ticket(self, user, **overrides):
        self.client.force_authenticate(user=user)
        payload = {
            "title": "Tx boundary",
            "description": "desc",
            "priority": "medium",
            "category": self.cat.pk,
        }
        payload.update(overrides)
        return self.client.post("/api/tickets/", payload, format="json")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_ticket_create_email_sent_after_outer_commit(self):
        # Outer atomic commits: email should be delivered exactly once.
        with transaction.atomic():
            res = self._create_ticket(self.mgr, assignee=self.admin.pk)
            self.assertEqual(res.status_code, 201)
            # Still inside outer transaction - must not have sent yet.
            self.assertEqual(len(mail.outbox), 0)
        # After outer commit, on_commit callbacks have run.
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee
        ticket_id = res.data["id"]
        from tickets.models import Ticket
        self.assertTrue(Ticket.objects.filter(pk=ticket_id).exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_ticket_create_email_not_sent_on_outer_rollback(self):
        from tickets.models import Ticket
        before = Ticket.objects.count()
        try:
            with transaction.atomic():
                res = self._create_ticket(self.mgr, assignee=self.admin.pk)
                self.assertEqual(res.status_code, 201)
                self.assertEqual(len(mail.outbox), 0)
                raise RuntimeError("force outer rollback")
        except RuntimeError:
            pass
        self.assertEqual(Ticket.objects.count(), before)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_ticket_update_status_email_sent_after_outer_commit(self):
        # Create ticket first (committed).
        res = self._create_ticket(self.emp)
        self.assertEqual(res.status_code, 201)
        ticket_id = res.data["id"]
        mail.outbox.clear()

        self.client.force_authenticate(user=self.mgr)
        with transaction.atomic():
            upd = self.client.patch(
                f"/api/tickets/{ticket_id}/",
                {"status": "in_progress"},
                format="json",
            )
            self.assertEqual(upd.status_code, 200)
            self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("status", mail.outbox[0].subject.lower())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_ticket_update_status_email_not_sent_on_outer_rollback(self):
        from tickets.models import Ticket
        res = self._create_ticket(self.emp)
        self.assertEqual(res.status_code, 201)
        ticket_id = res.data["id"]
        mail.outbox.clear()

        self.client.force_authenticate(user=self.mgr)
        try:
            with transaction.atomic():
                upd = self.client.patch(
                    f"/api/tickets/{ticket_id}/",
                    {"status": "in_progress"},
                    format="json",
                )
                self.assertEqual(upd.status_code, 200)
                self.assertEqual(len(mail.outbox), 0)
                raise RuntimeError("force outer rollback")
        except RuntimeError:
            pass
        self.assertEqual(len(mail.outbox), 0)
        t = Ticket.objects.get(pk=ticket_id)
        self.assertEqual(t.status, "open")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_ticket_create_email_no_duplicate_on_commit(self):
        # A single create should schedule/send exactly the expected emails once.
        with transaction.atomic():
            res = self._create_ticket(self.mgr, assignee=self.admin.pk)
            self.assertEqual(res.status_code, 201)
        # requester + assignee = 2, no duplicates
        self.assertEqual(len(mail.outbox), 2)
        recipients = sorted([m.to[0] for m in mail.outbox])
        self.assertEqual(recipients, sorted([self.mgr.email, self.admin.email]))


class BulkImportEmailTransactionBoundaryTests(TransactionTestCase):
    """Phase 60/64: bulk import emails must respect outer transaction boundaries."""

    def setUp(self):
        from rest_framework.test import APIClient
        from tickets.models import TicketCategory
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="General")
        self.client = APIClient()

    def _bulk_confirm(self, rows, user=None):
        self.client.force_authenticate(user=user or self.mgr)
        return self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": rows, "preview": False, "confirm": True},
            format="json",
        )

    def _row(self, **kw):
        base = {
            "title": "Bulk Tx",
            "description": "desc",
            "priority": "medium",
            "category": self.cat.pk,
            "department": self.dep.pk,
        }
        base.update(kw)
        return base

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_bulk_import_commit_sends_emails_after_outer_commit(self):
        from tickets.models import Ticket
        rows = [self._row(title="B1", assignee=self.admin.pk)]
        with transaction.atomic():
            res = self._bulk_confirm(rows)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data["summary"]["ok"], 1)
            self.assertEqual(len(mail.outbox), 0)  # not before outer commit
        self.assertEqual(len(mail.outbox), 2)  # requester + assignee
        self.assertEqual(Ticket.objects.filter(title="B1").count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_bulk_import_outer_rollback_sends_no_emails(self):
        from tickets.models import Ticket
        before = Ticket.objects.count()
        try:
            with transaction.atomic():
                res = self._bulk_confirm([self._row(title="B2", assignee=self.admin.pk)])
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.data["summary"]["ok"], 1)
                self.assertEqual(len(mail.outbox), 0)
                raise RuntimeError("force outer rollback")
        except RuntimeError:
            pass
        self.assertEqual(Ticket.objects.count(), before)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_bulk_import_multiple_rows_no_loop_variable_capture(self):
        from tickets.models import Ticket
        rows = [
            self._row(title="RowA", assignee=self.admin.pk),
            self._row(title="RowB", assignee=self.emp.pk),
        ]
        with transaction.atomic():
            res = self._bulk_confirm(rows)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data["summary"]["ok"], 2)
        # Each row: requester(mgr) + assignee = 2 emails, 2 rows = 4 total
        self.assertEqual(len(mail.outbox), 4)
        bodies = [m.body for m in mail.outbox]
        self.assertTrue(any("RowA" in b for b in bodies))
        self.assertTrue(any("RowB" in b for b in bodies))
        # Assignee emails should go to correct assignees with correct row content
        assignee_msgs = [m for m in mail.outbox if "assigned to you" in m.subject.lower()]
        self.assertTrue(any(self.admin.email in m.to and "RowA" in m.body for m in assignee_msgs))
        self.assertTrue(any(self.emp.email in m.to and "RowB" in m.body for m in assignee_msgs))
        self.assertEqual(Ticket.objects.filter(title__in=["RowA", "RowB"]).count(), 2)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_bulk_import_callback_failure_does_not_corrupt_committed_data(self):
        from tickets.models import Ticket
        with mock.patch("common.notification_delivery.send_ticket_notification", side_effect=RuntimeError("smtp down")):
            with transaction.atomic():
                res = self._bulk_confirm([self._row(title="B3", assignee=self.admin.pk)])
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.data["summary"]["ok"], 1)
        # Committed ticket remains; callback exceptions swallowed.
        self.assertEqual(Ticket.objects.filter(title="B3").count(), 1)
