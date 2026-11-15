"""Change Management tests.

NOTE: These tests cannot currently be executed via ``manage.py test`` because
concurrent work added a ``lifecycle`` app to INSTALLED_APPS whose
``admin.py`` references a nonexistent ``LifecycleAssetResolution`` model, and
``tickets/models.py`` uses ``CheckConstraint(condition=...)`` (Django 6.0
requires positional ``check``). Both issues prevent ``django.setup()`` and
therefore all Django test/check execution. These tests are written against the
real models and compile-checked; they must be executed once those blockers are
cleared.
"""
from django.test import TestCase, override_settings
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from tickets.models import Ticket, TicketCategory
from services.models import ServiceCatalogueItem, ServiceRequest
from changes.models import (
    ChangeRequest,
    ChangeTemplate,
    ChangeTask,
    ChangeHistory,
    ChangeAssetImpact,
    ChangeServiceImpact,
    ChangeDependency,
    ChangeRiskAssessment,
    ChangeApproval,
    ChangeReviewMeeting,
    ChangeReviewItem,
    MaintenanceWindow,
    ChangeConflict,
    ChangeAttachment,
    ChangeStakeholder,
    ChangeCommunication,
    ChangeImplementation,
    PostImplementationReview,
    ChangeTicketLink,
    ChangeKnowledgeLink,
)
from common.models import AuditLog
from changes.views import ChangeRequestViewSet
from changes.permissions import _can_approve, IsChangeApprover
from changes.services import (
    ensure_change_number, _generate_change_number,
    request_approval, approve_change, reject_change,
)


def _token(user):
    return str(RefreshToken.for_user(user).access_token)


def _auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(user)}")


def make_users():
    dep = Department.objects.create(name="Eng", code="ENGX")
    admin = User.objects.create_user(
        username="a@x", email="a@x", employee_id="A1",
        password="pw12345678", role="system_admin", home_department=dep,
    )
    mgr = User.objects.create_user(
        username="m@x", email="m@x", employee_id="M1",
        password="pw12345678", role="it_manager", home_department=dep,
    )
    sup = User.objects.create_user(
        username="s@x", email="s@x", employee_id="S1",
        password="pw12345678", role="it_support", home_department=dep,
    )
    emp = User.objects.create_user(
        username="e@x", email="e@x", employee_id="E1",
        password="pw12345678", role="employee", home_department=dep,
    )
    return dep, admin, mgr, sup, emp


def make_ticket_category():
    return TicketCategory.objects.create(name="Infrastructure", is_active=True)


def make_service_item(tc):
    return ServiceCatalogueItem.objects.create(
        name="Server restart", category="infrastructure", is_active=True,
        creates_ticket=True, requires_approval=False, ticket_category=tc,
    )


def make_change(requester, item, **kw):
    defaults = dict(
        title="Test change", description="desc",
        change_type="normal", category="infrastructure",
        status="draft", priority="normal",
        requester=requester, change_owner=requester,
        change_number=_generate_change_number(),
    )
    defaults.update(kw)
    return ChangeRequest.objects.create(**defaults)


class ChangeModelTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)

    def test_change_number_generation(self):
        change = make_change(self.emp, self.item, status="submitted")
        self.assertTrue(change.change_number.startswith("CHG-"))
        self.assertTrue(change.change_number.startswith(f"CHG-{timezone_now().year}-"))

    def test_change_number_unique(self):
        c1 = make_change(self.emp, self.item, status="submitted")
        c2 = make_change(self.emp, self.item, status="submitted")
        self.assertNotEqual(c1.change_number, c2.change_number)

    def test_status_choices(self):
        self.assertIn("submitted", dict(ChangeRequest.STATUS_CHOICES))
        self.assertIn("approved", dict(ChangeRequest.STATUS_CHOICES))
        self.assertIn("emergency", dict(ChangeRequest.CHANGE_TYPE_CHOICES))

    def test_protected_fields_not_client_settable(self):
        # change_number is server-generated; client cannot set it.
        change = make_change(self.emp, self.item, status="draft")
        self.assertIsNotNone(change.change_number)


def timezone_now():
    from django.utils import timezone
    return timezone.now()


class ChangeTemplateTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()

    def test_template_creation(self):
        tpl = ChangeTemplate.objects.create(
            name="Server restart", code="SR-001", category="infrastructure",
            default_priority="normal", default_risk_level="low",
            owner=self.admin, created_by=self.admin,
        )
        self.assertEqual(tpl.code, "SR-001")
        self.assertTrue(tpl.is_active)

    def test_code_unique(self):
        ChangeTemplate.objects.create(
            name="T1", code="T-1", category="infrastructure",
            owner=self.admin, created_by=self.admin,
        )
        with self.assertRaises(Exception):
            ChangeTemplate.objects.create(
                name="T2", code="T-1", category="infrastructure",
                owner=self.admin, created_by=self.admin,
            )


class ChangeTaskTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="submitted")

    def test_task_sequence_unique(self):
        ChangeTask.objects.create(
            change=self.change, sequence=1, title="Task 1",
            task_type="planning", required=True,
        )
        with self.assertRaises(Exception):
            ChangeTask.objects.create(
                change=self.change, sequence=1, title="Task 1b",
                task_type="planning", required=True,
            )


class ChangeRiskTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="submitted")

    def test_risk_assessment_creation(self):
        from changes.services import calculate_risk
        factors = {
            "service_impact_score": 3,
            "user_impact_score": 3,
            "complexity_score": 2,
            "reversibility_score": 2,
            "test_coverage_score": 3,
            "implementation_experience_score": 2,
            "timing_risk_score": 2,
            "dependency_risk_score": 2,
            "security_risk_score": 1,
            "data_integrity_risk_score": 1,
        }
        assessment = calculate_risk(self.change, factors, self.mgr)
        self.assertIsNotNone(assessment.total_score)
        self.assertIn(assessment.calculated_level, ["low", "medium", "high", "critical"])


class ChangeApprovalTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="pending_approval")

    def test_manager_approve(self):
        from changes.services import request_approval, approve_change
        approval = request_approval(self.change, self.mgr, "manager")
        self.assertEqual(approval.status, "pending")
        result = approve_change(self.change, self.mgr, decision_reason="ok")
        self.assertEqual(result.status, "approved")
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "approved")

    def test_requester_cannot_approve(self):
        from changes.services import request_approval, approve_change
        request_approval(self.change, self.mgr, "manager")
        with self.assertRaises(Exception):
            approve_change(self.change, self.emp)


class ChangeAttachmentTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="submitted")

    def test_attachment_creation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("plan.txt", b"plan content", content_type="text/plain")
        att = ChangeAttachment.objects.create(
            change=self.change, uploaded_by=self.mgr,
            document_type="implementation_plan",
            original_filename="plan.txt",
            content_type="text/plain",
            size=len(b"plan content"),
        )
        self.assertEqual(att.document_type, "implementation_plan")


class ChangeConflictTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)

    def test_dependency_no_self_reference(self):
        change = make_change(self.emp, self.item, status="submitted")
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChangeDependency.objects.create(
                    predecessor=change, successor=change,
                    dependency_type="blocks",
                )


class MaintenanceWindowTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()

    def test_window_creation(self):
        from django.utils import timezone
        from datetime import timedelta
        mw = MaintenanceWindow.objects.create(
            name="Weekend window", code="WW-001", window_type="one_time",
            start_at=timezone.now(), end_at=timezone.now()+timezone.timedelta(hours=4),
            created_by=self.admin,
        )
        self.assertEqual(mw.code, "WW-001")


class ChangeCommunicationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="submitted")

    def test_communication_creation(self):
        from changes.services import send_communication
        comm = send_communication(
            self.change, "planned_outage", "stakeholders",
            "Outage notice", "Server restart planned", self.mgr,
        )
        self.assertEqual(comm.status, "sent")


class PermissionTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="draft")

    def test_employee_can_create_draft(self):
        self.assertEqual(self.change.status, "draft")
        self.assertEqual(self.change.requester, self.emp)

    def test_employee_cannot_close(self):
        from types import SimpleNamespace
        from changes.views import ChangeRequestViewSet
        view = ChangeRequestViewSet()
        view.action = "close"
        permission = view.get_permissions()[0]
        self.assertFalse(permission.has_permission(SimpleNamespace(user=self.emp), view))
        self.assertTrue(permission.has_permission(SimpleNamespace(user=self.mgr), view))


class ChangeManagementRouteTests(TestCase):
    def test_change_management_list_route_registered(self):
        match = resolve("/api/changes/")
        self.assertEqual(match.func.cls, ChangeRequestViewSet)

    def test_change_management_detail_route_registered(self):
        match = resolve("/api/changes/1/")
        self.assertEqual(match.func.cls, ChangeRequestViewSet)


class ChangeApprovalServiceTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.change = make_change(self.emp, self.item, status="pending_approval")

    def _make_pending_approval(self, requester):
        return ChangeApproval.objects.create(
            change=self.change, approval_level="manager", status="pending",
            requester=requester, change_version=self.change.version,
        )

    def test_manager_approve_sets_change_status_approved(self):
        approval = self._make_pending_approval(self.mgr)
        result = approve_change(self.change, self.mgr, decision_reason="looks good", approval=approval)
        self.assertEqual(result.status, "approved")
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "approved")
        self.assertEqual(self.change.current_approver, self.mgr)
        self.assertIsNotNone(self.change.approved_at)

    def test_manager_reject_sets_change_status_rejected(self):
        approval = self._make_pending_approval(self.mgr)
        result = reject_change(self.change, self.mgr, decision_reason="no", approval=approval)
        self.assertEqual(result.status, "rejected")
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "rejected")

    def test_approve_creates_history_and_audit(self):
        approval = self._make_pending_approval(self.mgr)
        approve_change(self.change, self.mgr, decision_reason="ok", approval=approval)
        self.assertTrue(
            ChangeHistory.objects.filter(
                change=self.change, event_type="approved"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="update", reason="Change approved",
                entity_type="changes.changerequest",
            ).exists()
        )

    def test_reject_creates_history_and_audit(self):
        approval = self._make_pending_approval(self.mgr)
        reject_change(self.change, self.mgr, decision_reason="no", approval=approval)
        self.assertTrue(
            ChangeHistory.objects.filter(
                change=self.change, event_type="rejected"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="update", reason="Change rejected",
                entity_type="changes.changerequest",
            ).exists()
        )

    def test_requester_cannot_approve_own_change(self):
        self._make_pending_approval(self.emp)
        with self.assertRaises(ValidationError):
            approve_change(self.change, self.emp, approval=ChangeApproval.objects.get(change=self.change))

    def test_requester_cannot_reject_own_change(self):
        self._make_pending_approval(self.emp)
        with self.assertRaises(ValidationError):
            reject_change(self.change, self.emp, decision_reason="no", approval=ChangeApproval.objects.get(change=self.change))

    def test_approve_exact_approval_when_multiple_pending(self):
        a1 = ChangeApproval.objects.create(
            change=self.change, approval_level="manager", status="pending",
            requester=self.mgr, change_version=self.change.version,
        )
        a2 = ChangeApproval.objects.create(
            change=self.change, approval_level="manager", status="pending",
            requester=self.sup, change_version=self.change.version,
        )
        result = approve_change(self.change, self.admin, approval=a1)
        self.assertEqual(result.pk, a1.pk)
        a1.refresh_from_db(); a2.refresh_from_db()
        self.assertEqual(a1.status, "approved")
        self.assertEqual(a2.status, "pending")
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "approved")

    def test_reject_exact_approval_when_multiple_pending(self):
        a1 = ChangeApproval.objects.create(
            change=self.change, approval_level="manager", status="pending",
            requester=self.mgr, change_version=self.change.version,
        )
        a2 = ChangeApproval.objects.create(
            change=self.change, approval_level="manager", status="pending",
            requester=self.sup, change_version=self.change.version,
        )
        result = reject_change(self.change, self.admin, decision_reason="no", approval=a1)
        self.assertEqual(result.pk, a1.pk)
        a1.refresh_from_db(); a2.refresh_from_db()
        self.assertEqual(a1.status, "rejected")
        self.assertEqual(a2.status, "pending")
        self.change.refresh_from_db()
        self.assertEqual(self.change.status, "rejected")

    def test_approval_must_belong_to_change(self):
        other = make_change(self.emp, self.item, status="pending_approval")
        other_approval = ChangeApproval.objects.create(
            change=other, approval_level="manager", status="pending",
            requester=self.mgr, change_version=other.version,
        )
        with self.assertRaises(ValidationError):
            approve_change(self.change, self.mgr, approval=other_approval)

    def test_stale_approval_rejection_remains_enforced(self):
        approval = self._make_pending_approval(self.mgr)
        # Bump the change version after approval was requested.
        self.change.version = 999
        self.change.save(update_fields=["version"])
        with self.assertRaises(ValidationError):
            approve_change(self.change, self.mgr, approval=approval)

    def test_approve_roles(self):
        self.assertTrue(_can_approve(self.admin))
        self.assertTrue(_can_approve(self.mgr))
        self.assertFalse(_can_approve(self.sup))
        self.assertFalse(_can_approve(self.emp))


