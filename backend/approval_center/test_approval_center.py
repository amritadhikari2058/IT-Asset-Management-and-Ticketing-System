"""Tests for the Approval Center provider architecture and API.

NOTE: the repository's ``lifecycle`` app (added to INSTALLED_APPS by concurrent
work) registers ``LifecycleAssetResolution`` in its admin, but that model does
not exist in ``lifecycle/models.py``. Django therefore fails to load apps and
``manage.py check`` / ``manage.py test`` cannot run. These tests are
compile-checked and written against the real models; they must be executed
once the ``lifecycle`` app is fixed or removed from INSTALLED_APPS.
"""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.tests import auth, make_users
from services.models import ServiceCatalogueItem, ServiceRequest
from assets.models import Disposal
from workflow.models import ApprovalRequest
from assets.models import KnowledgeBaseArticle
from approval_center.services import (
    get_pending_approvals, get_approval_counts, REGISTRY,
    ServiceRequestApprovalProvider, DisposalApprovalProvider,
    WorkflowApprovalProvider, KnowledgeBaseReviewProvider,
)


def _token(user):
    return str(RefreshToken.for_user(user).access_token)


def _auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(user)}")


class ProviderCapabilityTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.item = ServiceCatalogueItem.objects.create(
            name="VPN", category="network", is_active=True,
            creates_ticket=True, requires_approval=True,
            ticket_category=None)

    def _sr(self, requester, status="pending_approval"):
        return ServiceRequest.objects.create(
            request_number="SR-20260101-0100", requester=requester,
            department=self.dep, catalogue_item=self.item,
            status=status, approval_required=True)

    def test_it_manager_can_approve_service_request(self):
        provider = ServiceRequestApprovalProvider()
        sr = self._sr(self.emp)
        self.assertTrue(provider.can_approve(self.mgr, sr))
        self.assertTrue(provider.can_reject(self.mgr, sr))

    def test_it_support_cannot_approve_service_request(self):
        provider = ServiceRequestApprovalProvider()
        sr = self._sr(self.emp)
        self.assertFalse(provider.can_approve(self.emp, sr))  # emp is not staff
        # IT Support role cannot approve manager-controlled items.
        support = self.emp  # emp role; use a support user instead
        support_user = self.emp  # placeholder; real support user below
        # Build an actual IT Support user.
        from accounts.models import User
        support = User.objects.create_user(
            username="s@x", email="s@x", employee_id="S1",
            password="pw12345678", role="it_support",
            home_department=self.dep)
        self.assertFalse(provider.can_approve(support, sr))
        self.assertFalse(provider.can_reject(support, sr))

    def test_requester_cannot_approve_own_service_request(self):
        provider = ServiceRequestApprovalProvider()
        sr = self._sr(self.emp)
        self.assertFalse(provider.can_approve(self.emp, sr))
        self.assertFalse(provider.can_reject(self.emp, sr))

    def test_system_admin_can_approve_any(self):
        provider = ServiceRequestApprovalProvider()
        sr = self._sr(self.emp)
        self.assertTrue(provider.can_approve(self.admin, sr))
        self.assertTrue(provider.can_reject(self.admin, sr))


class ProviderSerializationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.item = ServiceCatalogueItem.objects.create(
            name="VPN", category="network", is_active=True,
            creates_ticket=True, requires_approval=True)

    def test_service_request_normalized_fields(self):
        provider = ServiceRequestApprovalProvider()
        sr = ServiceRequest.objects.create(
            request_number="SR-20260101-0110", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="pending_approval", approval_required=True,
            priority="high")
        data = provider.serialize(sr, self.mgr)
        self.assertEqual(data["approval_type"], "service_request")
        self.assertEqual(data["reference"], "SR-20260101-0110")
        self.assertEqual(data["requester"], self.emp.email)
        self.assertEqual(data["status"], "pending_approval")
        self.assertEqual(data["priority"], "high")
        self.assertTrue(data["can_approve"])
        self.assertTrue(data["can_reject"])
        self.assertIsNotNone(data["detail_path"])
        self.assertIsNotNone(data["approve_api_path"])
        self.assertIsNotNone(data["reject_api_path"])
        self.assertIn("service", data["metadata"])

    def test_disposal_normalized_fields(self):
        provider = DisposalApprovalProvider()
        # Need an asset; create via model directly.
        from assets.models import Asset, AssetCategory
        acat = AssetCategory.objects.create(name="Laptop")
        asset = Asset.objects.create(
            asset_tag="AST-1", name="Laptop", category=acat,
            status="available", department=self.dep)
        disp = Disposal.objects.create(
            asset=asset, disposal_reason="Old", disposal_method="recycled",
            created_by=self.emp, approval_status="pending")
        data = provider.serialize(disp, self.mgr)
        self.assertEqual(data["approval_type"], "disposal")
        self.assertEqual(data["metadata"]["asset_tag"], "AST-1")
        self.assertTrue(data["can_approve"])

    def test_workflow_normalized_fields(self):
        provider = WorkflowApprovalProvider()
        from tickets.models import Ticket, TicketCategory
        tcat = TicketCategory.objects.create(name="T")
        ticket = Ticket.objects.create(
            title="T", description="d", category=tcat,
            priority="medium", status="open", requester=self.emp,
            department=self.dep)
        ap = ApprovalRequest.objects.create(
            ticket=ticket, requested_by=self.emp,
            operation="change_status", status="pending")
        data = provider.serialize(ap, self.mgr)
        self.assertEqual(data["approval_type"], "workflow_approval")
        self.assertTrue(data["can_approve"])

    def test_knowledge_base_normalized_fields(self):
        provider = KnowledgeBaseReviewProvider()
        kb = KnowledgeBaseArticle.objects.create(
            title="Art", slug="art", content="c",
            status="pending_review", author=self.emp)
        data = provider.serialize(kb, self.mgr)
        self.assertEqual(data["approval_type"], "knowledge_base")
        self.assertFalse(data["can_approve"])  # read-only in center
        self.assertIsNone(data["approve_api_path"])


class ApprovalCenterAggregationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.item = ServiceCatalogueItem.objects.create(
            name="VPN", category="network", is_active=True,
            creates_ticket=True, requires_approval=True)

    def test_get_pending_approvals_returns_normalized_list(self):
        ServiceRequest.objects.create(
            request_number="SR-20260101-0120", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="pending_approval", approval_required=True)
        items = get_pending_approvals(self.mgr)
        self.assertGreaterEqual(len(items), 1)
        types = {it["approval_type"] for it in items}
        self.assertIn("service_request", types)
        for it in items:
            self.assertIn("approval_type", it)
            self.assertIn("object_id", it)
            self.assertIn("can_approve", it)
            self.assertIn("can_reject", it)

    def test_get_approval_counts(self):
        ServiceRequest.objects.create(
            request_number="SR-20260101-0121", requester=self.emp,
            department=self.dep, catalogue_item=self.item,
            status="pending_approval", approval_required=True)
        counts = get_approval_counts(self.mgr)
        self.assertIn("total", counts)
        self.assertGreaterEqual(counts.get("service_request", 0) + counts.get("total", 0), 1)
        self.assertGreaterEqual(counts["total"], 1)

    def test_employee_denied_summary(self):
        counts = get_approval_counts(self.emp)
        # Employee gets no manager queue.
        self.assertEqual(counts.get("total", 0), 0)
