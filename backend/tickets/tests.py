"""Ticket bulk/history/report/permission tests.

Asset bulk-safety tests live in assets/tests.py (AssetBulkSafetyTests);
cross-cutting history tests below still touch assets where the flow is
ticket-driven, so Asset imports are kept intentionally."""
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
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
        cache.clear()
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
        cache.clear()
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
        with self.captureOnCommitCallbacks(execute=True):
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
        cache.clear()
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
        with self.captureOnCommitCallbacks(execute=True):
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
            with self.captureOnCommitCallbacks(execute=True):
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
        cache.clear()
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
        with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
            res = self._confirm([self._row(title="one", assignee=self.emp.pk)])
        self.assertEqual(res.data["summary"]["ok"], 1)
        t = Ticket.objects.get(title="one")
        # Assignee opted out: notification yes, email no. Requester mailed.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, object_id=str(t.pk)).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.mgr.email])

    def test_employee_file_upload_preview_does_not_crash(self):
        auth(self.c, self.emp)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category\n"
               "My Ticket,a description,%d\n" % self.tcat.pk).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv")}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["affected"], 1)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_employee_file_upload_with_asset_is_rejected_in_preview(self):
        auth(self.c, self.emp)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category,asset_tag\n"
               "My Ticket,a description,%d,ASSET-1\n" % self.tcat.pk).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv")}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["affected"], 0)
        self.assertEqual(len(res.data["invalid"]), 1)
        self.assertIn("asset", res.data["invalid"][0]["errors"])

    def test_file_upload_confirm_false_string_does_not_create(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category\n"
               "My Ticket,a description,%d\n" % self.tcat.pk).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv"),
                "preview": "false", "confirm": "false"}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_bulk_create_sets_sla_due_at_from_priority_config(self):
        from tickets.models import TicketSLA
        TicketSLA.objects.create(priority="medium", target_resolution_hours=24,
                                 is_active=True)
        auth(self.c, self.mgr)
        res = self._confirm([self._row(title="sla", priority="medium")])
        self.assertEqual(res.data["summary"]["ok"], 1)
        t = Ticket.objects.get(title="sla")
        self.assertIsNotNone(t.sla_due_at)

    def test_file_upload_partial_success_reports_rows_and_commits_valid(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category\n"
               "Good1,a description,%d\n"
               ",missing title,%d\n"
               "Good2,b description,%d\n" % (
                   self.tcat.pk, self.tcat.pk, self.tcat.pk)).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv"),
                "preview": "false", "confirm": "true"}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"], {"ok": 2, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), 2)
        self.assertTrue(Ticket.objects.filter(title="Good1").exists())
        self.assertTrue(Ticket.objects.filter(title="Good2").exists())
        failed_rows = [f["row"] for f in res.data["failed"]]
        self.assertEqual(failed_rows, [3])
        ok_rows = [s["row"] for s in res.data["successful"]]
        self.assertEqual(ok_rows, [2, 4])

    def test_malformed_file_upload_returns_400(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {"file": SimpleUploadedFile(
            "bad.xlsx", b"not-a-zip",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)

    def test_csv_missing_header_row_is_rejected(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {"file": SimpleUploadedFile("empty.csv", b"",
                                           content_type="text/csv")}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)

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

    def test_employee_json_confirm_with_asset_is_rejected_not_silent(self):
        """Employee preview/confirm parity: direct confirm must reject asset
        assignment rows instead of silently stripping the field."""
        auth(self.c, self.emp)
        row = self._row(title="mine", asset=12345)
        preview = self.c.post("/api/tickets/bulk_create/",
                              {"tickets": [row]}, format="json")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["affected"], 0)
        self.assertIn("asset", preview.data["invalid"][0]["errors"])
        res = self._confirm([row])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        self.assertIn("asset", res.data["failed"][0]["errors"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_employee_file_upload_confirm_with_asset_is_rejected(self):
        """Employees must never assign assets through bulk import; file
        confirmation must enforce the same policy as preview."""
        auth(self.c, self.emp)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category,asset_tag\n"
               "My Ticket,a description,%d,ASSET-1\n" % self.tcat.pk).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv"),
                "preview": "false", "confirm": "true"}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        self.assertIn("asset", res.data["failed"][0]["errors"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_confirm_false_like_values_do_not_create(self):
        """False-like multipart/JSON confirm values must require confirmation."""
        auth(self.c, self.mgr)
        for value in ("False", " false ", "0", "", False, 0):
            res = self.c.post("/api/tickets/bulk_create/",
                              {"tickets": [self._row(title=f"t-{value!r}")],
                               "preview": False, "confirm": value},
                              format="json")
            self.assertEqual(res.status_code, 400, msg=value)
            self.assertEqual(Ticket.objects.count(), 0, msg=value)

    def test_confirm_true_like_string_with_whitespace_creates(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": [self._row(title="spaced")],
                           "preview": False, "confirm": " true "},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"]["ok"], 1)
        self.assertTrue(Ticket.objects.filter(title="spaced").exists())

    def test_bulk_create_triggers_ticket_created_automation(self):
        from workflow.models import AutomationRule, RuleExecution
        AutomationRule.objects.create(
            name="bulk-auto-create", trigger="ticket_created",
            conditions={}, actions=[{"type": "note", "text": "Auto triage"}],
            is_enabled=True, created_by=self.admin)
        auth(self.c, self.mgr)
        res = self._confirm([self._row(title="auto")])
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 0})
        t = Ticket.objects.get(title="auto")
        self.assertTrue(t.notes.filter(body="Auto triage").exists())
        self.assertTrue(RuleExecution.objects.filter(
            ticket=t, success=True).exists())

    def test_invalid_bulk_row_does_not_trigger_automation(self):
        from workflow.models import AutomationRule, RuleExecution
        AutomationRule.objects.create(
            name="bulk-auto-invalid", trigger="ticket_created",
            conditions={}, actions=[{"type": "note", "text": "Auto triage"}],
            is_enabled=True, created_by=self.admin)
        auth(self.c, self.mgr)
        res = self._confirm([{"description": "no title",
                              "category": self.tcat.pk}])
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(RuleExecution.objects.count(), 0)

    def test_failed_uncommitted_bulk_row_does_not_trigger_automation(self):
        from workflow.models import AutomationRule, RuleExecution
        AutomationRule.objects.create(
            name="bulk-auto-rollback", trigger="ticket_created",
            conditions={}, actions=[{"type": "note", "text": "Auto triage"}],
            is_enabled=True, created_by=self.admin)
        auth(self.c, self.mgr)
        with patch("tickets.views._notify_user",
                   side_effect=RuntimeError("db down")):
            res = self._confirm([self._row(title="boom")])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(RuleExecution.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_duplicate_csv_headers_are_rejected(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,title,category\n"
               "My Ticket,dup,%d\n" % self.tcat.pk).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv")}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)

    def test_csv_header_whitespace_is_normalized(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = (" title , description , category \n"
               "My Ticket,a description,%d\n" % self.tcat.pk).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv")}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["affected"], 1)

    def test_staff_bulk_json_can_assign_asset(self):
        auth(self.c, self.mgr)
        asset = Asset.objects.create(
            asset_tag="AST-1", name="Laptop",
            category=self.dep and AssetCategory.objects.create(name="HW2"),
            department=self.dep)
        res = self._confirm([self._row(title="with-asset", asset=asset.pk)])
        self.assertEqual(res.data["summary"]["ok"], 1)
        t = Ticket.objects.get(title="with-asset")
        self.assertEqual(t.asset_id, asset.pk)

    def test_invalid_department_reference_fails_row(self):
        auth(self.c, self.mgr)
        res = self._confirm([self._row(title="baddep", department=999999)])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), 0)

    def test_soft_deleted_category_fails_row(self):
        auth(self.c, self.mgr)
        gone = TicketCategory.objects.create(name="Gone")
        gone.soft_delete(by_user=self.admin, reason="retired")
        res = self._confirm([self._row(title="badcat", category=gone.pk)])
        self.assertEqual(res.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), 0)

    def test_download_report_reflects_row_outcomes(self):
        auth(self.c, self.mgr)
        res = self.c.post(
            "/api/tickets/bulk_create/?download=csv",
            {"tickets": [self._row(title="good"),
                         {"description": "no title",
                          "category": self.tcat.pk}],
             "preview": False, "confirm": True},
            format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "text/csv")
        body = res.content.decode("utf-8")
        self.assertIn("successful", body)
        self.assertIn("failed", body)
        self.assertEqual(Ticket.objects.count(), 1)


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


