from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from .models import AutomationRule, ApprovalRequest
from tickets.models import Ticket, TicketCategory

User = get_user_model()

class WorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="adm", password="p", role="system_admin", employee_id="A1", email="a@x.com")
        self.other = User.objects.create_user(username="emp2", password="p", role="employee", employee_id="E2", email="e2@x.com")
        self.client = APIClient(); self.client.force_authenticate(self.admin)

    def test_create_rule(self):
        r = self.client.post("/api/workflow/automation-rules/", {"name":"r","trigger":"ticket_created","conditions":{},"actions":[],"created_by":self.admin.id}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_approval_approve(self):
        cat = TicketCategory.objects.create(name="Cat")
        t = Ticket.objects.create(title="t", description="d", category=cat, requester=self.other)
        ar = ApprovalRequest.objects.create(ticket=t, requested_by=self.other, status="pending")
        r = self.client.post(f"/api/workflow/approval-requests/{ar.id}/approve/", {"comment":"ok"}, format="json")
        self.assertEqual(r.status_code, 200)
        ar.refresh_from_db()
        self.assertEqual(ar.status, "approved")
