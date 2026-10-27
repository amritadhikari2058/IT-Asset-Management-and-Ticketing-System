"""Ticket bulk/history/report/permission tests.

Asset bulk-safety tests live in assets/tests.py (AssetBulkSafetyTests);
cross-cutting history tests below still touch assets where the flow is
ticket-driven, so Asset imports are kept intentionally."""
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory
from common.models import AuditLog, Notification
from tickets.models import Ticket, TicketCategory


def _notifs(user):
    return Notification.objects.filter(recipient=user)


class BulkAndHistoryTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def test_bulk_ticket_validates_transitions(self):
        auth(self.c, self.mgr)
        t = Ticket.objects.create(title="t", description="d",
                                  category=self.tcat, requester=self.emp,
                                  department=self.dep, status="archived")
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t.pk], "changes": {"status": "open"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["skipped"][0]["id"], t.pk)
        t.refresh_from_db()
        self.assertEqual(t.status, "archived")

    def test_employee_cannot_add_categories(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/assets/categories/", {"name": "X"},
                          format="json")
        self.assertEqual(res.status_code, 403)
        res = self.c.post("/api/tickets/categories/", {"name": "Y"},
                          format="json")
        self.assertEqual(res.status_code, 403)

    def test_new_category_selectable_immediately(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/categories/",
                          {"name": "BrandNew"}, format="json")
        self.assertEqual(res.status_code, 201)
        cid = res.data["id"]
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": cid,
                           "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)

    def test_category_report_counts(self):
        auth(self.c, self.mgr)
        Ticket.objects.create(title="a", description="d",
                              category=self.tcat, requester=self.emp,
                              department=self.dep, status="open",
                              priority="critical")
        Ticket.objects.create(title="b", description="d",
                              category=self.tcat, requester=self.emp,
                              department=self.dep, status="closed")
        res = self.c.get("/api/tickets/reports/by-category/")
        row = [r for r in res.data["results"]
               if r["name"] == "Hardware"][0]
        self.assertEqual(row["total"], 2)
        self.assertEqual(row["open_count"], 1)
        self.assertEqual(row["closed_count"], 1)
        self.assertEqual(row["urgent"], 1)
        # High and Critical are distinguished; urgent stays compatible.
        self.assertEqual(row["high_count"], 0)
        self.assertEqual(row["critical_count"], 1)
        self.assertEqual(row["urgent"],
                         row["high_count"] + row["critical_count"])

    def test_category_report_high_and_critical_split(self):
        auth(self.c, self.mgr)
        for i, pri in enumerate(["high", "high", "critical", "low"]):
            Ticket.objects.create(title=f"t{i}", description="d",
                                  category=self.tcat, requester=self.emp,
                                  department=self.dep, status="open",
                                  priority=pri)
        res = self.c.get("/api/tickets/reports/by-category/")
        row = [r for r in res.data["results"]
               if r["name"] == "Hardware"][0]
        self.assertEqual(row["total"], 4)
        self.assertEqual(row["high_count"], 2)
        self.assertEqual(row["critical_count"], 1)
        self.assertEqual(row["urgent"], 3)

    def test_category_report_omits_zero_count_categories(self):
        auth(self.c, self.mgr)
        TicketCategory.objects.create(name="Empty")
        res = self.c.get("/api/tickets/reports/by-category/")
        names = [r["name"] for r in res.data["results"]]
        self.assertNotIn("Empty", names)

    def test_category_report_date_filter(self):
        from django.utils import timezone
        auth(self.c, self.mgr)
        old = Ticket.objects.create(title="old", description="d",
                                    category=self.tcat, requester=self.emp,
                                    department=self.dep, status="open",
                                    priority="high")
        Ticket.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=30))
        Ticket.objects.create(title="new", description="d",
                              category=self.tcat, requester=self.emp,
                              department=self.dep, status="open",
                              priority="critical")
        res = self.c.get("/api/tickets/reports/by-category/",
                         {"date_from": (timezone.now() -
                                        timezone.timedelta(days=7)).isoformat()})
        row = [r for r in res.data["results"]
               if r["name"] == "Hardware"][0]
        self.assertEqual(row["total"], 1)
        self.assertEqual(row["high_count"], 0)
        self.assertEqual(row["critical_count"], 1)

    def test_category_report_employee_scoping(self):
        from accounts.models import Department
        auth(self.c, self.emp)
        other = Department.objects.create(name="Other", code="OTH2")
        Ticket.objects.create(title="mine", description="d",
                              category=self.tcat, requester=self.emp,
                              department=self.dep, status="open",
                              priority="critical")
        Ticket.objects.create(title="theirs", description="d",
                              category=self.tcat, requester=self.mgr,
                              department=other, status="open",
                              priority="critical")
        res = self.c.get("/api/tickets/reports/by-category/")
        row = [r for r in res.data["results"]
               if r["name"] == "Hardware"][0]
        # Own + home-department tickets only (theirs is invisible).
        self.assertEqual(row["total"], 1)
        self.assertEqual(row["critical_count"], 1)

    def test_employee_cannot_read_privileged_history(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/tickets/histories/")
        self.assertEqual(list(res.data.get("results", res.data)), [])
        res = self.c.get("/api/assets/histories/")
        self.assertEqual(list(res.data.get("results", res.data)), [])

    def test_history_written_for_single_and_bulk(self):
        # Single create via API writes 'created' history (ORM create bypasses
        # views, so history must be asserted on API-created rows).
        auth(self.c, self.mgr)
        res = self.c.post("/api/assets/",
                          {"asset_tag": "H1", "name": "n",
                           "category": self.acat.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        a = Asset.objects.get(asset_tag="H1")
        self.assertEqual(a.history.count(), 1)  # created
        self.c.post("/api/assets/bulk_update/",
                    {"rows": [{"asset_tag": "H1", "location": "Lab"}],
                     "preview": False, "confirm": True}, format="json")
        a.refresh_from_db()
        self.assertEqual(a.history.count(), 2)
        # Ticket created via API writes 'created' history as well.
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": self.tcat.pk,
                           "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.history.count(), 1)


class HistoryFilterTests(TestCase):
    """?ticket= narrows history without widening permissions."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.t1 = Ticket.objects.create(
            title="one", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        self.t2 = Ticket.objects.create(
            title="two", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        from tickets.models import TicketHistory
        TicketHistory.objects.create(ticket=self.t1, actor=self.mgr,
                                     action="note_added")
        TicketHistory.objects.create(ticket=self.t2, actor=self.mgr,
                                     action="note_added")

    def test_filter_by_ticket(self):
        auth(self.c, self.mgr)
        res = self.c.get(f"/api/tickets/histories/?ticket={self.t1.pk}")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if "results" in res.data else res.data
        self.assertTrue(rows)
        self.assertTrue(all(r["ticket"] == self.t1.pk for r in rows))

    def test_employee_still_gets_nothing(self):
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/histories/?ticket={self.t1.pk}")
        rows = res.data.get("results", res.data) if res.status_code == 200 \
            else []
        self.assertEqual(list(rows), [])


class TicketNotificationTests(TestCase):
    """In-app notifications for ticket events: right recipient, no leaks."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def _create(self, **kw):
        auth(self.c, self.mgr)
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        res = self.c.post("/api/tickets/", base, format="json")
        self.assertEqual(res.status_code, 201)
        return Ticket.objects.get(pk=res.data["id"])

    def test_create_notifies_assignee_not_actor(self):
        t = self._create(assignee=self.emp.pk)
        self.assertEqual(_notifs(self.emp).count(), 1)
        n = _notifs(self.emp).first()
        self.assertEqual(n.entity_type, "tickets.Ticket")
        self.assertEqual(n.object_id, str(t.pk))
        self.assertIn("assigned", n.title)
        self.assertEqual(_notifs(self.mgr).count(), 0)

    def test_create_without_assignee_notifies_nobody(self):
        self._create()
        self.assertEqual(Notification.objects.count(), 0)

    def _owned(self, **kw):
        """Ticket requested by emp (ORM), for actor-is-not-requester flows."""
        base = {"title": "t", "description": "d", "category": self.tcat,
                "requester": self.emp, "department": self.dep}
        base.update(kw)
        return Ticket.objects.create(**base)

    def test_status_change_notifies_requester(self):
        t = self._owned()
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_notifs(self.emp).count(), 1)
        self.assertIn("in_progress", _notifs(self.emp).first().title)
        self.assertEqual(_notifs(self.mgr).count(), 0)

    def test_actor_never_notified_of_own_action(self):
        # Staff requester changes their own ticket: allowed, but the
        # actor-requester is still not notified of their own action.
        # (Employees can no longer change status at all â€” see
        # TicketUpdatePermissionsTests.)
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": self.tcat.pk,
                           "department": self.dep.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.requester, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_notifs(self.mgr).count(), 0)
        self.assertEqual(_notifs(self.emp).count(), 0)

    def test_reassign_notifies_new_assignee_only(self):
        t = self._create(assignee=self.emp.pk)
        self.assertEqual(_notifs(self.emp).count(), 1)
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"assignee": self.admin.pk}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_notifs(self.admin).count(), 1)
        # Old assignee gets nothing new; actor gets nothing.
        self.assertEqual(_notifs(self.emp).count(), 1)
        self.assertEqual(_notifs(self.mgr).count(), 0)

    def test_public_note_notifies_requester_and_assignee(self):
        t = self._owned(assignee=self.admin)
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/tickets/{t.pk}/notes/",
                          {"body": "visible update", "is_internal": False},
                          format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(_notifs(self.emp).count(), 1)
        self.assertIn("visible update",
                      _notifs(self.emp).first().body)
        self.assertEqual(_notifs(self.admin).count(), 1)

    def test_internal_note_notifies_nobody_and_never_leaks(self):
        t = self._create(assignee=self.admin.pk)
        before = Notification.objects.count()
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/tickets/{t.pk}/notes/",
                          {"body": "SECRET-INTERNAL-XYZ",
                           "is_internal": True},
                          format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Notification.objects.count(), before)
        blob = " ".join(Notification.objects.values_list("body", flat=True))
        self.assertNotIn("SECRET-INTERNAL-XYZ", blob)

    def test_bulk_update_notifies_per_row(self):
        t = self._owned()
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t.pk],
                           "changes": {"status": "in_progress",
                                       "assignee": self.admin.pk},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_notifs(self.emp).count(), 1)  # status
        self.assertEqual(_notifs(self.admin).count(), 1)  # assignment
        self.assertEqual(_notifs(self.mgr).count(), 0)

    def test_list_shows_only_own_notifications(self):
        self._create(assignee=self.emp.pk)
        auth(self.c, self.emp)
        res = self.c.get("/api/common/notifications/")
        rows = res.data["results"] if "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/notifications/")
        rows = res.data["results"] if "results" in res.data else res.data
        self.assertEqual(list(rows), [])


