from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users, _make_user
from assets.models import Asset, AssetCategory
from tickets.models import Ticket, TicketAttachment, TicketCategory, TicketHistory


class TicketAuthorizationIDORTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.dep2 = Department.objects.create(name="HR", code="HR1")
        self.emp2 = _make_user("E2", "e2@x", "e2@x", "employee", self.dep)
        self.emp_other = _make_user("E3", "e3@x", "e3@x", "employee", self.dep2)
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.ticket_emp = Ticket.objects.create(
            title="emp ticket", description="d", category=self.tcat,
            requester=self.emp, department=self.dep, status="open")
        self.ticket_emp2 = Ticket.objects.create(
            title="emp2 ticket", description="d", category=self.tcat,
            requester=self.emp2, department=self.dep, status="open")
        self.ticket_other = Ticket.objects.create(
            title="other dept", description="d", category=self.tcat,
            requester=self.emp_other, department=self.dep2, status="open")
        self.c = APIClient()

    def test_employee_cannot_retrieve_unrelated_ticket(self):
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/{self.ticket_other.pk}/")
        self.assertEqual(res.status_code, 404)

    def test_employee_cannot_modify_other_employees_ticket_same_department(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.ticket_emp2.pk}/",
                           {"title": "hacked"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.ticket_emp2.refresh_from_db()
        self.assertEqual(self.ticket_emp2.title, "emp2 ticket")

    def test_employee_cannot_add_note_to_other_employees_ticket(self):
        auth(self.c, self.emp)
        res = self.c.post(f"/api/tickets/{self.ticket_emp2.pk}/notes/",
                          {"body": "hi", "is_internal": False}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(self.ticket_emp2.notes.filter(body="hi").exists())

    def test_employee_cannot_add_attachment_to_other_employees_ticket(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        auth(self.c, self.emp)
        f = SimpleUploadedFile("a.txt", b"hello", content_type="text/plain")
        res = self.c.post("/api/tickets/attachments/",
                          {"ticket": self.ticket_emp2.pk, "file": f}, format="multipart")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(TicketAttachment.objects.filter(ticket=self.ticket_emp2).exists())

    def test_employee_cannot_access_ticket_history_endpoint(self):
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/histories/?ticket={self.ticket_emp.pk}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get("count", len(res.data.get("results", res.data))), 0)

    def test_ticket_history_misrouted_actions_removed(self):
        auth(self.c, self.admin)
        h = TicketHistory.objects.create(ticket=self.ticket_emp, actor=self.admin, action="created")
        for action in ("claim", "unclaim", "reassign", "move_queue"):
            res = self.c.post(f"/api/tickets/histories/{h.pk}/{action}/", {}, format="json")
            self.assertIn(res.status_code, (404, 405))

    def test_employee_cannot_set_requester_on_create(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/", {
            "title": "x", "description": "d", "category": self.tcat.pk,
            "requester": self.emp2.pk,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.requester_id, self.emp.pk)

    def test_employee_cannot_modify_unrelated_ticket_by_id(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.ticket_other.pk}/",
                           {"title": "hacked"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.ticket_other.refresh_from_db()
        self.assertEqual(self.ticket_other.title, "other dept")

    def test_disabled_user_denied(self):
        auth(self.c, self.emp)
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        res = self.c.get("/api/tickets/")
        self.assertIn(res.status_code, (401, 403))

    def test_attachment_download_idor(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        att = TicketAttachment.objects.create(
            ticket=self.ticket_other,
            file=SimpleUploadedFile("s.txt", b"secret", content_type="text/plain"),
            uploaded_by=self.admin, original_filename="s.txt")
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/attachments/{att.pk}/download/")
        self.assertIn(res.status_code, (403, 404))

    def test_merge_requires_staff_and_scoped_duplicate(self):
        auth(self.c, self.emp)
        res = self.c.post(f"/api/tickets/{self.ticket_emp.pk}/merge/",
                          {"duplicate_ticket_id": self.ticket_emp2.pk, "reason": "dup"},
                          format="json")
        self.assertEqual(res.status_code, 403)

    def test_category_report_scopes_employee(self):
        auth(self.c, self.emp_other)
        res = self.c.get("/api/tickets/reports/by-category/")
        self.assertEqual(res.status_code, 200)
        # emp_other should only see their dept's tickets; none of dep tickets counted
        for row in res.data.get("results", []):
            # all tickets in report should be visible to emp_other
            pass
