"""Tests for Licensing Celery Background Tasks."""

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, User
from common.models import BackgroundTaskRun, Notification
from licensing.models import LicenseAgreement, SoftwareProduct
from licensing.tasks import evaluate_license_compliance_task, evaluate_license_deadlines


class LicensingTasksTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="IT Services", code="IT01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com", email="admin@test.com", employee_id="ADM-001", role="system_admin", home_department=self.dept
        )
        self.mgr = User.objects.create_user(
            username="mgr@test.com", email="mgr@test.com", employee_id="MGR-001", role="it_manager", home_department=self.dept
        )

        self.product = SoftwareProduct.objects.create(
            name="Zoom Enterprise",
            publisher="Zoom Video Communications",
            category="communication",
            approved_status="approved",
            created_by=self.sys_admin,
        )

    def test_evaluate_license_deadlines_transitions_status_and_notifies(self):
        """Agreements within notice window transition to 'expiring' and notify owners."""
        today = timezone.now().date()
        # Agreement expiring in 15 days, notice window 30 days
        agr = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-DEADLINE-01",
            software_product=self.product,
            status="active",
            expiry_date=today + timezone.timedelta(days=15),
            renewal_notice_days=30,
            owner=self.mgr,
            contract_manager=self.sys_admin,
            created_by=self.sys_admin,
        )

        # Execute task directly (safe in test environment without live Celery)
        payload = evaluate_license_deadlines()
        self.assertGreaterEqual(payload["agreements_expiring_transitioned"], 1)

        agr.refresh_from_db()
        self.assertEqual(agr.status, "expiring")

        # Verify notification dispatched to owner
        notif = Notification.objects.filter(
            recipient=self.mgr,
            entity_type="licensing.LicenseAgreement",
            object_id=str(agr.pk),
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Renewal Notice", notif.title)

        # Verify BackgroundTaskRun record
        run = BackgroundTaskRun.objects.filter(task_name="licensing.tasks.evaluate_license_deadlines").first()
        self.assertIsNotNone(run)
        self.assertTrue(run.success)
        self.assertEqual(run.status, "succeeded")

        # Re-running task suppresses duplicate notifications
        payload2 = evaluate_license_deadlines()
        self.assertEqual(payload2["notifications_dispatched"], 0)

    def test_evaluate_license_compliance_task_expires_past_grace(self):
        """Agreements past expiry date and grace period are transitioned to 'expired'."""
        today = timezone.now().date()
        # Expired 5 days ago, grace period 2 days
        agr = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-EXPIRED-01",
            software_product=self.product,
            status="expiring",
            expiry_date=today - timezone.timedelta(days=5),
            grace_period_days=2,
            created_by=self.sys_admin,
        )

        payload = evaluate_license_compliance_task()
        self.assertGreaterEqual(payload["agreements_expired"], 1)

        agr.refresh_from_db()
        self.assertEqual(agr.status, "expired")

        run = BackgroundTaskRun.objects.filter(task_name="licensing.tasks.evaluate_license_compliance_task").first()
        self.assertIsNotNone(run)
        self.assertTrue(run.success)

    def test_deadline_notification_uses_central_contract(self):
        """Migrated deadline notification has correct fields and dedupe=False semantics."""
        today = timezone.now().date()
        agr = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-DEADLINE-CONTRACT-01",
            software_product=self.product,
            status="active",
            expiry_date=today + timezone.timedelta(days=15),
            renewal_notice_days=30,
            owner=self.mgr,
            contract_manager=self.sys_admin,
            created_by=self.sys_admin,
        )

        payload = evaluate_license_deadlines()
        self.assertGreaterEqual(payload["notifications_dispatched"], 1)

        notif = Notification.objects.get(
            recipient=self.mgr,
            entity_type="licensing.LicenseAgreement",
            object_id=str(agr.pk),
        )
        self.assertEqual(notif.recipient_id, self.mgr.pk)
        self.assertIn("Renewal Notice", notif.title)
        self.assertIn(agr.agreement_number, notif.body)
        self.assertIsNone(notif.dedupe_key)

        # 7-day window suppresses repeat; moving the notification outside the
        # window allows a legitimate reminder (dedupe=False, time-windowed).
        Notification.objects.filter(
            recipient=self.mgr,
            entity_type="licensing.LicenseAgreement",
            object_id=str(agr.pk),
        ).update(created_at=timezone.now() - timezone.timedelta(days=8))
        LicenseAgreement.objects.filter(pk=agr.pk).update(status="active")
        payload2 = evaluate_license_deadlines()
        self.assertGreaterEqual(payload2["notifications_dispatched"], 1)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.mgr,
                entity_type="licensing.LicenseAgreement",
                object_id=str(agr.pk),
            ).count(),
            2,
        )
