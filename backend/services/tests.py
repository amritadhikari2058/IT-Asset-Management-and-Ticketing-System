"""Services: catalogue + service-request API tests (were empty stub file).

Covers the contracts the P1 frontend relies on:
- catalogue visibility (employees see active only) + staff-only writes
- request creation (auto requester/dept/number, pending_approval when the
  catalogue item requires approval) + employee isolation
- approve/reject (staff only, own-request guard, pending-only)
- assign (staff only; approved -> in_progress)
- comment (internal forced False for non-staff; empty body 400)
- cancel (requester or staff; terminal states rejected)
"""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from services.models import (
    ServiceCatalogueItem, ServiceRequest, ServiceRequestComment,
    ServiceRequestHistory,
)


class ServiceApiTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.item = ServiceCatalogueItem.objects.create(
            name="VPN access", category="network", is_active=True,
            requires_approval=True,
            form_fields=[{"key": "reason", "label": "Reason", "type": "text"}],
        )
        self.inactive = ServiceCatalogueItem.objects.create(
            name="Legacy", category="other", is_active=False,
        )

    # ---- catalogue ----

    def test_employee_sees_only_active_catalogue(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/services/catalogue/")
        self.assertEqual(res.status_code, 200)
        names = [i["name"] for i in res.data["results"]]
        self.assertIn("VPN access", names)
        self.assertNotIn("Legacy", names)

    def test_staff_sees_inactive_catalogue(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/services/catalogue/")
        names = [i["name"] for i in res.data["results"]]
        self.assertIn("VPN access", names)
        self.assertIn("Legacy", names)

    def test_employee_cannot_create_catalogue_item(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/services/catalogue/", {"name": "X"},
                          format="json")
        self.assertEqual(res.status_code, 403)

    def test_staff_create_and_patch_catalogue_item(self):
        auth(self.c, self.mgr)
        res = self.c.post(
            "/api/services/catalogue/",
            {"name": "New", "category": "software", "is_active": True},
            format="json")
        self.assertEqual(res.status_code, 201)
        res = self.c.patch(
            f"/api/services/catalogue/{self.item.pk}/",
            {"is_active": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(ServiceCatalogueItem.objects.get(pk=self.item.pk).is_active)

    def test_catalogue_delete_soft_deletes(self):
        auth(self.c, self.mgr)
        res = self.c.delete(f"/api/services/catalogue/{self.item.pk}/")
        self.assertEqual(res.status_code, 204)
        self.assertTrue(
            ServiceCatalogueItem.objects.get(pk=self.item.pk).is_deleted)
        res = self.c.get("/api/services/catalogue/")
        self.assertNotIn("VPN access", [i["name"] for i in res.data["results"]])

    # ---- request creation ----

    def test_create_request_sets_pending_approval(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/services/requests/", {
            "catalogue_item": self.item.pk,
            "description": "please",
            "priority": "high",
            "answers": {"reason": "remote work"},
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        req = ServiceRequest.objects.get(pk=res.data["id"])
        self.assertEqual(req.requester, self.emp)
        self.assertEqual(req.department, self.dep)
        self.assertTrue(req.approval_required)
        self.assertEqual(req.status, "pending_approval")
        self.assertTrue(req.request_number.startswith("SR-"))
        self.assertTrue(ServiceRequestHistory.objects.filter(
            request=req, event="created").exists())
        self.assertTrue(ServiceRequestHistory.objects.filter(
            request=req, event="approval_required").exists())

    def test_employee_sees_only_own_requests(self):
        other = self.emp.__class__.objects.create_user(
            username="o@x", email="o@x", employee_id="O1",
            password="pw12345678", role="employee")
        ServiceRequest.objects.create(
            request_number="SR-20000101-0001", requester=self.emp,
            catalogue_item=self.item, status="submitted")
        ServiceRequest.objects.create(
            request_number="SR-20000101-0002", requester=other,
            catalogue_item=self.item, status="submitted")
        auth(self.c, self.emp)
        res = self.c.get("/api/services/requests/")
        self.assertEqual(
            [r["request_number"] for r in res.data["results"]],
            ["SR-20000101-0001"])
        auth(self.c, self.mgr)
        res = self.c.get("/api/services/requests/")
        self.assertEqual(len(res.data["results"]), 2)

    # ---- guard rails: approve / reject ----

    def _make_pending(self, requester=None):
        return ServiceRequest.objects.create(
            request_number="SR-20000101-0010", requester=requester or self.emp,
            catalogue_item=self.item, status="pending_approval",
            approval_required=True)

    def test_approve_by_staff(self):
        req = self._make_pending()
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/services/requests/{req.pk}/approve/",
                          {"reason": "ok"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertEqual(req.approver, self.mgr)
        self.assertEqual(req.approval_decision, "approved")

    def test_approve_own_request_is_400(self):
        req = self._make_pending(requester=self.mgr)
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/services/requests/{req.pk}/approve/", {},
                          format="json")
        self.assertEqual(res.status_code, 400)

    def test_approve_non_pending_is_400(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20000101-0011", requester=self.emp,
            catalogue_item=self.item, status="submitted")
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/services/requests/{req.pk}/approve/", {},
                          format="json")
        self.assertEqual(res.status_code, 400)

    def test_employee_cannot_approve(self):
        req = self._make_pending()
        auth(self.c, self.emp)
        res = self.c.post(f"/api/services/requests/{req.pk}/approve/", {},
                          format="json")
        self.assertEqual(res.status_code, 403)

    def test_reject_by_staff_sets_resolved(self):
        req = self._make_pending()
        auth(self.c, self.admin)
        res = self.c.post(f"/api/services/requests/{req.pk}/reject/",
                          {"reason": "no budget"}, format="json")
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, "rejected")
        self.assertIsNotNone(req.resolved_at)

    # ---- assign ----

    def test_assign_moves_approved_to_in_progress(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20000101-0012", requester=self.emp,
            catalogue_item=self.item, status="approved")
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/services/requests/{req.pk}/assign/",
                          {"assigned_to": self.mgr.pk}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        req.refresh_from_db()
        self.assertEqual(req.assigned_to, self.mgr)
        self.assertEqual(req.status, "in_progress")

    # ---- comments ----

    def test_employee_comment_cannot_be_internal(self):
        req = self._make_pending()
        auth(self.c, self.emp)
        res = self.c.post(f"/api/services/requests/{req.pk}/comment/",
                          {"body": "hello", "is_internal": True}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertFalse(ServiceRequestComment.objects.get(
            pk=res.data["id"]).is_internal)

    def test_staff_comment_can_be_internal(self):
        req = self._make_pending()
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/services/requests/{req.pk}/comment/",
                          {"body": "note", "is_internal": True}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(ServiceRequestComment.objects.get(
            pk=res.data["id"]).is_internal)

    def test_comment_requires_body(self):
        req = self._make_pending()
        auth(self.c, self.emp)
        res = self.c.post(f"/api/services/requests/{req.pk}/comment/",
                          {"body": "  "}, format="json")
        self.assertEqual(res.status_code, 400)

    # ---- cancel ----

    def test_requester_can_cancel_open_request(self):
        req = self._make_pending()
        auth(self.c, self.emp)
        res = self.c.post(f"/api/services/requests/{req.pk}/cancel/", {},
                          format="json")
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, "cancelled")
        self.assertIsNotNone(req.resolved_at)

    def test_cancel_terminal_state_is_400(self):
        req = ServiceRequest.objects.create(
            request_number="SR-20000101-0013", requester=self.emp,
            catalogue_item=self.item, status="fulfilled")
        auth(self.c, self.emp)
        res = self.c.post(f"/api/services/requests/{req.pk}/cancel/", {},
                          format="json")
        self.assertEqual(res.status_code, 400)