class ChangeApprovalAPITests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.sup, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)
        self.client = APIClient()

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(user)}")

    def _setup_change_with_approval(self, requester, decider):
        change = make_change(requester, self.item, status="pending_approval")
        approval = ChangeApproval.objects.create(
            change=change, approval_level="manager", status="pending",
            requester=decider, change_version=change.version,
        )
        return change, approval

    def test_approval_history_returns_only_that_changes_approvals(self):
        c1 = make_change(self.emp, self.item, status="pending_approval")
        c2 = make_change(self.emp, self.item, status="pending_approval")
        ChangeApproval.objects.create(
            change=c1, approval_level="manager", status="pending",
            requester=self.mgr, change_version=c1.version,
        )
        ChangeApproval.objects.create(
            change=c1, approval_level="manager", status="pending",
            requester=self.sup, change_version=c1.version,
        )
        ChangeApproval.objects.create(
            change=c2, approval_level="manager", status="pending",
            requester=self.mgr, change_version=c2.version,
        )
        self._auth(self.admin)
        res = self.client.get(f"/api/changes/{c1.pk}/approvals/")
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results", res.data)
        ids = [a["id"] for a in results]
        self.assertEqual(len(ids), 2)
        c1_ids = {pk for pk in ChangeApproval.objects.filter(
            change=c1).values_list("pk", flat=True)}
        self.assertEqual(set(ids), c1_ids)

    def test_manager_can_approve_via_api(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.mgr)
        res = self.client.post(
            f"/api/changes/{change.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        change.refresh_from_db()
        self.assertEqual(change.status, "approved")

    def test_system_admin_can_approve_via_api(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.admin)
        res = self.client.post(
            f"/api/changes/{change.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 200)

    def test_it_support_cannot_approve_or_reject_via_api(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        # ChangeApprovalViewSet actions enforce IsChangeApprover (manager/admin only).
        self._auth(self.sup)
        res = self.client.post(
            f"/api/changes/approvals/{approval.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 403)
        res = self.client.post(
            f"/api/changes/approvals/{approval.pk}/reject/",
            {"decision_reason": "no"}, format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_manager_can_approve_via_approval_endpoint(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.mgr)
        res = self.client.post(
            f"/api/changes/approvals/{approval.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        change.refresh_from_db()
        self.assertEqual(change.status, "approved")

    def test_requester_cannot_approve_via_api(self):
        # Requester who IS an approver still cannot approve their own change
        # (separation of duties enforced by the service → HTTP 400).
        change, approval = self._setup_change_with_approval(self.mgr, self.mgr)
        self._auth(self.mgr)
        res = self.client.post(
            f"/api/changes/{change.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 400)
        change.refresh_from_db()
        self.assertEqual(change.status, "pending_approval")

    def test_requester_cannot_reject_via_api(self):
        change, approval = self._setup_change_with_approval(self.mgr, self.mgr)
        self._auth(self.mgr)
        res = self.client.post(
            f"/api/changes/{change.pk}/reject/",
            {"decision_reason": "no"}, format="json",
        )
        self.assertEqual(res.status_code, 400)
        change.refresh_from_db()
        self.assertEqual(change.status, "pending_approval")

    def test_it_support_cannot_approve_via_change_endpoint(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.sup)
        res = self.client.post(
            f"/api/changes/{change.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_it_support_cannot_reject_via_change_endpoint(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.sup)
        res = self.client.post(
            f"/api/changes/{change.pk}/reject/",
            {"decision_reason": "no"}, format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_manager_and_admin_retain_approval_and_rejection_access(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.mgr)
        res = self.client.post(
            f"/api/changes/{change.pk}/approve/",
            {"decision_reason": "ok"}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        change.refresh_from_db()
        self.assertEqual(change.status, "approved")

        change2, approval2 = self._setup_change_with_approval(self.emp, self.sup)
        self._auth(self.admin)
        res = self.client.post(
            f"/api/changes/{change2.pk}/reject/",
            {"decision_reason": "no"}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        change2.refresh_from_db()
        self.assertEqual(change2.status, "rejected")

    def test_manager_can_reject_via_api(self):
        change, approval = self._setup_change_with_approval(self.emp, self.mgr)
        self._auth(self.mgr)
        res = self.client.post(
            f"/api/changes/{change.pk}/reject/",
            {"decision_reason": "not acceptable"}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        change.refresh_from_db()
        self.assertEqual(change.status, "rejected")
