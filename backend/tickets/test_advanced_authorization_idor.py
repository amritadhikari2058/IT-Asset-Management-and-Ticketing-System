from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users, _make_user
from tickets.models import (
    Ticket, TicketCategory, TicketBulkImportOperation,
    SavedTicketView, TicketQueue, CannedResponse, TicketTemplate,
    TicketSatisfactionSurvey, TicketMergeRecord,
)


class TicketBulkImportMetadataIsolationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support1 = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.support2 = _make_user("S2", "s2@x", "s2@x", "it_support", self.dep)
        self.c = APIClient()
        self.op1 = TicketBulkImportOperation.objects.create(
            user=self.support1, token="tok1", status=TicketBulkImportOperation.STATUS_PREVIEWED,
            total_rows=1)
        self.op2 = TicketBulkImportOperation.objects.create(
            user=self.support2, token="tok2", status=TicketBulkImportOperation.STATUS_PREVIEWED,
            total_rows=1)

    def test_it_support_cannot_list_other_users_import_operations(self):
        auth(self.c, self.support1)
        res = self.c.get("/api/tickets/bulk-imports/")
        self.assertEqual(res.status_code, 200)
        ids = {r["id"] for r in res.data.get("results", res.data)}
        self.assertIn(self.op1.pk, ids)
        self.assertNotIn(self.op2.pk, ids)

    def test_it_support_cannot_retrieve_other_users_import_operation(self):
        auth(self.c, self.support1)
        res = self.c.get(f"/api/tickets/bulk-imports/{self.op2.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_it_manager_can_list_all_import_operations(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/tickets/bulk-imports/")
        self.assertEqual(res.status_code, 200)
        ids = {r["id"] for r in res.data.get("results", res.data)}
        self.assertIn(self.op1.pk, ids)
        self.assertIn(self.op2.pk, ids)

    def test_employee_cannot_access_bulk_import_operations(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/tickets/bulk-imports/")
        self.assertEqual(res.status_code, 403)


class SavedTicketViewAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.emp2 = _make_user("E2", "e2@x", "e2@x", "employee", self.dep)
        self.c = APIClient()
        self.view_emp = SavedTicketView.objects.create(
            owner=self.emp, name="mine", filters={}, ordering="-created_at", columns=[])

    def test_user_cannot_modify_other_users_saved_view(self):
        auth(self.c, self.emp2)
        res = self.c.patch(f"/api/tickets/saved-views/{self.view_emp.pk}/",
                           {"name": "hacked"}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.view_emp.refresh_from_db()
        self.assertEqual(self.view_emp.name, "mine")

    def test_user_cannot_delete_other_users_saved_view(self):
        auth(self.c, self.emp2)
        res = self.c.delete(f"/api/tickets/saved-views/{self.view_emp.pk}/")
        self.assertIn(res.status_code, (403, 404))
        self.assertTrue(SavedTicketView.objects.filter(pk=self.view_emp.pk).exists())


class TicketActionPermissionConsistencyTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.c = APIClient()

    def test_operations_dashboard_requires_staff(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/tickets/operations-dashboard/")
        self.assertEqual(res.status_code, 403)

    def test_agent_workload_requires_staff(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/tickets/agent-workload/")
        self.assertEqual(res.status_code, 403)

    def test_satisfaction_report_requires_manager(self):
        auth(self.c, self.support)
        res = self.c.get("/api/tickets/satisfaction-report/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.mgr)
        res = self.c.get("/api/tickets/satisfaction-report/")
        self.assertEqual(res.status_code, 200)


class QueueMembershipAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.c = APIClient()
        self.queue = TicketQueue.objects.create(
            name="Q1", code="Q1", created_by=self.mgr, manager=self.mgr)

    def test_it_support_cannot_create_queue_membership(self):
        auth(self.c, self.support)
        res = self.c.post("/api/tickets/queue-memberships/",
                          {"queue": self.queue.pk, "user": self.support.pk, "role": "agent"},
                          format="json")
        self.assertEqual(res.status_code, 403)

    def test_it_support_cannot_list_queue_memberships(self):
        auth(self.c, self.support)
        res = self.c.get("/api/tickets/queue-memberships/")
        self.assertEqual(res.status_code, 403)

    def test_it_manager_can_create_queue_membership(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/queue-memberships/",
                          {"queue": self.queue.pk, "user": self.support.pk, "role": "agent"},
                          format="json")
        self.assertEqual(res.status_code, 201)


class TemplateAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support1 = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.support2 = _make_user("S2", "s2@x", "s2@x", "it_support", self.dep)
        self.c = APIClient()
        self.personal = TicketTemplate.objects.create(
            name="Personal", code="PERS1", title_template="t", owner=self.support1,
            is_shared=False, created_by=self.support1)

    def test_support_cannot_update_other_users_private_template(self):
        auth(self.c, self.support2)
        res = self.c.patch(f"/api/tickets/templates/{self.personal.pk}/",
                           {"name": "Hacked"}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.name, "Personal")

    def test_support_cannot_delete_other_users_private_template(self):
        auth(self.c, self.support2)
        res = self.c.delete(f"/api/tickets/templates/{self.personal.pk}/")
        self.assertIn(res.status_code, (403, 404))
        self.assertTrue(TicketTemplate.objects.filter(pk=self.personal.pk, is_deleted=False).exists())

    def test_support_cannot_make_template_shared(self):
        own = TicketTemplate.objects.create(
            name="Mine", code="MINE1", title_template="t", owner=self.support1,
            is_shared=False, created_by=self.support1)
        auth(self.c, self.support1)
        res = self.c.patch(f"/api/tickets/templates/{own.pk}/",
                           {"is_shared": True}, format="json")
        self.assertEqual(res.status_code, 403)
        own.refresh_from_db()
        self.assertFalse(own.is_shared)


class MergeRecordAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.c = APIClient()

    def test_it_support_cannot_list_merge_records(self):
        auth(self.c, self.support)
        res = self.c.get("/api/tickets/merge-records/")
        self.assertEqual(res.status_code, 403)

    def test_it_manager_can_list_merge_records(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/tickets/merge-records/")
        self.assertEqual(res.status_code, 200)


class SavedTicketViewValidationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.view = SavedTicketView.objects.create(
            owner=self.emp, name="mine", filters={}, ordering="-created_at", columns=[])

    def test_owner_cannot_set_invalid_ordering_via_patch(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/saved-views/{self.view.pk}/",
                           {"ordering": "bad_field"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.view.refresh_from_db()
        self.assertEqual(self.view.ordering, "-created_at")


class QueueAdminActionAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.c = APIClient()
        self.queue = TicketQueue.objects.create(
            name="Q2", code="Q2", created_by=self.mgr, manager=self.mgr)

    def test_it_support_cannot_deactivate_queue(self):
        auth(self.c, self.support)
        res = self.c.post(f"/api/tickets/queues/{self.queue.pk}/deactivate/")
        self.assertEqual(res.status_code, 403)
        self.queue.refresh_from_db()
        self.assertTrue(self.queue.is_active)

    def test_it_support_cannot_create_queue(self):
        auth(self.c, self.support)
        res = self.c.post("/api/tickets/queues/",
                          {"name": "X", "code": "XQ"}, format="json")
        self.assertEqual(res.status_code, 403)


class SatisfactionSurveyAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.emp2 = _make_user("E2", "e2@x", "e2@x", "employee", self.dep)
        self.cat = TicketCategory.objects.create(name="Cat", is_active=True)
        self.ticket = Ticket.objects.create(
            title="T", description="D", category=self.cat,
            requester=self.emp, department=self.dep)
        self.survey = TicketSatisfactionSurvey.objects.create(
            ticket=self.ticket, requester=self.emp,
            status="pending")
        self.c = APIClient()

    def test_other_employee_cannot_get_survey(self):
        auth(self.c, self.emp2)
        res = self.c.get(f"/api/tickets/{self.ticket.pk}/satisfaction/")
        self.assertEqual(res.status_code, 404)

    def test_other_employee_cannot_submit_survey(self):
        auth(self.c, self.emp2)
        res = self.c.post(f"/api/tickets/{self.ticket.pk}/satisfaction/submit/",
                          {"rating": 5}, format="json")
        self.assertIn(res.status_code, (400, 403, 404))
        self.survey.refresh_from_db()
        self.assertEqual(self.survey.status, "pending")
        self.assertIsNone(self.survey.rating)

    def test_requester_can_submit_own_survey(self):
        auth(self.c, self.emp)
        res = self.c.post(f"/api/tickets/{self.ticket.pk}/satisfaction/submit/",
                          {"rating": 4}, format="json")
        self.assertEqual(res.status_code, 200)
        self.survey.refresh_from_db()
        self.assertEqual(self.survey.status, "submitted")


class WatcherAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.dep2 = Department.objects.create(name="Other", code="OTHX")
        self.emp2 = _make_user("E2", "e2@x", "e2@x", "employee", self.dep)
        self.emp_other = _make_user("E3", "e3@x", "e3@x", "employee", self.dep2)
        self.cat = TicketCategory.objects.create(name="Cat2", is_active=True)
        self.ticket = Ticket.objects.create(
            title="T", description="D", category=self.cat,
            requester=self.emp, department=self.dep)
        self.c = APIClient()

    def test_other_employee_cannot_watch_ticket(self):
        auth(self.c, self.emp_other)
        res = self.c.post(f"/api/tickets/{self.ticket.pk}/watch/", {}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.assertFalse(self.ticket.watchers.filter(user=self.emp_other).exists())

    def test_same_dept_employee_cannot_watch_others_ticket_via_api(self):
        # Same-dept employee may be able to read ticket, but cannot mutate watch
        # state for a ticket they did not request.
        auth(self.c, self.emp2)
        res = self.c.post(f"/api/tickets/{self.ticket.pk}/watch/", {}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.assertFalse(self.ticket.watchers.filter(user=self.emp2).exists())


class ServiceLayerAuthorizationTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.cat = TicketCategory.objects.create(name="Cat3", is_active=True)
        self.t1 = Ticket.objects.create(
            title="A", description="D", category=self.cat,
            requester=self.emp, department=self.dep)
        self.t2 = Ticket.objects.create(
            title="B", description="D", category=self.cat,
            requester=self.emp, department=self.dep)

    def test_merge_service_rejects_it_support(self):
        from tickets.merge_services import merge_tickets, MergeError
        with self.assertRaises((MergeError, Exception)):
            merge_tickets(self.t1, self.t2, self.support, "dup", {})
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertNotEqual(self.t1.status, "merged")
        self.assertNotEqual(self.t2.status, "merged")

    def test_queue_membership_service_rejects_it_support(self):
        from tickets.queue_services import add_membership
        q = TicketQueue.objects.create(name="Q3", code="Q3", created_by=self.mgr, manager=self.mgr)
        with self.assertRaises(Exception):
            add_membership(q, {"user": self.support, "role": "agent"}, self.support)
        self.assertFalse(q.memberships.filter(user=self.support, is_deleted=False).exists())


class SavedTicketViewReadTimeProtectionTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.view = SavedTicketView.objects.create(
            owner=self.emp, name="legacy", filters={"status__in": ["open"], "bad": {"evil": 1}},
            ordering="not_a_field", columns=[])

    def test_results_handles_invalid_ordering_and_filter_types(self):
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/saved-views/{self.view.pk}/results/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("results", res.data)


class BulkImportDiagnosticProtectionTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = _make_user("S1", "s1@x", "s1@x", "it_support", self.dep)
        self.c = APIClient()
        self.op = TicketBulkImportOperation.objects.create(
            user=self.support, token="tok-sec", status=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=1,
            error_detail="Traceback (most recent call last): File \"C:\\secret\\app.py\", line 1\nBearer SECRET123456789012345678901234567890")

    def test_error_detail_is_sanitized(self):
        auth(self.c, self.support)
        res = self.c.get(f"/api/tickets/bulk-imports/{self.op.pk}/")
        self.assertEqual(res.status_code, 200)
        detail = res.data.get("error_detail", "")
        self.assertNotIn("Traceback", detail)
        self.assertNotIn("SECRET123456789012345678901234567890", detail)
        self.assertNotIn("C:\\secret\\app.py", detail)
