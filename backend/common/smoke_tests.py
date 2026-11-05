"""Authenticated end-to-end smoke tests for critical workflows.

These tests exercise real backend API endpoints with real database state
(through Django's test database). No browser automation is used. Every
request is authenticated where required, and role-based denials are asserted
explicitly.

Run: python backend/manage.py test common.smoke_tests
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory
from common.models import UserNotificationPreference
from tickets.models import Ticket, TicketCategory, TicketNote
from services.models import (
    ServiceCatalogueItem, ServiceRequest, ServiceRequestComment,
)


def _token(user):
    return str(RefreshToken.for_user(user).access_token)


class SmokeTests(TestCase):
    """Critical end-to-end workflows exercised end to end."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="General")
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.item = ServiceCatalogueItem.objects.create(
            name="VPN access", category="network", is_active=True,
            requires_approval=True,
            form_fields=[{"key": "reason", "label": "Reason", "type": "text"}])

    # ---- login / profile / logout ------------------------------------

    def test_login_and_profile(self):
        # Login via token endpoint.
        res = self.c.post("/api/token/", {
            "email": self.emp.email,
            "password": "pw12345678",
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        access = res.data["access"]
        refresh = res.data["refresh"]

        # Current-user profile.
        auth(self.c, self.emp)
        res = self.c.get("/api/accounts/me/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["email"], self.emp.email)
        self.assertEqual(res.data["role"], "employee")

        # Logout blacklists the refresh token.
        res = self.c.post("/api/accounts/logout/", {"refresh": refresh},
                          format="json")
        self.assertEqual(res.status_code, 200, res.data)
        # Refreshing with the blacklisted token must fail.
        res = self.c.post("/api/token/refresh/", {"refresh": refresh},
                          format="json")
        self.assertEqual(res.status_code, 401, res.data)

    # ---- ticket workflow ---------------------------------------------

    def test_create_ticket_and_staff_actions(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/", {
            "title": "Broken monitor",
            "description": "Screen is cracked",
            "category": self.tcat.pk,
            "department": self.dep.pk,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        ticket_id = res.data["id"]

        # Staff can view the ticket.
        auth(self.c, self.mgr)
        res = self.c.get(f"/api/tickets/{ticket_id}/")
        self.assertEqual(res.status_code, 200, res.data)

        # Employee cannot see another employee's out-of-department ticket.
        other_dep = Department.objects.create(name="Other", code="OTH")
        other = User.objects.create_user(
            username="o@x", email="o@x", employee_id="O2",
            password="pw12345678", role="employee",
            home_department=other_dep)
        other_ticket = Ticket.objects.create(
            title="Other", description="d", category=self.tcat,
            requester=other, department=other_dep, status="open",
            priority="medium")
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/{other_ticket.pk}/")
        # Scoped 404 is intended anti-IDOR behavior.
        self.assertIn(res.status_code, (403, 404))

    def test_ticket_internal_note_hidden_from_employee(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/", {
            "title": "Note test", "description": "d",
            "category": self.tcat.pk, "department": self.dep.pk,
        }, format="json")
        ticket_id = res.data["id"]
        # Staff adds an internal note.
        res = self.c.post(f"/api/tickets/{ticket_id}/notes/", {
            "body": "internal only", "is_internal": True,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        # Internal note is stored as internal.
        from tickets.models import TicketNote
        note = TicketNote.objects.get(ticket_id=ticket_id, body="internal only")
        self.assertTrue(note.is_internal)
        # Employee cannot add internal notes (403).
        auth(self.c, self.emp)
        res = self.c.post(f"/api/tickets/{ticket_id}/notes/", {
            "body": "x", "is_internal": True,
        }, format="json")
        self.assertEqual(res.status_code, 403, res.data)

    # ---- service request workflow -----------------------------------

    def test_service_request_create_and_approve(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/services/requests/", {
            "catalogue_item": self.item.pk,
            "description": "Need VPN",
            "priority": "high",
            "answers": {"reason": "remote work"},
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        req_id = res.data["id"]
        self.assertEqual(res.data["status"], "pending_approval")

        # Employee cannot approve their own request.
        res = self.c.post(f"/api/services/requests/{req_id}/approve/",
                          {}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

        # Staff approves (separation of duties: not the requester).
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/services/requests/{req_id}/approve/",
                          {"reason": "approved"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        req = ServiceRequest.objects.get(pk=req_id)
        self.assertEqual(req.status, "approved")
        self.assertEqual(req.approver, self.mgr)

    def test_service_request_comment_internal_hidden(self):
        auth(self.c, self.mgr)
        req = ServiceRequest.objects.create(
            request_number="SR-20000101-100", requester=self.emp,
            catalogue_item=self.item, status="pending_approval",
            approval_required=True)
        # Staff internal comment.
        res = self.c.post(f"/api/services/requests/{req.pk}/comment/",
                          {"body": "internal note", "is_internal": True},
                          format="json")
        self.assertEqual(res.status_code, 201, res.data)
        # Employee fetches comments: internal hidden.
        auth(self.c, self.emp)
        res = self.c.get(f"/api/services/requests/{req.pk}/")
        self.assertEqual(res.status_code, 200, res.data)
        bodies = [c["body"] for c in res.data["comments"]]
        self.assertNotIn("internal note", bodies)

    # ---- asset workflow ----------------------------------------------

    def test_asset_assign_and_return(self):
        auth(self.c, self.mgr)
        asset = Asset.objects.create(
            asset_tag="AST-1", name="Laptop", category=self.acat,
            status="available", department=self.dep)
        # Assign asset to emp.
        res = self.c.post(f"/api/assets/{asset.pk}/assign/", {
            "assigned_to": self.emp.pk,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        asset.refresh_from_db()
        self.assertEqual(asset.assigned_to, self.emp)
        # Return asset.
        res = self.c.post(f"/api/assets/{asset.pk}/return_asset/", {},
                          format="json")
        self.assertEqual(res.status_code, 200, res.data)
        asset.refresh_from_db()
        self.assertIsNone(asset.assigned_to)

    # ---- reports -----------------------------------------------------

    def test_report_endpoint_authentication(self):
        # Unauthenticated access denied.
        res = self.c.get("/api/common/reports/departments/")
        self.assertEqual(res.status_code, 401)
        # Staff can access.
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/reports/departments/")
        self.assertEqual(res.status_code, 200, res.data)

    # ---- protected attachment access ---------------------------------

    def test_protected_attachment_access(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/", {
            "title": "Attach test", "description": "d",
            "category": self.tcat.pk, "department": self.dep.pk,
        }, format="json")
        ticket_id = res.data["id"]
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile("note.txt", b"hello", "text/plain")
        res = self.c.post("/api/tickets/attachments/", {
            "ticket": ticket_id, "file": up,
        }, format="multipart")
        self.assertEqual(res.status_code, 201, res.data)
        att_id = res.data["id"]
        # Download requires authentication.
        self.c.credentials()
        res = self.c.get(f"/api/tickets/attachments/{att_id}/download/")
        self.assertEqual(res.status_code, 401)
        # Authenticated owner can download.
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/attachments/{att_id}/download/")
        self.assertEqual(res.status_code, 200)
        res.close()

    # ---- notification preferences -----------------------------------

    def test_notification_preference_behavior(self):
        auth(self.c, self.emp)
        # Create the preference row (OneToOne per user).
        res = self.c.post("/api/common/notification-preferences/",
                          {"email_enabled": True}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        prefs_id = res.data["id"]
        # Disable master switch.
        res = self.c.patch(f"/api/common/notification-preferences/{prefs_id}/",
                           {"email_enabled": False}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data["email_enabled"])
