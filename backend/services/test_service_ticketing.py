"""Tests for automatic Service Request -> Ticket creation.

Exercises ``backend/services/service_ticketing.py`` and the ``create-ticket``
recovery action on ``ServiceRequestViewSet``.

NOTE: the repository's ``lifecycle`` app (added to INSTALLED_APPS by
concurrent work) registers ``LifecycleAssetResolution`` in its admin, but that
model does not exist in ``lifecycle/models.py``. Django therefore fails to load
apps and ``manage.py check`` / ``manage.py test`` cannot run. These tests are
compile-checked and written against the real models/endpoints; they must be
executed once the ``lifecycle`` app is fixed or removed from INSTALLED_APPS.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import ValidationError

from accounts.tests import auth, make_users
from services.models import ServiceCatalogueItem, ServiceRequest

from services.service_ticketing import ensure_ticket_for_service_request
from tickets.models import Ticket, TicketCategory, TicketHistory
from common.models import AuditLog, Notification
from services.models import ServiceRequestHistory


def _token(user):
    return str(RefreshToken.for_user(user).access_token)


def _make_item(**kw):
    defaults = dict(
        name="VPN access", category="network", is_active=True,
        creates_ticket=True, requires_approval=False,
        form_fields=[{"key": "reason", "label": "Reason", "type": "text"}],
    )
    defaults.update(kw)
    return ServiceCatalogueItem.objects.create(**defaults)


def _auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(user)}")


class CatalogueConfigurationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.active_cat = TicketCategory.objects.create(name="Active", is_active=True)
        self.inactive_cat = TicketCategory.objects.create(name="Inactive", is_active=False)

    def test_creates_ticket_without_category_allowed_at_model_level(self):
        item = ServiceCatalogueItem.objects.create(
            name="NoCat", category="network", creates_ticket=True)
        self.assertTrue(item.creates_ticket)
        self.assertIsNone(item.ticket_category_id)

    def test_inactive_category_rejected_by_service(self):
        item = _make_item(ticket_category=self.inactive_cat)
        req = ServiceRequest.objects.create(
            request_number="SR-20260101-0001", requester=self.emp,
            department=self.dep, catalogue_item=item, status="submitted")
        with self.assertRaises(ValidationError):
            ensure_ticket_for_service_request(req, self.mgr)

    def test_creates_ticket_false_requires_no_category(self):
        item = _make_item(creates_ticket=False, ticket_category=None)
        self.assertFalse(item.creates_ticket)
        self.assertIsNone(item.ticket_category_id)


class NoApprovalTicketCreationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.active_cat = TicketCategory.objects.create(name="Active", is_active=True)
        self.item = _make_item(ticket_category=self.active_cat,
                               requires_approval=False)

    def _make_request(self, **kw):
        defaults = dict(
            request_number="SR-20260101-0002", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="submitted", priority="medium",
            answers={"reason": "remote work"}, description="Need VPN.",
        )
        defaults.update(kw)
        return ServiceRequest.objects.create(**defaults)

    def test_creates_exactly_one_ticket(self):
        req = self._make_request()
        with self.captureOnCommitCallbacks(execute=True):
            ticket, created = ensure_ticket_for_service_request(req, self.mgr)
        self.assertTrue(created)
        self.assertEqual(ticket.requester, self.emp)
        self.assertEqual(ticket.department, self.dep)
        self.assertEqual(ticket.category, self.active_cat)
        self.assertEqual(ticket.title, "[SR-20260101-0002] VPN access")
        self.assertIn("SR-20260101-0002", ticket.description)
        self.assertIn("VPN access", ticket.description)
        self.assertIn("remote work", ticket.description)
        # No raw JSON / HTML in description.
        self.assertNotIn("{", ticket.description)
        self.assertNotIn("<", ticket.description)
        req.refresh_from_db()
        self.assertEqual(req.fulfilment_ticket, ticket)
        self.assertEqual(req.status, "approved")  # no assignee -> approved
        # Exactly one fulfilment link.
        self.assertEqual(
            Ticket.objects.filter(service_requests__isnull=False).distinct().count(),
            1)
        # Histories + audit.
        self.assertTrue(TicketHistory.objects.filter(
            ticket=ticket, action="created_from_service_request").exists())
        self.assertTrue(ServiceRequestHistory.objects.filter(
            request=req, event="ticket_created").exists())
        self.assertTrue(AuditLog.objects.filter(
            entity_type="tickets.ticket", object_id=str(ticket.pk)).exists())
        # In-app notification to requester.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, entity_type="tickets.Ticket",
            object_id=str(ticket.pk)).exists())

    def test_assigns_in_progress_when_assignee_set(self):
        req = self._make_request(assigned_to=self.mgr)
        ticket, created = ensure_ticket_for_service_request(req, self.mgr)
        self.assertTrue(created)
        req.refresh_from_db()
        self.assertEqual(req.status, "in_progress")

    def test_idempotent_second_call_returns_existing(self):
        req = self._make_request()
        t1, c1 = ensure_ticket_for_service_request(req, self.mgr)
        self.assertTrue(c1)
        t2, c2 = ensure_ticket_for_service_request(req, self.mgr)
        self.assertFalse(c2)
        self.assertEqual(t1.pk, t2.pk)
        # No duplicate history.
        self.assertEqual(
            ServiceRequestHistory.objects.filter(
                request=req, event="ticket_created").count(), 1)

    def test_rejected_request_denied(self):
        req = self._make_request(status="rejected")
        with self.assertRaises(ValidationError):
            ensure_ticket_for_service_request(req, self.mgr)
        self.assertIsNone(req.fulfilment_ticket_id)

    def test_cancelled_request_denied(self):
        req = self._make_request(status="cancelled")
        with self.assertRaises(ValidationError):
            ensure_ticket_for_service_request(req, self.mgr)

    def test_fulfilled_request_denied(self):
        req = self._make_request(status="fulfilled")
        with self.assertRaises(ValidationError):
            ensure_ticket_for_service_request(req, self.mgr)


class ApprovalRequiredTicketCreationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.active_cat = TicketCategory.objects.create(name="Active", is_active=True)
        self.item = _make_item(ticket_category=self.active_cat,
                               requires_approval=True)

    def _make_pending(self, **kw):
        defaults = dict(
            request_number="SR-20260101-0003", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="pending_approval", priority="high",
            answers={"reason": "please"}, description="Need VPN.",
        )
        defaults.update(kw)
        return ServiceRequest.objects.create(**defaults)

    def test_no_ticket_before_approval(self):
        req = self._make_pending()
        self.assertIsNone(req.fulfilment_ticket_id)

    def test_ticket_created_after_authorized_approval(self):
        req = self._make_pending()
        # Simulate the approve flow: mark approved then create ticket.
        req.status = "approved"
        req.approver = self.mgr
        req.approval_decision = "approved"
        req.save()
        ticket, created = ensure_ticket_for_service_request(req, self.mgr)
        self.assertTrue(created)
        req.refresh_from_db()
        self.assertEqual(req.fulfilment_ticket, ticket)

    def test_non_approved_request_denied(self):
        req = self._make_pending()  # status pending_approval, not approved
        with self.assertRaises(ValidationError):
            ensure_ticket_for_service_request(req, self.mgr)
        self.assertIsNone(req.fulfilment_ticket_id)

    def test_duplicate_approval_one_ticket(self):
        req = self._make_pending()
        req.status = "approved"
        req.approver = self.mgr
        req.save()
        t1, _ = ensure_ticket_for_service_request(req, self.mgr)
        t2, created = ensure_ticket_for_service_request(req, self.mgr)
        self.assertFalse(created)
        self.assertEqual(t1.pk, t2.pk)


class NoTicketCatalogueTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.item = ServiceCatalogueItem.objects.create(
            name="Info", category="other", is_active=True,
            creates_ticket=False, requires_approval=False)

    def test_existing_behavior_unchanged(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20260101-0004", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="submitted")
        ticket, created = ensure_ticket_for_service_request(req, self.mgr)
        self.assertFalse(created)
        self.assertIsNone(ticket)
        req.refresh_from_db()
        self.assertIsNone(req.fulfilment_ticket_id)


class CreateTicketActionTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.active_cat = TicketCategory.objects.create(name="Active", is_active=True)
        self.item = _make_item(ticket_category=self.active_cat,
                               requires_approval=False)
        self.client = APIClient()

    def _url(self, pk):
        return f"/api/services/requests/{pk}/create-ticket/"

    def test_manager_creates_missing_ticket(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20260101-0005", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="submitted")
        _auth(self.client, self.mgr)
        res = self.client.post(self._url(req.pk), {}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["created"])
        req.refresh_from_db()
        self.assertIsNotNone(req.fulfilment_ticket_id)

    def test_employee_denied(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20260101-0006", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="submitted")
        _auth(self.client, self.emp)
        res = self.client.post(self._url(req.pk), {}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

    def test_creates_ticket_false_denied(self):
        plain = ServiceCatalogueItem.objects.create(
            name="Plain", category="other", is_active=True,
            creates_ticket=False)
        req = ServiceRequest.objects.create(
            request_number="SR-20260101-0007", requester=self.emp,
            department=self.dep, catalogue_item=plain,
            status="submitted")
        _auth(self.client, self.mgr)
        res = self.client.post(self._url(req.pk), {}, format="json")
        self.assertEqual(res.status_code, 400, res.data)

    def test_existing_ticket_returned_200(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20260101-0008", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="submitted")
        ticket, _ = ensure_ticket_for_service_request(req, self.mgr)
        _auth(self.client, self.mgr)
        res = self.client.post(self._url(req.pk), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data["created"])
        self.assertEqual(res.data["ticket"]["id"], ticket.pk)