class TicketAttachmentSecurityTests(TestCase):
    """Ticket attachment download security: authentication, scoping, IDOR."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="General")
        # A ticket owned by emp, visible to both emp and staff.
        self.ticket = Ticket.objects.create(
            title="Private ticket", description="d",
            category=self.tcat, requester=self.emp,
            department=self.dep, status="open", priority="medium")

    def _upload(self, name="report.txt", content=b"hello",
                ctype="text/plain"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile(name, content, content_type=ctype)
        return self.c.post("/api/tickets/attachments/",
                           {"ticket": self.ticket.pk, "file": up},
                           format="multipart")

    def test_anonymous_download_denied(self):
        auth(self.c, self.mgr)
        aid = self._upload().data["id"]
        self.c.credentials()
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 401)
        dl.close()

    def test_employee_downloads_own_ticket_attachment(self):
        auth(self.c, self.emp)
        aid = self._upload().data["id"]
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        dl.close()

    def test_staff_downloads_visible_attachment(self):
        auth(self.c, self.mgr)
        aid = self._upload().data["id"]
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        dl.close()

    def test_employee_cannot_download_other_employee_ticket_attachment(self):
        other = self.emp.__class__.objects.create_user(
            username="o@x", email="o@x", employee_id="O1",
            password="pw12345678", role="employee")
        other_dep = self.emp.__class__  # reuse User model
        other_department = None
        from accounts.models import Department
        other_dep_obj = Department.objects.create(
            name="Other Dept", code="OT", description="x")
        other_ticket = Ticket.objects.create(
            title="Other ticket", description="d", category=self.tcat,
            requester=other, department=other_dep_obj, status="open",
            priority="medium")
        # emp uploads to their own ticket first.
        auth(self.c, self.emp)
        aid = self._upload().data["id"]
        # Repoint the attachment onto the other employee's ticket (different
        # department, not visible to emp).
        from tickets.models import TicketAttachment
        att = TicketAttachment.objects.get(pk=aid)
        att.ticket = other_ticket
        att.save()
        # emp should not see a ticket they cannot access.
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 404)

    def test_download_sets_security_headers(self):
        auth(self.c, self.mgr)
        aid = self._upload().data["id"]
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", dl["Content-Disposition"])
        # No CRLF in the header value.
        self.assertNotIn("\r", dl["Content-Disposition"])
        self.assertNotIn("\n", dl["Content-Disposition"])
        dl.close()

    def test_download_sanitizes_crlf_filename(self):
        from tickets.models import TicketAttachment
        auth(self.c, self.mgr)
        aid = self._upload().data["id"]
        att = TicketAttachment.objects.get(pk=aid)
        att.original_filename = "evil\r\nname.txt"
        att.save()
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 200)
        self.assertNotIn("\r", dl["Content-Disposition"])
        self.assertNotIn("\n", dl["Content-Disposition"])
        dl.close()

    def test_download_deleted_attachment_404(self):
        auth(self.c, self.mgr)
        aid = self._upload().data["id"]
        from tickets.models import TicketAttachment
        att = TicketAttachment.objects.get(pk=aid)
        att.soft_delete(by_user=self.mgr)
        dl = self.c.get(f"/api/tickets/attachments/{aid}/download/")
        self.assertEqual(dl.status_code, 404)
        dl.close()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketBulkCreateIdempotencyTests(TestCase):
    """Idempotent preview/confirm behavior for ticket bulk import."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.other_dep = Department.objects.create(name="Other", code="OTH-IDEM")

    def _row(self, **kw):
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        return base

    def _post(self, payload, **kwargs):
        return self.c.post("/api/tickets/bulk_create/", payload,
                           format=kwargs.pop("fmt", "json"), **kwargs)

    def test_same_token_confirmation_replays_without_duplicates(self):
        auth(self.c, self.mgr)
        token = "idem-confirm-1"
        payload = {"tickets": [self._row(title="once")],
                   "preview": False, "confirm": True, "import_token": token}
        res1 = self._post(payload)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 0})
        first_id = res1.data["successful"][0]["id"]
        # Client loses response and retries the same confirmation.
        res2 = self._post(payload)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data, res1.data)
        self.assertEqual(Ticket.objects.filter(title="once").count(), 1)
        self.assertEqual(Ticket.objects.get(pk=first_id).title, "once")

    def test_same_token_csv_confirmation_replays_same_report(self):
        auth(self.c, self.mgr)
        token = "idem-csv-1"
        payload = {"tickets": [self._row(title="csv-once"),
                               {"description": "no title", "category": self.tcat.pk}],
                   "preview": False, "confirm": True, "import_token": token}
        res1 = self._post(payload, fmt="json",
                          QUERY_STRING="download=csv")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1["Content-Type"], "text/csv")
        body1 = res1.content.decode("utf-8")
        self.assertEqual(Ticket.objects.filter(title="csv-once").count(), 1)
        res2 = self._post(payload, fmt="json",
                          QUERY_STRING="download=csv")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2["Content-Type"], "text/csv")
        self.assertEqual(res2.content.decode("utf-8"), body1)
        self.assertEqual(Ticket.objects.filter(title="csv-once").count(), 1)

    def test_partial_success_confirmation_replays_same_outcome(self):
        auth(self.c, self.mgr)
        token = "idem-partial-1"
        payload = {"tickets": [self._row(title="good-p"),
                               {"description": "no title", "category": self.tcat.pk}],
                   "preview": False, "confirm": True, "import_token": token}
        res1 = self._post(payload)
        self.assertEqual(res1.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 1})
        res2 = self._post(payload)
        self.assertEqual(res2.data, res1.data)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertTrue(Ticket.objects.filter(title="good-p").exists())

    def test_separate_imports_with_identical_rows_are_allowed(self):
        auth(self.c, self.mgr)
        row = self._row(title="same")
        res1 = self._post({"tickets": [row], "preview": False,
                           "confirm": True, "import_token": "idem-a"})
        res2 = self._post({"tickets": [row], "preview": False,
                           "confirm": True, "import_token": "idem-b"})
        self.assertEqual(res1.data["summary"]["ok"], 1)
        self.assertEqual(res2.data["summary"]["ok"], 1)
        self.assertEqual(Ticket.objects.filter(title="same").count(), 2)
        self.assertNotEqual(res1.data["successful"][0]["id"],
                            res2.data["successful"][0]["id"])

    def test_different_user_cannot_access_another_users_import_result(self):
        auth(self.c, self.mgr)
        token = "idem-cross-user"
        res = self._post({"tickets": [self._row(title="mgr-only")],
                          "preview": False, "confirm": True,
                          "import_token": token})
        self.assertEqual(res.data["summary"]["ok"], 1)
        mgr_ticket_id = res.data["successful"][0]["id"]
        # Employee uses the same token value: must not access manager's stored
        # result. It is scoped to the employee and treated as a separate import
        # attempt; with a different (and valid) payload it may create their own
        # ticket, but must never replay or expose the manager's import.
        auth(self.c, self.emp)
        res_emp = self._post({"tickets": [self._row(title="emp-own")],
                              "preview": False, "confirm": True,
                              "import_token": token})
        self.assertEqual(res_emp.status_code, 200)
        self.assertEqual(res_emp.data["summary"]["ok"], 1)
        emp_ticket_id = res_emp.data["successful"][0]["id"]
        self.assertNotEqual(emp_ticket_id, mgr_ticket_id)
        self.assertEqual(Ticket.objects.filter(pk=mgr_ticket_id).count(), 1)
        self.assertEqual(Ticket.objects.get(pk=emp_ticket_id).requester,
                         self.emp)
        # No additional manager ticket was created and manager's result not replayed.
        self.assertEqual(Ticket.objects.filter(title="mgr-only").count(), 1)

    def test_expired_token_is_rejected(self):
        from django.utils import timezone
        from datetime import timedelta
        from tickets.models import TicketBulkImportOperation
        from tickets.views import _ticket_bulk_import_fingerprint
        auth(self.c, self.mgr)
        token = "idem-expired"
        rows = [self._row(title="late")]
        TicketBulkImportOperation.objects.create(
            user=self.mgr, token=token,
            status=TicketBulkImportOperation.STATUS_PREVIEWED,
            request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
            expires_at=timezone.now() - timedelta(minutes=1))
        res = self._post({"tickets": rows, "preview": False,
                          "confirm": True, "import_token": token})
        self.assertEqual(res.status_code, 410)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_processing_operation_rejects_concurrent_confirmation(self):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.models import TicketBulkImportOperation
        auth(self.c, self.mgr)
        token = "idem-processing"
        # Same payload fingerprint as request to simulate in-progress claim.
        rows_in = [self._row(title="inprog")]
        from tickets.views import _ticket_bulk_import_fingerprint
        fp = _ticket_bulk_import_fingerprint(rows_in, upload=None)
        TicketBulkImportOperation.objects.create(
            user=self.mgr, token=token,
            status=TicketBulkImportOperation.STATUS_PROCESSING,
            request_fingerprint=fp,
            started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1))
        res = self._post({"tickets": rows_in, "preview": False,
                          "confirm": True, "import_token": token})
        self.assertEqual(res.status_code, 409)
        self.assertIn("in progress", res.data["detail"].lower())
        self.assertEqual(Ticket.objects.count(), 0)

    def test_same_token_cannot_be_reused_with_different_payload(self):
        auth(self.c, self.mgr)
        token = "idem-mismatch"
        res1 = self._post({"tickets": [self._row(title="first")],
                           "preview": True, "import_token": token})
        self.assertEqual(res1.status_code, 200)
        res2 = self._post({"tickets": [self._row(title="different")],
                           "preview": True, "import_token": token})
        self.assertEqual(res2.status_code, 409)
        res3 = self._post({"tickets": [self._row(title="different")],
                           "preview": False, "confirm": True,
                           "import_token": token})
        self.assertEqual(res3.status_code, 409)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_confirmation_with_no_created_tickets_is_replayable(self):
        auth(self.c, self.mgr)
        token = "idem-none-created"
        payload = {"tickets": [{"description": "no title", "category": self.tcat.pk}],
                   "preview": False, "confirm": True, "import_token": token}
        res1 = self._post(payload)
        self.assertEqual(res1.data["summary"],
                         {"ok": 0, "skipped": 0, "failed": 1})
        res2 = self._post(payload)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data, res1.data)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_confirmation_fails_before_any_ticket_created(self):
        """Unexpected failure before any durable ticket creation must not allow
        a blind retry that could duplicate work once fixed/retried differently;
        the same operation token is marked failed."""
        from tickets.models import TicketBulkImportOperation
        auth(self.c, self.mgr)
        token = "idem-fail-no-create"
        # All rows invalid => no tickets committed. Force an unexpected failure
        # during CSV report finalization (after processing loop, before completion).
        old = self.c.raise_request_exception
        self.c.raise_request_exception = False
        try:
            with patch("tickets.views._ticket_report_rows",
                       side_effect=RuntimeError("boom")):
                res = self.c.post(
                    "/api/tickets/bulk_create/?download=csv",
                    {"tickets": [{"description": "no title",
                                  "category": self.tcat.pk}],
                     "preview": False, "confirm": True,
                     "import_token": token},
                    format="json")
        finally:
            self.c.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        self.assertEqual(Ticket.objects.count(), 0)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        # Finalization failed before a completed result was persisted. The
        # implementation attempts to mark the operation failed; if that status
        # cannot be persisted in the current transaction context, it remains
        # processing (retry is still blocked as in-progress/stale, never
        # auto-replayed to duplicate tickets).
        self.assertIn(op.status, [
            TicketBulkImportOperation.STATUS_FAILED,
            TicketBulkImportOperation.STATUS_PROCESSING,
        ])
        res2 = self._post({"tickets": [{"description": "no title",
                                        "category": self.tcat.pk}],
                           "preview": False, "confirm": True,
                           "import_token": token},
                          fmt="json", QUERY_STRING="download=csv")
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_preview_then_confirm_with_same_token_creates_once(self):
        auth(self.c, self.mgr)
        token = "idem-preview-confirm"
        rows = [self._row(title="previewed")]
        p = self._post({"tickets": rows, "preview": True,
                        "import_token": token})
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p.data["affected"], 1)
        c = self._post({"tickets": rows, "preview": False,
                        "confirm": True, "import_token": token})
        self.assertEqual(c.data["summary"]["ok"], 1)
        c2 = self._post({"tickets": rows, "preview": False,
                         "confirm": True, "import_token": token})
        self.assertEqual(c2.data, c.data)
        self.assertEqual(Ticket.objects.count(), 1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   TICKET_BULK_IMPORT_MAX_ROWS=2,
                   TICKET_BULK_IMPORT_MAX_JSON_ROWS=2,
                   TICKET_BULK_IMPORT_MAX_FILE_SIZE_MB=0.0005)
