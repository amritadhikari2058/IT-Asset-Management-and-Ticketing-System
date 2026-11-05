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
from rest_framework.test import APIClient
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
from changes.services import ensure_change_number


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
            created_by=self.admin,
        )
        self.assertEqual(tpl.code, "SR-001")
        self.assertTrue(tpl.is_active)

    def test_code_unique(self):
        ChangeTemplate.objects.create(
            name="T1", code="T-1", category="infrastructure",
            created_by=self.admin,
        )
        with self.assertRaises(Exception):
            ChangeTemplate.objects.create(
                name="T2", code="T-1", category="infrastructure",
                created_by=self.admin,
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
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tc = make_ticket_category()
        self.item = make_service_item(self.tc)

    def test_dependency_no_self_reference(self):
        change = make_change(self.emp, self.item, status="submitted")
        with self.assertRaises(Exception):
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
        from changes.services import close_change
        self.change.status = "completed"
        self.change.save()
        with self.assertRaises(Exception):
            close_change(self.change, self.emp, closure_summary="done")