class TicketUpdatePermissionsTests(TestCase):
    """Employees may edit own-ticket content but never change staff-only
    fields (assignee/status/priority/category/resolution_notes) â€” single
    or bulk."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.tcat2 = TicketCategory.objects.create(name="Software")
        self.own = Ticket.objects.create(
            title="mine", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        self.dept_ticket = Ticket.objects.create(
            title="dept", description="d", category=self.tcat,
            requester=self.mgr, department=self.dep)

    def test_employee_cannot_change_assignee(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"assignee": self.admin.pk}, format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertIsNone(self.own.assignee)

    def test_employee_cannot_unassign_via_null(self):
        self.own.assignee = self.mgr
        self.own.save(update_fields=["assignee"])
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"assignee": None}, format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.assignee, self.mgr)

    def test_employee_cannot_change_status(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, "open")

    def test_employee_cannot_change_priority_or_category(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"priority": "critical"}, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"category": self.tcat2.pk}, format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.priority, "medium")
        self.assertEqual(self.own.category, self.tcat)

    def test_employee_can_edit_own_content(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"title": "mine v2",
                            "description": "more detail"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.title, "mine v2")

    def test_employee_resubmit_unchanged_staff_fields_ok(self):
        # The edit form always reposts priority/category/status; echoes pass.
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"title": "mine v2", "priority": "medium",
                            "category": self.tcat.pk, "status": "open",
                            "assignee": None}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_employee_cannot_touch_home_dept_ticket_fields(self):
        # Visible via home department, but staff-only mutation still denied.
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.dept_ticket.pk}/",
                           {"priority": "high"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.dept_ticket.refresh_from_db()
        self.assertEqual(self.dept_ticket.priority, "medium")

    def test_employee_bulk_update_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [self.own.pk],
                           "changes": {"priority": "high"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.priority, "medium")

    def test_staff_can_still_assign_and_transition(self):
        auth(self.c, self.mgr)
        before = self.own.history.count()
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"assignee": self.admin.pk,
                            "status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.assignee, self.admin)
        self.assertEqual(self.own.status, "in_progress")
        self.assertGreater(self.own.history.count(), before)

    def test_employee_cannot_change_resolution_notes(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"resolution_notes": "fixed it"},
                           format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.resolution_notes, "")

    def test_employee_resubmit_unchanged_resolution_notes_ok(self):
        self.own.resolution_notes = "known fix"
        self.own.save(update_fields=["resolution_notes"])
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"title": "mine v2",
                            "resolution_notes": "known fix"},
                           format="json")
        self.assertEqual(res.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.title, "mine v2")
        self.assertEqual(self.own.resolution_notes, "known fix")

    def test_staff_can_set_resolution_notes(self):
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{self.own.pk}/",
                           {"status": "resolved",
                            "resolution_notes": "replaced toner"},
                           format="json")
        self.assertEqual(res.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, "resolved")
        self.assertEqual(self.own.resolution_notes, "replaced toner")


class TicketDeletePermissionsTests(TestCase):
    """Ticket soft-deletion (single + bulk) is IT-staff-only."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.own = Ticket.objects.create(
            title="mine", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        self.other = Ticket.objects.create(
            title="dept", description="d", category=self.tcat,
            requester=self.mgr, department=self.dep)

    def test_employee_single_delete_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.delete(f"/api/tickets/{self.own.pk}/")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.assertFalse(self.own.is_deleted)

    def test_employee_bulk_delete_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/bulk_delete/",
                          {"ids": [self.own.pk, self.other.pk],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 403)
        self.own.refresh_from_db()
        self.other.refresh_from_db()
        self.assertFalse(self.own.is_deleted)
        self.assertFalse(self.other.is_deleted)

    def test_staff_can_soft_delete_with_history_and_audit(self):
        auth(self.c, self.mgr)
        before_history = self.own.history.count()
        res = self.c.delete(f"/api/tickets/{self.own.pk}/")
        self.assertEqual(res.status_code, 204)
        self.own.refresh_from_db()
        self.assertTrue(self.own.is_deleted)
        self.assertGreater(self.own.history.count(), before_history)
        self.assertTrue(self.own.history.filter(
            action="soft_deleted").exists())
        self.assertTrue(AuditLog.objects.filter(
            entity_type="tickets.ticket", object_id=str(self.own.pk),
            action="soft_delete").exists())
        # Hidden from ordinary queries, visible with_deleted.
        self.assertFalse(Ticket.objects.filter(pk=self.own.pk).exists())
        self.assertTrue(Ticket.all_objects.filter(
            pk=self.own.pk).exists())

    def test_staff_can_bulk_delete(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_delete/",
                          {"ids": [self.own.pk, self.other.pk],
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(res.data["successful"]),
                         sorted([self.own.pk, self.other.pk]))
        self.assertTrue(Ticket.all_objects.get(
            pk=self.own.pk).is_deleted)
        self.assertTrue(Ticket.all_objects.get(
            pk=self.other.pk).is_deleted)

    def test_out_of_scope_id_not_deletable_by_employee(self):
        from accounts.models import Department as Dept
        other_dep = Dept.objects.create(name="Far", code="FAR")
        hidden = Ticket.objects.create(
            title="hidden", description="d", category=self.tcat,
            requester=self.admin, department=other_dep)
        auth(self.c, self.emp)
        res = self.c.delete(f"/api/tickets/{hidden.pk}/")
        self.assertEqual(res.status_code, 403)
        hidden.refresh_from_db()
        self.assertFalse(hidden.is_deleted)

    def test_admin_can_delete_and_restore_flow_intact(self):
        auth(self.c, self.admin)
        res = self.c.delete(f"/api/tickets/{self.own.pk}/")
        self.assertEqual(res.status_code, 204)
        res = self.c.post(
            f"/api/recycle-bin/tickets.Ticket/{self.own.pk}/restore/",
            {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.own.refresh_from_db()
        self.assertFalse(self.own.is_deleted)


class TicketAssigneeValidationTests(TestCase):
    """Non-null assignees must exist, be non-deleted, and be active;
    employees cannot choose an assignee at creation."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.inactive = User.objects.create_user(
            username="i@x", email="i@x", employee_id="I1",
            password="pw12345678", role="employee",
            home_department=self.dep, is_active=False)
        self.gone = User.objects.create_user(
            username="g@x", email="g@x", employee_id="G1",
            password="pw12345678", role="employee",
            home_department=self.dep)
        self.gone.soft_delete(by_user=self.admin, reason="left")
        self.t = Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)

    def _base_payload(self):
        return {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}

    def _counts(self, ticket):
        from tickets.models import TicketHistory
        return (ticket.history.count(),
                AuditLog.objects.filter(entity_type="tickets.ticket",
                                        object_id=str(ticket.pk)).count(),
                Notification.objects.filter(
                    object_id=str(ticket.pk)).count())

    # ---- single update ----

    def test_staff_assign_active_succeeds(self):
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{self.t.pk}/",
                           {"assignee": self.admin.pk}, format="json")
        self.assertEqual(res.status_code, 200)
        self.t.refresh_from_db()
        self.assertEqual(self.t.assignee, self.admin)
        self.assertTrue(Notification.objects.filter(
            recipient=self.admin, object_id=str(self.t.pk)).exists())

    def test_assign_inactive_returns_400_unchanged(self):
        auth(self.c, self.mgr)
        before = self._counts(self.t)
        res = self.c.patch(f"/api/tickets/{self.t.pk}/",
                           {"assignee": self.inactive.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("assignee", res.data)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)
        self.assertEqual(self._counts(self.t), before)

    def test_assign_unknown_returns_400(self):
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{self.t.pk}/",
                           {"assignee": 999999}, format="json")
        self.assertEqual(res.status_code, 400)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    def test_assign_soft_deleted_returns_400(self):
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{self.t.pk}/",
                           {"assignee": self.gone.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    def test_explicit_null_unassigns(self):
        self.t.assignee = self.admin
        self.t.save(update_fields=["assignee"])
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/tickets/{self.t.pk}/",
                           {"assignee": None}, format="json")
        self.assertEqual(res.status_code, 200)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    # ---- creation ----

    def test_staff_create_with_active_assignee(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/",
                          {**self._base_payload(),
                           "assignee": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.assignee, self.emp)

    def test_staff_create_with_inactive_assignee(self):
        auth(self.c, self.mgr)
        n_before = Ticket.objects.count()
        res = self.c.post("/api/tickets/",
                          {**self._base_payload(),
                           "assignee": self.inactive.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("assignee", res.data)
        self.assertEqual(Ticket.objects.count(), n_before)

    def test_employee_create_with_assignee_forbidden(self):
        auth(self.c, self.emp)
        n_before = Ticket.objects.count()
        res = self.c.post("/api/tickets/",
                          {**self._base_payload(),
                           "assignee": self.mgr.pk}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Ticket.objects.count(), n_before)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertFalse(AuditLog.objects.filter(action="create").exists())

    def test_employee_create_without_assignee_ok(self):
        auth(self.c, self.emp)
        for payload in (self._base_payload(),
                        {**self._base_payload(), "assignee": None}):
            res = self.c.post("/api/tickets/", payload, format="json")
            self.assertEqual(res.status_code, 201)
            t = Ticket.objects.get(pk=res.data["id"])
            self.assertIsNone(t.assignee)

    # ---- bulk update ----

    def _bulk(self, changes, *tickets):
        auth(self.c, self.mgr)
        return self.c.post("/api/tickets/bulk_update/",
                           {"ids": [t.pk for t in tickets], "changes": changes,
                            "preview": False, "confirm": True}, format="json")

    def test_bulk_inactive_assignee_failed_unchanged(self):
        res = self._bulk({"assignee": self.inactive.pk}, self.t)
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0,
                                               "failed": 1})
        self.assertIn("inactive", res.data["failed"][0]["errors"])
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)
        self.assertEqual(self._counts(self.t), (0, 0, 0))

    def test_bulk_unknown_assignee_failed_not_unassigned(self):
        res = self._bulk({"assignee": 999999}, self.t)
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0,
                                               "failed": 1})
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    def test_bulk_soft_deleted_assignee_failed(self):
        res = self._bulk({"assignee": self.gone.pk}, self.t)
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0,
                                               "failed": 1})
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    def test_bulk_valid_assignee_with_side_effects(self):
        res = self._bulk({"assignee": self.admin.pk}, self.t)
        self.assertEqual(res.data["summary"], {"ok": 1, "skipped": 0,
                                               "failed": 0})
        self.t.refresh_from_db()
        self.assertEqual(self.t.assignee, self.admin)
        self.assertTrue(self.t.history.filter(action="bulk_change").exists())
        self.assertTrue(AuditLog.objects.filter(
            entity_type="tickets.ticket", object_id=str(self.t.pk),
            action="bulk_update").exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.admin, object_id=str(self.t.pk)).exists())

    def test_bulk_null_unassigns(self):
        self.t.assignee = self.admin
        self.t.save(update_fields=["assignee"])
        res = self._bulk({"assignee": None}, self.t)
        self.assertEqual(res.data["summary"], {"ok": 1, "skipped": 0,
                                               "failed": 0})
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    def test_bulk_mixed_rows_partial_success(self):
        t2 = Ticket.objects.create(
            title="u", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [self.t.pk, t2.pk],
                           "changes": {"assignee": self.inactive.pk},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0,
                                               "failed": 2})
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [t2.pk],
                           "changes": {"assignee": self.admin.pk},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"], {"ok": 1, "skipped": 0,
                                               "failed": 0})
        t2.refresh_from_db()
        self.assertEqual(t2.assignee, self.admin)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)

    def test_bulk_invalid_assignee_blocks_sibling_changes(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_update/",
                          {"ids": [self.t.pk],
                           "changes": {"assignee": self.inactive.pk,
                                       "status": "in_progress",
                                       "priority": "high"},
                           "preview": False, "confirm": True}, format="json")
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0,
                                               "failed": 1})
        self.t.refresh_from_db()
        self.assertIsNone(self.t.assignee)
        self.assertEqual(self.t.status, "open")
        self.assertEqual(self.t.priority, "medium")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketUpdateAtomicityTests(TestCase):
    """Single update commits ticket + history + audit + notifications
    together; email never rolls back (or ghosts) the update."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.t = Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        auth(self.c, self.mgr)

    def _patch(self, payload):
        return self.c.patch(f"/api/tickets/{self.t.pk}/", payload,
                            format="json")

    def _db_state(self):
        self.t.refresh_from_db()
        return {
            "title": self.t.title,
            "status": self.t.status,
            "assignee": self.t.assignee_id,
            "history": list(self.t.history.values_list("action",
                                                       flat=True)),
            "audits": sorted(AuditLog.objects.filter(
                entity_type="tickets.ticket",
                object_id=str(self.t.pk)).values_list("action", flat=True)),
            "notifs": sorted(Notification.objects.filter(
                object_id=str(self.t.pk)).values_list("title", flat=True)),
            "mails": len(mail.outbox),
        }

    def test_success_commits_everything_once(self):
        res = self._patch({"title": "t2", "assignee": self.admin.pk,
                           "status": "in_progress"})
        self.assertEqual(res.status_code, 200)
        state = self._db_state()
        self.assertEqual(state["title"], "t2")
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(state["assignee"], self.admin.pk)
        self.assertEqual(sorted(state["history"]), ["status_change",
                                                    "updated"])
        self.assertEqual(state["audits"], ["status_change", "update"])
        # Exactly one assignee + one status notification, one email.
        self.assertEqual(len(state["notifs"]), 2)
        self.assertEqual(state["mails"], 1)

    def test_history_failure_rolls_back_everything(self):
        with patch("tickets.views._write_history",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self._patch({"title": "t2", "status": "in_progress"})
        state = self._db_state()
        self.assertEqual(state["title"], "t")
        self.assertEqual(state["status"], "open")
        self.assertEqual(state["history"], [])
        self.assertEqual(state["audits"], [])
        self.assertEqual(state["notifs"], [])
        self.assertEqual(state["mails"], 0)

    def test_final_audit_failure_rolls_back_without_ghost_email(self):
        from common.audit import log_action as real_log_action

        def fail_on_update(*args, **kwargs):
            if kwargs.get("action") == "update":
                raise RuntimeError("audit db down")
            return real_log_action(*args, **kwargs)

        with patch("tickets.views.log_action",
                   side_effect=fail_on_update):
            with self.assertRaises(RuntimeError):
                self._patch({"title": "t2", "status": "in_progress"})
        state = self._db_state()
        self.assertEqual(state["title"], "t")
        self.assertEqual(state["history"], [])
        self.assertEqual(state["audits"], [])
        self.assertEqual(state["notifs"], [])
        # Rolled back BEFORE any mail could go out: no ghost email.
        self.assertEqual(state["mails"], 0)

    def test_email_failure_does_not_roll_back(self):
        with patch("accounts.email_utils.send_ticket_notification",
                   side_effect=RuntimeError("smtp down")):
            res = self._patch({"title": "t2", "status": "in_progress"})
        self.assertEqual(res.status_code, 200)
        state = self._db_state()
        self.assertEqual(state["title"], "t2")
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(sorted(state["history"]), ["status_change",
                                                    "updated"])
        self.assertEqual(state["audits"], ["status_change", "update"])
        self.assertEqual(len(state["notifs"]), 1)  # requester only
        self.assertEqual(state["mails"], 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketCreateAtomicityTests(TestCase):
    """Creation commits ticket + history + audit + notification together;
    email goes out only after commit and never rolls anything back."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        auth(self.c, self.mgr)

    def _create(self, **kw):
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        return self.c.post("/api/tickets/", base, format="json")

    def test_success_commits_everything_once(self):
        res = self._create(assignee=self.emp.pk)
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(list(t.history.values_list("action", flat=True)),
                         ["created"])
        self.assertEqual(list(AuditLog.objects.filter(
            entity_type="tickets.ticket",
            object_id=str(t.pk)).values_list("action", flat=True)),
            ["create"])
        self.assertEqual(Notification.objects.filter(
            object_id=str(t.pk)).count(), 1)
        # Requester mail + assignee mail, exactly once each.
        self.assertEqual(len(mail.outbox), 2)

    def test_history_failure_rolls_back_ticket(self):
        with patch("tickets.views._write_history",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self._create(assignee=self.emp.pk)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_late_failure_sends_no_ghost_email(self):
        with patch("tickets.views._notify_user",
                   side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self._create(assignee=self.emp.pk)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_failure_leaves_commit(self):
        with patch("accounts.email_utils.send_ticket_notification",
                   side_effect=RuntimeError("smtp down")):
            res = self._create(assignee=self.emp.pk)
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.history.count(), 1)
        self.assertTrue(AuditLog.objects.filter(
            entity_type="tickets.ticket", object_id=str(t.pk),
            action="create").exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())
        self.assertEqual(len(mail.outbox), 0)


class TicketCreateRequesterTests(TestCase):
    """The requester is always the authenticated caller.

    No `requester` / `on_behalf_of` payload key can impersonate another
    user: `requester` is read-only on the serializer and `perform_create`
    saves with `requester=user`. Staff file cross-department tickets via
    department + reason, still as themselves.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.other_dep = Department.objects.create(name="Other", code="OTH")

    def _base_payload(self):
        return {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}

    def test_employee_cannot_spoof_requester(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/",
                          {**self._base_payload(),
                           "requester": self.mgr.pk,
                           "on_behalf_of": self.mgr.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.requester, self.emp)

    def test_staff_cannot_spoof_requester(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/",
                          {**self._base_payload(),
                           "requester": self.emp.pk,
                           "on_behalf_of": self.emp.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.requester, self.mgr)

    def test_staff_cross_department_needs_reason(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": self.tcat.pk,
                           "department": self.other_dep.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.c.post("/api/tickets/",
                          {"title": "t", "description": "d",
                           "category": self.tcat.pk,
                           "department": self.other_dep.pk,
                           "on_behalf_reason": "covering support"},
                          format="json")
        self.assertEqual(res.status_code, 201)
        t = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(t.requester, self.mgr)
        self.assertEqual(t.department, self.other_dep)

    def test_employee_update_cannot_touch_requester(self):
        t = Ticket.objects.create(
            title="t", description="d", category=self.tcat,
            requester=self.emp, department=self.dep)
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"title": "t2", "requester": self.mgr.pk},
                           format="json")
        self.assertEqual(res.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.title, "t2")
        self.assertEqual(t.requester, self.emp)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketBulkCreateTests(TestCase):
    """POST /api/tickets/bulk_create/: per-row single-create semantics."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.other_dep = Department.objects.create(name="Other", code="OTH")
        self.inactive = User.objects.create_user(
            username="i@x", email="i@x", employee_id="I1",
            password="pw12345678", role="employee",
            home_department=self.dep, is_active=False)

    def _row(self, **kw):
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        return base

    def _confirm(self, rows):
        return self.c.post("/api/tickets/bulk_create/",
                           {"tickets": rows, "preview": False,
                            "confirm": True}, format="json")

    def test_staff_bulk_creates_with_side_effects(self):
        auth(self.c, self.mgr)
        res = self._confirm([self._row(title="one"),
                             self._row(title="two",
                                       assignee=self.emp.pk)])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 2, "skipped": 0, "failed": 0})
        ids = [s["id"] for s in res.data["successful"]]
        self.assertEqual(len(ids), 2)
        for pk in ids:
            t = Ticket.objects.get(pk=pk)
            self.assertEqual(t.requester, self.mgr)
            self.assertTrue(t.history.filter(action="created").exists())
            self.assertTrue(AuditLog.objects.filter(
                entity_type="tickets.ticket", object_id=str(pk),
                action="create").exists())
        two = Ticket.objects.get(pk=ids[1])
        self.assertEqual(two.assignee, self.emp)
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(two.pk)).exists())
        # Requester mails (2) + assignee mail (1), no duplicates.
        self.assertEqual(len(mail.outbox), 3)

    def test_no_permission_user_rejected(self):
        self.emp.can_create_tickets = False
        self.emp.save(update_fields=["can_create_tickets"])
        auth(self.c, self.emp)
        res = self._confirm([self._row()])
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_employee_creates_own_but_not_assignee(self):
        auth(self.c, self.emp)
        res = self._confirm([self._row(title="mine"),
                             self._row(title="bad",
                                       assignee=self.mgr.pk)])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 1})
        mine = Ticket.objects.get(title="mine")
        self.assertEqual(mine.requester, self.emp)
        self.assertIsNone(mine.assignee)
        self.assertIn("assign", res.data["failed"][0]["errors"]["assignee"])

    def test_requester_spoof_ignored(self):
        auth(self.c, self.emp)
        res = self._confirm([dict(self._row(), requester=self.mgr.pk,
                                  on_behalf_of=self.mgr.pk)])
        self.assertEqual(res.data["summary"]["ok"], 1)
        t = Ticket.objects.get(title="t")
        self.assertEqual(t.requester, self.emp)

    def test_invalid_rows_create_nothing(self):
        auth(self.c, self.mgr)
        res = self._confirm([
            {"description": "no title", "category": self.tcat.pk},
            self._row(title="badcat", category=999999),
            self._row(title="cross", department=self.other_dep.pk),
            self._row(title="inactive", assignee=self.inactive.pk),
        ])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 4})
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_cross_dept_with_reason_and_partial_success(self):
        auth(self.c, self.mgr)
        res = self._confirm([
            self._row(title="good"),
            self._row(title="xdept", department=self.other_dep.pk,
                      on_behalf_reason="covering support"),
            {"title": "", "description": "d",
             "category": self.tcat.pk},
        ])
        self.assertEqual(res.data["summary"],
                         {"ok": 2, "skipped": 0, "failed": 1})
        xdept = Ticket.objects.get(title="xdept")
        self.assertEqual(xdept.department, self.other_dep)
        self.assertEqual(xdept.requester, self.mgr)

    def test_preview_writes_nothing_and_confirm_required(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": [self._row()]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["affected"], 1)
        self.assertEqual(Ticket.objects.count(), 0)
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": [self._row()], "preview": False},
                          format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Ticket.objects.count(), 0)
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": "nope", "preview": False,
                           "confirm": True}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_email_preference_respected_per_recipient(self):
        self.emp.receive_ticket_emails = False
        self.emp.save(update_fields=["receive_ticket_emails"])
        auth(self.c, self.mgr)
        res = self._confirm([self._row(title="one", assignee=self.emp.pk)])
        self.assertEqual(res.data["summary"]["ok"], 1)
        t = Ticket.objects.get(title="one")
        # Assignee opted out: notification yes, email no. Requester mailed.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])

    def test_unknown_columns_in_file_upload_are_rejected(self):
        """An uploaded ticket file with unsupported columns is rejected
        with a clear 400 instead of being silently ignored."""
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category,bogus_column\n"
               "My Ticket,a description,1,\n").encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv"),
                "preview": "false", "confirm": "true"}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertIn("bogus_column", str(res.data))
        # Nothing created.
        self.assertEqual(Ticket.objects.count(), 0)


class TicketOrderingTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        auth(self.c, self.mgr)

    def _titles(self, res):
        self.assertEqual(res.status_code, 200)
        data = res.data
        rows = data["results"] if isinstance(data, dict) else data
        return [r["title"] for r in rows]

    def test_priority_sorts_by_severity(self):
        for title, pri in (("lo", "low"), ("crit", "critical"),
                           ("med", "medium"), ("hi", "high")):
            Ticket.objects.create(title=title, description="d",
                                  category=self.tcat, requester=self.emp,
                                  department=self.dep, priority=pri)
        res = self.c.get("/api/tickets/", {"ordering": "priority"})
        self.assertEqual(self._titles(res), ["lo", "med", "hi", "crit"])
        res = self.c.get("/api/tickets/", {"ordering": "-priority"})
        self.assertEqual(self._titles(res), ["crit", "hi", "med", "lo"])

    def test_unsupported_ordering_falls_back_to_default(self):
        Ticket.objects.create(title="a", description="d",
                              category=self.tcat, requester=self.emp,
                              department=self.dep)
        Ticket.objects.create(title="b", description="d",
                              category=self.tcat, requester=self.emp,
                              department=self.dep)
        res = self.c.get("/api/tickets/", {"ordering": "password"})
        # Default newest-first is preserved; no error, no leak.
        self.assertEqual(self._titles(res), ["b", "a"])

    def test_tie_break_is_stable(self):
        for title in ("one", "two"):
            Ticket.objects.create(title=title, description="d",
                                  category=self.tcat, requester=self.emp,
                                  department=self.dep, status="open")
        res = self.c.get("/api/tickets/", {"ordering": "status"})
        rows = res.data["results"]
        ids = [r["id"] for r in rows if r["title"] in ("one", "two")]
        self.assertEqual(ids, sorted(ids))


class TicketResolutionTimestampTests(TestCase):
    """resolved_at / closed_at follow real transitions on every path.

    Single-ticket PATCH and the bulk endpoint must apply the same rule:
    -> resolved stamps resolved_at, -> closed stamps closed_at, a reopen
    clears both, and a resubmit of the current status never touches them.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        auth(self.c, self.mgr)

    def _ticket(self, **kw):
        base = {"title": "t", "description": "d", "category": self.tcat,
                "requester": self.emp, "department": self.dep,
                "status": "open"}
        base.update(kw)
        return Ticket.objects.create(**base)

    def _bulk(self, ticket, status):
        return self.c.post("/api/tickets/bulk_update/",
                           {"ids": [ticket.pk], "changes": {"status": status},
                            "preview": False, "confirm": True},
                           format="json")

    # ---------- single-ticket path ----------

    def test_resolving_stamps_resolved_at(self):
        t = self._ticket()
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "resolved"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertIsNotNone(t.resolved_at)
        self.assertIsNone(t.closed_at)
        self.assertIsNotNone(res.data["resolved_at"])
        self.assertIsNone(res.data["closed_at"])

    def test_closing_stamps_closed_at(self):
        t = self._ticket()
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "closed"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertIsNotNone(t.closed_at)
        self.assertIsNone(t.resolved_at)

    def test_reopening_clears_both_timestamps(self):
        t = self._ticket(status="resolved", resolved_at=timezone.now(),
                         closed_at=timezone.now())
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "reopened"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertEqual(t.status, "reopened")
        self.assertIsNone(t.resolved_at)
        self.assertIsNone(t.closed_at)

    def test_resubmitting_the_current_status_keeps_the_stamp(self):
        stamp = timezone.now()
        t = self._ticket(status="resolved", resolved_at=stamp)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "resolved", "title": "edited"},
                           format="json")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertEqual(t.title, "edited")
        self.assertEqual(t.resolved_at, stamp)

    def test_unrelated_edit_never_touches_the_timestamps(self):
        stamp = timezone.now()
        t = self._ticket(status="closed", closed_at=stamp,
                         resolved_at=stamp)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"resolution_notes": "Fixed at the desk."},
                           format="json")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertEqual(t.closed_at, stamp)
        self.assertEqual(t.resolved_at, stamp)

    def test_rejected_transition_leaves_timestamps_untouched(self):
        t = self._ticket()  # open -> reopened is not a valid move
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "reopened"}, format="json")
        self.assertEqual(res.status_code, 400)
        t.refresh_from_db()
        self.assertEqual(t.status, "open")
        self.assertIsNone(t.resolved_at)
        self.assertIsNone(t.closed_at)

    def test_employee_edit_cannot_forge_status_timestamps(self):
        auth(self.c, self.emp)
        t = self._ticket(requester=self.emp)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "resolved"}, format="json")
        self.assertEqual(res.status_code, 403)
        t.refresh_from_db()
        self.assertIsNone(t.resolved_at)

    # ---------- bulk path ----------

    def test_bulk_resolve_stamps_and_bulk_reopen_clears(self):
        t = self._ticket()
        res = self._bulk(t, "resolved")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertIsNotNone(t.resolved_at)
        self.assertIsNone(t.closed_at)

        res = self._bulk(t, "reopened")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertIsNone(t.resolved_at)
        self.assertIsNone(t.closed_at)

    def test_bulk_close_stamps_closed_at(self):
        t = self._ticket()
        res = self._bulk(t, "closed")
        self.assertEqual(res.status_code, 200, res.data)
        t.refresh_from_db()
        self.assertIsNotNone(t.closed_at)
        self.assertIsNone(t.resolved_at)

    def test_bulk_same_status_never_touches_timestamps(self):
        stamp = timezone.now()
        t = self._ticket(status="resolved", resolved_at=stamp)
        res = self._bulk(t, "resolved")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["successful"], [t.pk])
        t.refresh_from_db()
        self.assertEqual(t.resolved_at, stamp)

    def test_bulk_invalid_transition_skips_the_row_and_the_stamp(self):
        t = self._ticket()  # open -> reopened is invalid
        res = self._bulk(t, "reopened")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data["skipped"]), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "open")
        self.assertIsNone(t.resolved_at)
        self.assertIsNone(t.closed_at)

    def test_both_paths_agree_on_the_same_transition(self):
        single = self._ticket()
        bulk = self._ticket()
        self.c.patch(f"/api/tickets/{single.pk}/",
                     {"status": "resolved"}, format="json")
        self._bulk(bulk, "resolved")
        single.refresh_from_db()
        bulk.refresh_from_db()
        self.assertIsNotNone(single.resolved_at)
        self.assertIsNotNone(bulk.resolved_at)
        self.assertEqual(single.resolved_at is None, bulk.resolved_at is None)