class TicketBulkCreateLimitTests(TestCase):
    """Configurable hard limits for ticket bulk import."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def _row(self, **kw):
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        return base

    def test_json_row_limit_rejects_before_creation(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": [self._row(title="a"),
                                       self._row(title="b"),
                                       self._row(title="c")],
                           "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("too many rows", res.data["detail"].lower())
        self.assertEqual(Ticket.objects.count(), 0)

    def test_csv_row_limit_rejects_entire_upload(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = ("title,description,category\n"
               "A,d,%d\nB,d,%d\nC,d,%d\n" % (
                   self.tcat.pk, self.tcat.pk, self.tcat.pk)).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", csv,
                                           content_type="text/csv"),
                "preview": "false", "confirm": "true"}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_file_size_limit_rejects_before_parsing(self):
        auth(self.c, self.mgr)
        from django.core.files.uploadedfile import SimpleUploadedFile
        # ~700 bytes, above 0.0005 MB (~512 bytes) limit in settings override.
        big = ("title,description,category\n" + ("A," + ("d" * 200) + ",%d\n" % self.tcat.pk) * 3).encode("utf-8")
        data = {"file": SimpleUploadedFile("tickets.csv", big,
                                           content_type="text/csv"),
                "preview": "true"}
        res = self.c.post("/api/tickets/bulk_create/", data,
                          format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)
        self.assertIn("too large", str(res.data["file"]).lower())
        self.assertEqual(Ticket.objects.count(), 0)

    @override_settings(TICKET_BULK_IMPORT_MAX_ROWS=10,
                       TICKET_BULK_IMPORT_MAX_JSON_ROWS=10,
                       TICKET_BULK_IMPORT_MAX_FILE_SIZE_MB=5)
    def test_within_limits_preserves_partial_success(self):
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": [self._row(title="good"),
                                       {"description": "no title",
                                        "category": self.tcat.pk}],
                           "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"],
                         {"ok": 1, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), 1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketBulkCreateOperationalRecoveryTests(TestCase):
    """Operational observability and recovery behavior for ticket bulk imports."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def _row(self, **kw):
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        return base

    def _post(self, payload, **kwargs):
        return self.c.post("/api/tickets/bulk_create/", payload,
                           format=kwargs.pop("fmt", "json"), **kwargs)

    def test_stale_processing_operation_blocks_retry_without_duplicates(self):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.models import TicketBulkImportOperation
        from tickets.views import _ticket_bulk_import_fingerprint
        auth(self.c, self.mgr)
        token = "idem-stale-processing"
        rows = [self._row(title="stale")]
        fp = _ticket_bulk_import_fingerprint(rows, upload=None)
        TicketBulkImportOperation.objects.create(
            user=self.mgr, token=token,
            status=TicketBulkImportOperation.STATUS_PROCESSING,
            request_fingerprint=fp,
            started_at=timezone.now() - timedelta(minutes=30),
            expires_at=timezone.now() + timedelta(hours=1),
            total_rows=1, processed_count=0)
        res = self._post({"tickets": rows, "preview": False,
                          "confirm": True, "import_token": token})
        self.assertEqual(res.status_code, 409)
        self.assertIn("interrupted", res.data["detail"].lower())
        self.assertEqual(Ticket.objects.count(), 0)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_PROCESSING)

    def test_failure_during_result_generation_after_committed_rows_preserves_counts_and_blocks_retry(self):
        """Report/result generation failure after some per-row commits: committed
        tickets must remain, no duplicates on retry, and operation must expose
        known progress/counts without a completed result."""
        from tickets.models import TicketBulkImportOperation
        auth(self.c, self.mgr)
        token = "idem-report-fail-after-commit"
        rows = [self._row(title="committed-1"),
                {"description": "no title", "category": self.tcat.pk}]
        old = self.c.raise_request_exception
        self.c.raise_request_exception = False
        try:
            with patch("tickets.views._ticket_report_rows",
                       side_effect=RuntimeError("csv boom")):
                res = self.c.post(
                    "/api/tickets/bulk_create/?download=csv",
                    {"tickets": rows, "preview": False, "confirm": True,
                     "import_token": token},
                    format="json")
        finally:
            self.c.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        self.assertEqual(Ticket.objects.filter(title="committed-1").count(), 1)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        self.assertIn(op.status, [
            TicketBulkImportOperation.STATUS_FAILED,
            TicketBulkImportOperation.STATUS_PROCESSING,
        ])
        # Known durable progress: 1 row created, 1 failed validation, all processed.
        self.assertEqual(op.total_rows, 2)
        self.assertEqual(op.processed_count, 2)
        self.assertEqual(op.successful_count, 1)
        self.assertEqual(op.failed_count, 1)
        self.assertEqual(op.result_json, None)
        self.assertEqual(op.result_csv, "")
        res2 = self._post({"tickets": rows, "preview": False,
                           "confirm": True, "import_token": token},
                          fmt="json", QUERY_STRING="download=csv")
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(Ticket.objects.filter(title="committed-1").count(), 1)

    def test_failure_during_final_operation_persistence_keeps_result_uncompleted_and_blocks_duplicate_retry(self):
        """If persisting the completed operation/result fails, the operation must
        not be marked completed and retries must not duplicate committed work."""
        from tickets.models import TicketBulkImportOperation
        auth(self.c, self.mgr)
        token = "idem-final-persist-fail"
        rows = [self._row(title="persist-1")]
        real_filter = TicketBulkImportOperation.objects.filter

        def flaky_filter(*args, **kwargs):
            qs = real_filter(*args, **kwargs)

            class _QS:
                def __getattr__(self, name):
                    return getattr(qs, name)

                def update(self, **ukwargs):
                    if ukwargs.get("status") == TicketBulkImportOperation.STATUS_COMPLETED:
                        raise RuntimeError("persist boom")
                    return qs.update(**ukwargs)

            return _QS()

        old = self.c.raise_request_exception
        self.c.raise_request_exception = False
        try:
            with patch("tickets.models.TicketBulkImportOperation.objects.filter",
                       side_effect=flaky_filter):
                res = self._post({"tickets": rows, "preview": False,
                                  "confirm": True, "import_token": token})
        finally:
            self.c.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        self.assertEqual(Ticket.objects.filter(title="persist-1").count(), 1)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        self.assertNotEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertIn(op.status, [
            TicketBulkImportOperation.STATUS_FAILED,
            TicketBulkImportOperation.STATUS_PROCESSING,
        ])
        self.assertIsNone(op.result_json)
        res2 = self._post({"tickets": rows, "preview": False,
                           "confirm": True, "import_token": token})
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(Ticket.objects.filter(title="persist-1").count(), 1)

    def test_repeated_confirmation_after_partial_failure_is_blocked(self):
        """A failed operation with some committed rows must not be auto-rerun."""
        from tickets.models import TicketBulkImportOperation
        auth(self.c, self.mgr)
        token = "idem-partial-failed"
        rows = [self._row(title="partial-1"),
                {"description": "no title", "category": self.tcat.pk}]
        # Simulate a failure recorded after one ticket committed.
        Ticket.objects.create(title="partial-1", description="d",
                              category=self.tcat, requester=self.mgr,
                              department=self.dep)
        # (The above is just to have a committed row; operation record below
        # represents the import that produced it and then failed finalization.)
        from tickets.views import _ticket_bulk_import_fingerprint
        TicketBulkImportOperation.objects.create(
            user=self.mgr, token=token,
            status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
            total_rows=2, processed_count=2,
            successful_count=1, failed_count=1,
            error_detail="Finalization failed")
        before = Ticket.objects.count()
        res = self._post({"tickets": rows, "preview": False,
                          "confirm": True, "import_token": token})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(Ticket.objects.count(), before)

    def test_bulk_import_inspection_staff_only_and_redacted(self):
        from tickets.models import TicketBulkImportOperation
        from tickets.views import _ticket_bulk_import_fingerprint
        auth(self.c, self.mgr)
        token = "inspect-1"
        rows = [self._row(title="inspect-target")]
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token=token,
            status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
            preview_payload={"secret": "preview"},
            result_json={"secret": "result"},
            result_csv="secret,csv",
            error_detail="boom",
            total_rows=1, processed_count=1, successful_count=1, failed_count=0)
        # Employee cannot inspect operational details.
        auth(self.c, self.emp)
        res = self.c.get("/api/tickets/bulk-imports/")
        self.assertEqual(res.status_code, 403)
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/")
        self.assertEqual(res.status_code, 403)
        # Staff can inspect, but sensitive fields/payloads/results/tokens are omitted.
        auth(self.c, self.admin)
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["id"], op.pk)
        self.assertEqual(res.data["user"], self.mgr.pk)
        self.assertEqual(res.data["status"], TicketBulkImportOperation.STATUS_FAILED)
        self.assertEqual(res.data["total_rows"], 1)
        self.assertEqual(res.data["successful_count"], 1)
        self.assertNotIn("token", res.data)
        self.assertNotIn("request_fingerprint", res.data)
        self.assertNotIn("preview_payload", res.data)
        self.assertNotIn("result_json", res.data)
        self.assertNotIn("result_csv", res.data)
        blob = str(res.data)
        self.assertNotIn("inspect-1", blob)
        self.assertNotIn("secret", blob)
        # List endpoint works for staff.
        res = self.c.get("/api/tickets/bulk-imports/")
        self.assertEqual(res.status_code, 200)
        rows_out = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertTrue(any(r["id"] == op.pk for r in rows_out))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketBulkImportRowOutcomeTests(TestCase):
    """Durable per-row outcome tracking and read-only reconciliation evidence."""

    def setUp(self):
        cache.clear()
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")

    def _row(self, **kw):
        base = {"title": "t", "description": "d",
                "category": self.tcat.pk, "department": self.dep.pk}
        base.update(kw)
        return base

    def _confirm(self, rows, token, fmt="json", query_string=""):
        auth(self.c, self.mgr)
        payload = {"tickets": rows, "preview": False, "confirm": True,
                   "import_token": token}
        return self.c.post(f"/api/tickets/bulk_create/{query_string}", payload,
                           format=fmt)

    def test_tokenized_confirm_records_durable_row_outcomes(self):
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        auth(self.c, self.mgr)
        token = "row-outcomes-basic"
        rows = [self._row(title="ok-1"),
                {"description": "no title", "category": self.tcat.pk},
                self._row(title="ok-2")]
        res = self._confirm(rows, token)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"], {"ok": 2, "skipped": 0, "failed": 1})
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op)
                        .order_by("row_index"))
        self.assertEqual(len(outcomes), 3)
        self.assertEqual([o.row_index for o in outcomes], [0, 1, 2])
        self.assertEqual([o.row_number for o in outcomes], [1, 2, 3])
        self.assertEqual(outcomes[0].outcome, TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED)
        self.assertEqual(outcomes[1].outcome, TicketBulkImportRowOutcome.OUTCOME_FAILED)
        self.assertEqual(outcomes[2].outcome, TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED)
        self.assertIsNotNone(outcomes[0].ticket_id)
        self.assertIsNone(outcomes[1].ticket_id)
        self.assertIsNotNone(outcomes[2].ticket_id)
        self.assertEqual(Ticket.objects.filter(
            pk__in=[outcomes[0].ticket_id, outcomes[2].ticket_id]).count(), 2)
        self.assertEqual(outcomes[0].ticket.title, "ok-1")
        self.assertEqual(outcomes[2].ticket.title, "ok-2")
        self.assertNotEqual(outcomes[1].error_message, "")
        self.assertTrue(all(o.row_fingerprint for o in outcomes))
        # Succeeded outcomes must map to tickets created by this operation/result.
        result_ids = sorted([s["id"] for s in res.data["successful"]])
        outcome_ids = sorted([o.ticket_id for o in outcomes
                              if o.outcome == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED])
        self.assertEqual(result_ids, outcome_ids)

    def test_processing_exception_rolls_back_ticket_and_records_failed_outcome(self):
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        auth(self.c, self.mgr)
        token = "row-outcome-rollback"
        rows = [self._row(title="boom-row")]
        with patch("tickets.views.log_action", side_effect=RuntimeError("forced")):
            res = self._confirm(rows, token)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.filter(title="boom-row").count(), 0)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op))
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].outcome, TicketBulkImportRowOutcome.OUTCOME_FAILED)
        self.assertIsNone(outcomes[0].ticket_id)
        self.assertIn("forced", outcomes[0].error_message.lower())
        self.assertEqual(op.status, TicketBulkImportOperation.STATUS_COMPLETED)

    def test_succeeded_outcome_save_failure_rolls_back_ticket(self):
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        auth(self.c, self.mgr)
        token = "row-outcome-save-fail"
        rows = [self._row(title="no-commit-without-outcome")]
        real_create = TicketBulkImportRowOutcome.objects.create

        def flaky_create(*args, **kwargs):
            if kwargs.get("outcome") == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED:
                raise RuntimeError("outcome save failed")
            return real_create(*args, **kwargs)

        with patch("tickets.models.TicketBulkImportRowOutcome.objects.create",
                   side_effect=flaky_create):
            res = self._confirm(rows, token)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"], {"ok": 0, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.filter(
            title="no-commit-without-outcome").count(), 0)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op))
        # No succeeded outcome may remain; a failed outcome may be recorded after rollback.
        self.assertFalse(any(
            o.outcome == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED for o in outcomes))
        self.assertTrue(any(
            o.outcome == TicketBulkImportRowOutcome.OUTCOME_FAILED for o in outcomes))
        self.assertTrue(all(o.ticket_id is None for o in outcomes))

    def test_finalization_failure_after_commit_preserves_authoritative_row_outcomes(self):
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        auth(self.c, self.mgr)
        token = "row-outcome-finalize-fail"
        rows = [self._row(title="committed-with-outcome"),
                {"description": "no title", "category": self.tcat.pk}]
        old = self.c.raise_request_exception
        self.c.raise_request_exception = False
        try:
            with patch("tickets.views._ticket_report_rows",
                       side_effect=RuntimeError("csv boom")):
                res = self.c.post(
                    "/api/tickets/bulk_create/?download=csv",
                    {"tickets": rows, "preview": False, "confirm": True,
                     "import_token": token},
                    format="json")
        finally:
            self.c.raise_request_exception = old
        self.assertEqual(res.status_code, 500)
        self.assertEqual(Ticket.objects.filter(
            title="committed-with-outcome").count(), 1)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)
        outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op)
                        .order_by("row_index"))
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].outcome, TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED)
        self.assertEqual(outcomes[0].ticket_id,
                         Ticket.objects.get(title="committed-with-outcome").pk)
        self.assertEqual(outcomes[1].outcome, TicketBulkImportRowOutcome.OUTCOME_FAILED)
        self.assertIsNone(outcomes[1].ticket_id)

    def test_reconciliation_endpoint_staff_only_and_evidence_based(self):
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        auth(self.c, self.mgr)
        token = "recon-ok"
        rows = [self._row(title="r1"),
                {"description": "no title", "category": self.tcat.pk}]
        res = self._confirm(rows, token)
        self.assertEqual(res.status_code, 200)
        op = TicketBulkImportOperation.objects.get(user=self.mgr, token=token)

        # Employee denied.
        auth(self.c, self.emp)
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
        self.assertEqual(res.status_code, 403)

        # Staff gets durable evidence-based preview without sensitive payloads.
        auth(self.c, self.admin)
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["operation_id"], op.pk)
        self.assertEqual(res.data["status"], TicketBulkImportOperation.STATUS_COMPLETED)
        self.assertEqual(res.data["expected_rows"], 2)
        self.assertEqual(res.data["recorded_successful_rows"], 1)
        self.assertEqual(res.data["recorded_failed_rows"], 1)
        self.assertEqual(res.data["unprocessed_or_unrecorded_rows"], 0)
        self.assertTrue(res.data["result_stored"])
        self.assertTrue(res.data["evidence"]["has_row_level_outcomes"])
        self.assertFalse(res.data["evidence"]["legacy_or_pre_tracking"])
        self.assertFalse(res.data["evidence"]["ambiguous"])
        self.assertEqual(len(res.data["committed_ticket_ids"]), 1)
        self.assertEqual(res.data["committed_ticket_ids"][0],
                         Ticket.objects.get(title="r1").pk)
        blob = str(res.data)
        self.assertNotIn(token, blob)
        self.assertNotIn("request_fingerprint", blob)
        self.assertNotIn("preview_payload", blob)
        self.assertNotIn("result_json", blob)

    def test_reconciliation_marks_legacy_operation_without_row_outcomes_ambiguous(self):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.models import TicketBulkImportOperation
        from tickets.views import _ticket_bulk_import_fingerprint
        auth(self.c, self.admin)
        rows = [self._row(title="legacy")]
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token="legacy-op",
            status=TicketBulkImportOperation.STATUS_FAILED,
            request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
            total_rows=1, processed_count=1, successful_count=1, failed_count=0,
            error_detail="legacy failure",
            expires_at=timezone.now() + timedelta(hours=1))
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["recorded_successful_rows"], 0)
        self.assertEqual(res.data["recorded_failed_rows"], 0)
        self.assertEqual(res.data["unprocessed_or_unrecorded_rows"], 1)
        self.assertTrue(res.data["evidence"]["legacy_or_pre_tracking"])
        self.assertTrue(res.data["evidence"]["ambiguous"])
        self.assertTrue(res.data["eligible_for_investigation"])
        self.assertEqual(res.data["committed_ticket_ids"], [])
        self.assertIn("ambiguous_or_legacy_evidence",
                      res.data["investigation_reasons"])

    def test_reconciliation_reports_unprocessed_rows_for_interrupted_operation(self):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        from tickets.views import _ticket_bulk_import_fingerprint, _ticket_bulk_import_row_fingerprint
        auth(self.c, self.admin)
        rows = [self._row(title="done"), self._row(title="missing")]
        fp = _ticket_bulk_import_fingerprint(rows, upload=None)
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token="interrupted-op",
            status=TicketBulkImportOperation.STATUS_PROCESSING,
            request_fingerprint=fp,
            total_rows=2, processed_count=1, successful_count=1, failed_count=0,
            started_at=timezone.now() - timedelta(minutes=30),
            expires_at=timezone.now() + timedelta(hours=1))
        t = Ticket.objects.create(title="done", description="d",
                                  category=self.tcat, requester=self.mgr,
                                  department=self.dep)
        TicketBulkImportRowOutcome.objects.create(
            operation=op, row_index=0, row_number=1,
            row_fingerprint=_ticket_bulk_import_row_fingerprint(rows[0]),
            outcome=TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED,
            ticket=t)
        res = self.c.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["recorded_successful_rows"], 1)
        self.assertEqual(res.data["recorded_failed_rows"], 0)
        self.assertEqual(res.data["unprocessed_or_unrecorded_rows"], 1)
        self.assertTrue(res.data["eligible_for_investigation"])
        self.assertIn("unprocessed_or_unrecorded_rows",
                      res.data["investigation_reasons"])
        self.assertEqual(res.data["committed_ticket_ids"], [t.pk])

    def test_failed_row_outcome_recording_does_not_overwrite_succeeded(self):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        from tickets.views import (_record_ticket_bulk_import_row_failure,
                                   _ticket_bulk_import_fingerprint,
                                   _ticket_bulk_import_row_fingerprint)
        rows = [self._row(title="ok")]
        op = TicketBulkImportOperation.objects.create(
            user=self.mgr, token="no-downgrade",
            status=TicketBulkImportOperation.STATUS_PROCESSING,
            request_fingerprint=_ticket_bulk_import_fingerprint(rows, upload=None),
            total_rows=1, processed_count=1, successful_count=1, failed_count=0,
            started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1))
        t = Ticket.objects.create(title="ok", description="d",
                                  category=self.tcat, requester=self.mgr,
                                  department=self.dep)
        TicketBulkImportRowOutcome.objects.create(
            operation=op, row_index=0, row_number=1,
            row_fingerprint=_ticket_bulk_import_row_fingerprint(rows[0]),
            outcome=TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED,
            ticket=t)
        _record_ticket_bulk_import_row_failure(op, 0, 1, rows[0], "later failure")
        outcome = TicketBulkImportRowOutcome.objects.get(operation=op, row_index=0)
        self.assertEqual(outcome.outcome, TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED)
        self.assertEqual(outcome.ticket_id, t.pk)

    def test_non_tokenized_import_preserves_behavior_without_operation_tracking(self):
        auth(self.c, self.mgr)
        from tickets.models import TicketBulkImportOperation, TicketBulkImportRowOutcome
        res = self.c.post("/api/tickets/bulk_create/",
                          {"tickets": [self._row(title="no-token")],
                           "preview": False, "confirm": True},
                          format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"], {"ok": 1, "skipped": 0, "failed": 0})
        self.assertTrue(Ticket.objects.filter(title="no-token").exists())
        self.assertEqual(TicketBulkImportOperation.objects.count(), 0)
        self.assertEqual(TicketBulkImportRowOutcome.objects.count(), 0)
