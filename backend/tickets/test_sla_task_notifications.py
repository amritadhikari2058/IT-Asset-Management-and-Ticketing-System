"""Regression tests for SLA escalation task notification migration."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.tests import make_users
from common.models import Notification
from tickets.models import SLAEscalation, Ticket, TicketCategory, TicketSLA
from tickets.tasks import check_sla_escalations

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


@override_settings(**LOC)
class SLAEscalationTaskNotificationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.cat = TicketCategory.objects.create(name="General")
        TicketSLA.objects.create(
            priority="high",
            target_resolution_hours=4,
            escalation_hours=1,
            breach_hours=1,
            is_active=True,
        )

    def _make_ticket(self, **overrides):
        values = {
            "title": "VPN down",
            "description": "Cannot connect",
            "category": self.cat,
            "priority": "high",
            "status": "open",
            "requester": self.emp,
            "assignee": self.mgr,
            "department": self.dep,
        }
        values.update(overrides)
        return Ticket.objects.create(**values)

    def test_breach_notification_uses_central_contract(self):
        ticket = self._make_ticket(
            sla_due_at=timezone.now() - timedelta(hours=6),
        )

        check_sla_escalations()

        notif = Notification.objects.get(
            recipient=self.mgr,
            entity_type="tickets.SLA",
            object_id=str(ticket.pk),
            title__contains="SLA breached",
        )
        self.assertIn("SLA breached", notif.title)
        self.assertIn(f"Ticket #{ticket.pk}", notif.body)
        self.assertIsNotNone(notif.dedupe_key)
        self.assertTrue(
            SLAEscalation.objects.filter(ticket=ticket, level="breach").exists()
        )

    def test_breach_notification_is_idempotent(self):
        ticket = self._make_ticket(
            sla_due_at=timezone.now() - timedelta(hours=6),
        )
        check_sla_escalations()
        check_sla_escalations()

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.mgr,
                entity_type="tickets.SLA",
                object_id=str(ticket.pk),
                title__contains="SLA breached",
            ).count(),
            1,
        )

    def test_approaching_notification_uses_central_contract(self):
        ticket = self._make_ticket(
            sla_due_at=timezone.now() + timedelta(minutes=30),
        )

        check_sla_escalations()

        notif = Notification.objects.get(
            recipient=self.mgr,
            entity_type="tickets.SLA",
            object_id=str(ticket.pk),
            title__contains="SLA approaching",
        )
        self.assertIsNotNone(notif.dedupe_key)
        self.assertTrue(
            SLAEscalation.objects.filter(ticket=ticket, level="approach").exists()
        )
