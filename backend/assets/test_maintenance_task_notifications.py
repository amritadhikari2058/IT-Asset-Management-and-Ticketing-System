"""Regression tests for maintenance reminder task notification migration."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.tests import make_users
from assets.models import Asset, AssetCategory, Maintenance, MaintenanceReminder
from assets.tasks import check_maintenance_reminders
from common.models import Notification

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


@override_settings(**LOC)
class MaintenanceReminderTaskNotificationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(
            asset_tag="L-1", name="Laptop 1", category=self.cat,
        )

    def _make_maintenance(self, **overrides):
        values = {
            "asset": self.asset,
            "title": "Disk check",
            "maintenance_type": "preventive",
            "status": "scheduled",
            "scheduled_date": timezone.now() + timedelta(hours=1),
            "assigned_to": self.emp,
            "created_by": self.mgr,
        }
        values.update(overrides)
        return Maintenance.objects.create(**values)

    def test_due_soon_notification_uses_central_contract(self):
        m = self._make_maintenance()

        result = check_maintenance_reminders()
        self.assertGreaterEqual(result["checked"], 1)

        notif = Notification.objects.get(
            recipient=self.emp,
            entity_type="assets.Maintenance",
            object_id=str(m.pk),
        )
        self.assertIn("Maintenance due soon", notif.title)
        self.assertIn(self.asset.asset_tag, notif.body)
        self.assertIsNotNone(notif.dedupe_key)
        self.assertTrue(MaintenanceReminder.objects.filter(maintenance=m, level="before").exists())

    def test_due_soon_notification_is_idempotent(self):
        m = self._make_maintenance()
        check_maintenance_reminders()
        check_maintenance_reminders()

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.emp,
                entity_type="assets.Maintenance",
                object_id=str(m.pk),
            ).count(),
            1,
        )

    def test_overdue_notification_uses_central_contract(self):
        m = self._make_maintenance(
            scheduled_date=timezone.now() - timedelta(hours=2),
        )

        check_maintenance_reminders()

        notif = Notification.objects.get(
            recipient=self.emp,
            entity_type="assets.Maintenance",
            object_id=str(m.pk),
            title__contains="overdue",
        )
        self.assertIn("Maintenance overdue", notif.title)
        self.assertIsNotNone(notif.dedupe_key)
        self.assertTrue(MaintenanceReminder.objects.filter(maintenance=m, level="overdue").exists())

    def test_inactive_recipient_skipped(self):
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        self._make_maintenance()

        check_maintenance_reminders()

        self.assertEqual(Notification.objects.filter(recipient=self.emp).count(), 0)
