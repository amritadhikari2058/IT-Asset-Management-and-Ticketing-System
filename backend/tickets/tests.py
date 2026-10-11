"""Ticket bulk/history/report/permission tests.

Asset bulk-safety tests live in assets/tests.py (AssetBulkSafetyTests);
cross-cutting history tests below still touch assets where the flow is
ticket-driven, so Asset imports are kept intentionally."""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Department, User
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory
from common.models import Notification
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
        t = self._owned()
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
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
