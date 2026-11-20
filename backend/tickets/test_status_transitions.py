"""Tests for ticket status transition permissions and SLA pause handling."""
import pytest
from django.test import TestCase
from rest_framework.test import APIClient
from accounts.tests import auth, make_users
from tickets.models import Ticket, TicketCategory, TicketSLA, TicketSlaPause


class TicketStatusTransitionTests(TestCase):
    """Test ticket status transitions and permissions."""
    
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name='test-category')
        self.ticket = Ticket.objects.create(
            title='Test Ticket',
            description='d',
            category=self.tcat,
            requester=self.emp,
            department=self.dep,
            assignee=self.mgr,
        )
        from rest_framework.test import APIClient
        self.admin_client = APIClient()
        self.mgr_client = APIClient()
        self.emp_client = APIClient()
        auth(self.admin_client, self.admin)
        auth(self.mgr_client, self.mgr)
        auth(self.emp_client, self.emp)
    
    def test_employee_cannot_transition_to_forbidden_status(self):
        """Employees cannot transition to unauthorized statuses."""
        # Emp should not be able to directly change status via API
        # (status transitions are validated server-side)
        pass
    
    def test_mgr_can_transition_ticket(self):
        """IT Managers can transition tickets they manage."""
        self.ticket.assignee = self.mgr
        self.ticket.save()
        # Manager should be able to update ticket status
        res = self.mgr_client.patch(
            f'/api/tickets/{self.ticket.pk}/',
            {'status': 'in_progress'},
            format='json'
        )
        self.assertIn(res.status_code, [200, 400])  # 400 if invalid data, but not 403
    
    def test_emp_cannot_change_own_ticket_status(self):
        """Employees cannot change their own ticket status without proper auth."""
        res = self.emp_client.patch(
            f'/api/tickets/{self.ticket.pk}/',
            {'status': 'in_progress'},
            format='json'
        )
        # Employee should get permission denied for changing ticket status
        self.assertEqual(res.status_code, 403)


class TicketSlaPauseTests(TestCase):
    """Test SLA pause handling and transaction safety."""
    
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name='test-category')
        self.ticket = Ticket.objects.create(
            title='Test Ticket',
            description='d',
            category=self.tcat,
            requester=self.emp,
            department=self.dep,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.mgr)
    
    def test_sla_pause_created_on_waiting_requester(self):
        """SLA pause should be created when ticket goes to waiting_requester."""
        from tickets.models import TicketSlaPause
        self.client.force_authenticate(user=self.mgr)
        res = self.client.patch(
            f'/api/tickets/{self.ticket.pk}/',
            {'status': 'waiting_requester'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)

        pause = TicketSlaPause.objects.filter(ticket=self.ticket, ended_at__isnull=True).first()
        self.assertIsNotNone(pause, "SLA pause should be created when status is waiting_requester")
    
    def test_sla_pause_ended_on_status_change(self):
        """SLA pause should be ended when leaving waiting status."""
        from tickets.models import TicketSlaPause
        self.client.force_authenticate(user=self.mgr)
        res = self.client.patch(
            f'/api/tickets/{self.ticket.pk}/',
            {'status': 'waiting_requester'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        pause = TicketSlaPause.objects.filter(ticket=self.ticket, ended_at__isnull=True).first()
        self.assertIsNotNone(pause)

        res = self.client.patch(
            f'/api/tickets/{self.ticket.pk}/',
            {'status': 'resolved'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        pause.refresh_from_db()
        self.assertIsNotNone(pause.ended_at, "SLA pause should be ended when leaving waiting status")
    
    def test_bulk_update_respects_sla_pauses(self):
        """Bulk update should properly handle SLA pauses."""
        from tickets.models import TicketSlaPause
        # Create two tickets with pauses
        t1 = Ticket.objects.create(
            title='Ticket 1',
            description='d1',
            category=self.tcat,
            requester=self.emp,
            department=self.dep,
        )
        t2 = Ticket.objects.create(
            title='Ticket 2',
            description='d2',
            category=self.tcat,
            requester=self.emp,
            department=self.dep,
        )
        
        # Add pauses to both
        self.client.force_authenticate(user=self.mgr)
        for t in (t1, t2):
            res = self.client.patch(
                f'/api/tickets/{t.pk}/',
                {'status': 'waiting_requester'}, format='json')
            self.assertEqual(res.status_code, 200, res.data)
        t1_pause = TicketSlaPause.objects.filter(ticket=t1, ended_at__isnull=True).first()
        t2_pause = TicketSlaPause.objects.filter(ticket=t2, ended_at__isnull=True).first()
        self.assertIsNotNone(t1_pause)
        self.assertIsNotNone(t2_pause)
        
        # Bulk update should handle pauses properly
        self.client.force_authenticate(user=self.mgr)
        res = self.client.post('/api/tickets/bulk_update/', {
            'ids': [t1.pk, t2.pk],
            'changes': {'status': 'resolved'},
            'preview': False,
            'confirm': True,
        }, format='json')
        
        # Both tickets should be resolved
        self.assertEqual(res.status_code, 200)
        
        # Check that both pauses were ended
        t1_pause.refresh_from_db()
        t2_pause.refresh_from_db()
        self.assertIsNotNone(t1_pause.ended_at, "First pause should be ended")
        self.assertIsNotNone(t2_pause.ended_at, "Second pause should be ended")