class TicketCategoryEditTests(TestCase):
    """Category EDIT flow: staff-only PATCH, duplicate handling, and
    preserved ticket relationships after a rename."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)
        self.tcat = TicketCategory.objects.create(
            name="Hardware", description="Old")

    def test_staff_edits_name_and_description(self):
        res = self.c.patch(
            f"/api/tickets/categories/{self.tcat.pk}/",
            {"name": "Hardware & Peripherals",
             "description": "Desktops, laptops, printers."},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.tcat.refresh_from_db()
        self.assertEqual(self.tcat.name, "Hardware & Peripherals")
        self.assertEqual(self.tcat.description,
                         "Desktops, laptops, printers.")

    def test_edit_preserves_ticket_relationship(self):
        t = Ticket.objects.create(title="t", description="d",
                                  category=self.tcat, requester=self.emp,
                                  department=self.dep)
        res = self.c.patch(f"/api/tickets/categories/{self.tcat.pk}/",
                           {"name": "Renamed"}, format="json")
        self.assertEqual(res.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.category_id, self.tcat.pk)
        self.assertEqual(t.category.name, "Renamed")

    def test_duplicate_name_rejected_with_field_error(self):
        TicketCategory.objects.create(name="Software")
        res = self.c.patch(f"/api/tickets/categories/{self.tcat.pk}/",
                           {"name": "Software"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data)
        self.tcat.refresh_from_db()
        self.assertEqual(self.tcat.name, "Hardware")

    def test_employee_cannot_edit_categories(self):
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/categories/{self.tcat.pk}/",
                           {"name": "X"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.tcat.refresh_from_db()
        self.assertEqual(self.tcat.name, "Hardware")

    def test_blank_name_rejected(self):
        res = self.c.patch(f"/api/tickets/categories/{self.tcat.pk}/",
                           {"name": "   "}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data)
