"""Regression tests for notification-related authorization boundaries."""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from common.models import (Notification, SavedReport, ScheduledReport,
                           UserNotificationPreference)
from tickets.models import TicketCategory


class NotificationAuthorizationHardeningTests(TestCase):

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.client = APIClient()
        self.category = TicketCategory.objects.create(name="PH62")
        self.shared_report = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category", name="Shared",
            filters={"category": self.category.pk}, is_shared=True)

    def _schedule(self, report, **overrides):
        values = {
            "saved_report": report,
            "schedule": "weekly",
            "recipients": ["reports@example.com"],
            "format": "csv",
            "enabled": True,
        }
        values.update(overrides)
        return ScheduledReport.objects.create(**values)

    def test_anonymous_notification_related_access_is_denied(self):
        for path in (
                "/api/common/notifications/",
                "/api/common/notification-preferences/",
                "/api/common/scheduled-reports/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_notification_content_is_immutable_and_creation_is_disabled(self):
        notification = Notification.objects.create(
            recipient=self.emp, title="System message", body="Original body",
            entity_type="tickets.Ticket", object_id="7")
        auth(self.client, self.emp)

        update = self.client.patch(
            f"/api/common/notifications/{notification.pk}/",
            {"title": "Forged message", "body": "Forged body",
             "entity_type": "assets.Asset", "object_id": "999",
             "recipient": self.mgr.pk,
             "created_at": "2000-01-01T00:00:00Z",
             "is_deleted": True, "dedupe_key": "forged",
             "is_read": True}, format="json")
        self.assertEqual(update.status_code, 200)
        notification.refresh_from_db()
        self.assertEqual(notification.title, "System message")
        self.assertEqual(notification.body, "Original body")
        self.assertEqual(notification.entity_type, "tickets.Ticket")
        self.assertEqual(notification.object_id, "7")
        self.assertEqual(notification.recipient_id, self.emp.pk)
        self.assertTrue(notification.is_read)
        self.assertFalse(notification.is_deleted)
        self.assertNotEqual(notification.dedupe_key, "forged")

        create = self.client.post(
            "/api/common/notifications/",
            {"title": "Forged message", "body": "Forged body"},
            format="json")
        self.assertEqual(create.status_code, 405)

    def test_it_staff_cannot_edit_other_users_preferences(self):
        prefs = UserNotificationPreference.objects.create(
            user=self.emp, email_enabled=False, categories={})

        for actor in (self.mgr, self.admin):
            with self.subTest(actor=actor.role):
                auth(self.client, actor)
                response = self.client.patch(
                    f"/api/common/notification-preferences/{prefs.pk}/",
                    {"email_enabled": True}, format="json")
                self.assertEqual(response.status_code, 403)
                prefs.refresh_from_db()
                self.assertFalse(prefs.email_enabled)

    def test_staff_can_still_edit_own_notification_preferences(self):
        prefs = UserNotificationPreference.objects.create(
            user=self.mgr, email_enabled=False, categories={})
        auth(self.client, self.mgr)
        response = self.client.patch(
            f"/api/common/notification-preferences/{prefs.pk}/",
            {"email_enabled": True}, format="json")
        self.assertEqual(response.status_code, 200)
        prefs.refresh_from_db()
        self.assertTrue(prefs.email_enabled)

    def test_employee_cannot_update_or_delete_shared_report_schedule(self):
        schedule = self._schedule(self.shared_report)
        auth(self.client, self.emp)

        update = self.client.patch(
            f"/api/common/scheduled-reports/{schedule.pk}/",
            {"enabled": False}, format="json")
        self.assertEqual(update.status_code, 403)
        delete = self.client.delete(
            f"/api/common/scheduled-reports/{schedule.pk}/")
        self.assertEqual(delete.status_code, 403)

        schedule.refresh_from_db()
        self.assertTrue(schedule.enabled)

    def test_employee_can_update_schedule_for_owned_report(self):
        own_report = SavedReport.objects.create(
            user=self.emp, report_type="ticket_category", name="Mine",
            filters={"category": self.category.pk})
        schedule = self._schedule(own_report)
        auth(self.client, self.emp)

        response = self.client.patch(
            f"/api/common/scheduled-reports/{schedule.pk}/",
            {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200)
        schedule.refresh_from_db()
        self.assertFalse(schedule.enabled)

    def test_employee_cannot_reassign_owned_schedule_to_shared_report(self):
        own_report = SavedReport.objects.create(
            user=self.emp, report_type="ticket_category", name="Mine",
            filters={"category": self.category.pk})
        schedule = self._schedule(own_report)
        auth(self.client, self.emp)

        response = self.client.patch(
            f"/api/common/scheduled-reports/{schedule.pk}/",
            {"saved_report": self.shared_report.pk}, format="json")
        self.assertEqual(response.status_code, 403)
        schedule.refresh_from_db()
        self.assertEqual(schedule.saved_report_id, own_report.pk)

    def test_it_staff_can_manage_schedule_for_shared_report(self):
        schedule = self._schedule(self.shared_report)
        auth(self.client, self.mgr)

        response = self.client.patch(
            f"/api/common/scheduled-reports/{schedule.pk}/",
            {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200)
        schedule.refresh_from_db()
        self.assertFalse(schedule.enabled)
