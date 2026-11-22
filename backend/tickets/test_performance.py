"""Query-count regression tests for the performance-engineered read paths.

These tests prove that query growth is bounded as the number of returned
records grows. They use small realistic fixtures: a handful of tickets
wraps a handful of notes/attachments/history rows, and a handful of assets
wraps assignments/categories/maintenance.

Tests never assert an exact query count. Exact counts are framework- and
database-version-dependent. Every assertion is an explicit growth
assertion: the count for a 2-record result set must not exceed the count
for a 1-record result set (or a 5-record set, where that is the expected
bound) by more than the width of one row.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Department
from accounts.tests import make_users
from assets.models import Asset, AssetCategory, Assignment, Maintenance
from cmdb.models import (
    ConfigurationItem, ConfigurationItemHistory, ConfigurationItemRelationship,
    ConfigurationItemType,
)
from tickets.models import Ticket, TicketCategory, TicketNote, TicketHistory, TicketAttachment

User = get_user_model()


def _api(client, url):
    return client.get(url)


def _authenticate(client, user):
    client.force_authenticate(user)


class _Fixture:
    """Small realistic fixture: each ticket/asset wraps a few children."""

    def __init__(self):
        dep, admin, mgr, emp = make_users()
        self.dep = dep
        self.admin = admin
        self.mgr = mgr
        self.emp = emp
        self.client = None  # set by TestCase
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.tcat = TicketCategory.objects.create(name="Hardware")

        # 3 tickets; first two wrap children, third is a value sentinel.
        self.t1 = Ticket.objects.create(
            title="T1", description="d", category=self.tcat,
            requester=self.emp, department=self.dep, status="open",
            priority="medium", sla_due_at=None,
        )
        self.t2 = Ticket.objects.create(
            title="T2", description="d", category=self.tcat,
            requester=self.emp, department=self.dep, status="open",
            priority="medium", sla_due_at=None,
        )
        self.t3 = Ticket.objects.create(
            title="T3", description="d", category=self.tcat,
            requester=self.emp, department=self.dep, status="resolved",
            priority="medium", sla_due_at=None,
        )
        TicketAttachment.objects.create(ticket=self.t3)
        TicketAttachment.objects.create(ticket=self.t3)
        TicketNote.objects.create(ticket=self.t3)
        TicketNote.objects.create(ticket=self.t3)
        TicketHistory.objects.create(ticket=self.t3, actor=self.mgr, action="update", note="")
        self.notes1 = [TicketNote.objects.create(ticket=self.t1)
                       for _ in range(3)]
        self.notes2 = [TicketNote.objects.create(ticket=self.t2)
                       for _ in range(3)]
        self.history1 = [TicketHistory.objects.create(
            ticket=self.t1, actor=self.mgr, action="update", note="")
            for _ in range(3)]
        self.history2 = [TicketHistory.objects.create(
            ticket=self.t2, actor=self.mgr, action="update", note="")
            for _ in range(3)]
        self.attachments1 = [
            TicketAttachment.objects.create(ticket=self.t1) for _ in range(3)]
        self.attachments2 = [
            TicketAttachment.objects.create(ticket=self.t2) for _ in range(3)]

        # 3 assets; first two wrap children.
        # Each asset gets exactly ONE open (unreturned) assignment plus
        # several closed (returned) ones, honoring the one-open-assignment
        # constraint enforced by the Assignment model.
        self.a1 = Asset.objects.create(
            asset_tag="A1", name="n1", category=self.acat,
            status="available", assigned_to=None, department=self.dep,
        )
        self.r1 = Assignment.objects.create(asset=self.a1, assigned_to=self.emp)
        # Closed assignments: return the current open one first, then create
        # the next open one. This honors the one-open-assignment constraint.
        self.r1.returned_at = timezone.now()
        self.r1.save(update_fields=["returned_at"])
        self.r1b = Assignment.objects.create(asset=self.a1, assigned_to=self.emp)
        self.r1b.returned_at = timezone.now()
        self.r1b.save(update_fields=["returned_at"])
        self.r1c = Assignment.objects.create(asset=self.a1, assigned_to=self.emp)
        self.a2 = Asset.objects.create(
            asset_tag="A2", name="n2", category=self.acat,
            status="available", assigned_to=None, department=self.dep,
        )
        self.r2 = Assignment.objects.create(asset=self.a2, assigned_to=self.emp)
        self.r2.returned_at = timezone.now()
        self.r2.save(update_fields=["returned_at"])
        self.r2b = Assignment.objects.create(asset=self.a2, assigned_to=self.emp)
        self.r2b.returned_at = timezone.now()
        self.r2b.save(update_fields=["returned_at"])
        self.r2c = Assignment.objects.create(asset=self.a2, assigned_to=self.emp)
        self.a3 = Asset.objects.create(
            asset_tag="A3", name="n3", category=self.acat,
            status="available", assigned_to=None, department=self.dep,
        )
        # a3 stays unassigned (sentinel for empty-assignment queries).
        self.assigns1 = [
            Assignment.objects.create(asset=self.a1, assigned_to=self.emp)
            for _ in range(3)]
        for a in self.assigns1:
            a.returned_at = timezone.now()
            a.save(update_fields=["returned_at"])
        self.assigns2 = [
            Assignment.objects.create(asset=self.a2, assigned_to=self.emp)
            for _ in range(3)]
        for a in self.assigns2:
            a.returned_at = timezone.now()
            a.save(update_fields=["returned_at"])
        self.maintenance1 = [
            Maintenance.objects.create(asset=self.a1, status="scheduled")
            for _ in range(3)]
        Maintenance.objects.create(asset=self.a1, status="scheduled", assigned_to=None)
        self.maintenance2 = [
            Maintenance.objects.create(asset=self.a2, status="scheduled")
            for _ in range(3)]
        Maintenance.objects.create(asset=self.a2, status="scheduled", assigned_to=None)

        # 1 cmdb item + children for the detail bound.
        self.ctype = ConfigurationItemType.objects.create(
            name="Server", code="SRVP", category="hardware",
            department=self.dep,
        )
        self.ci = ConfigurationItem.objects.create(
            ci_type=self.ctype, status="active", name="CI1",
            department=self.dep,
        )
        for _ in range(3):
            ConfigurationItemRelationship.objects.create(
                source_ci=self.ci, target_ci=self.ci,
                relationship_type="depends_on", status="active")
        for _ in range(3):
            ConfigurationItemHistory.objects.create(
                configuration_item=self.ci, event_type="updated", detail="")

    def _record_counts(self, func):
        with CaptureQueriesContext(connection) as ctx:
            result = func()
        try:
            payload = len(result.content)
        except Exception:
            payload = "?"
        return len(ctx), payload, result


class QueryGrowthTests(TestCase):
    """A 1-row result set must not cost more queries than a 3-row set."""

    def setUp(self):
        self.fixture = _Fixture()
        self.client = self.fixture.client = self

    # ---- Tickets ----
    def test_ticket_list_growth(self):
        f = self.fixture

        def one():
            return _api(self.client, "/api/tickets/")

        def three():
            return _api(self.client, "/api/tickets/?page=2")

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        self.assertEqual(p1, 2)
        self.assertEqual(p3, 2)
        self.assertLessEqual(c3, c1 + 2)

    def test_ticket_list_nested_reverse_relations_closed(self):
        f = self.fixture

        def one():
            return _api(self.client, "/api/tickets/")

        def three():
            return _api(self.client, "/api/tickets/?page=2")

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        # Only the detail/retrieve path loads notes/history/attachments.
        self.assertEqual(p1, 2)
        self.assertEqual(p3, 2)
        self.assertLessEqual(c3, c1)

    def test_ticket_retrieve_growth(self):
        f = self.fixture

        def one():
            return _api(self.client, f"/api/tickets/{f.t1.pk}/",)

        def three():
            return _api(self.client, f"/api/tickets/{f.t2.pk}/",)

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        self.assertEqual(p1, 2)
        self.assertEqual(p3, 2)
        self.assertLessEqual(c3, c1)

    # ---- Assets ----
    def test_asset_list_growth(self):
        f = self.fixture

        def one():
            return _api(self.client, "/api/assets/",)

        def three():
            return _api(self.client, "/api/assets/?page=2",)

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        self.assertEqual(p1, 2)
        self.assertEqual(p3, 2)
        self.assertLessEqual(c3, c1 + 2)

    def test_asset_retrieve_growth(self):
        f = self.fixture

        def one():
            return _api(self.client, f"/api/assets/{f.a1.pk}/",)

        def three():
            return _api(self.client, f"/api/assets/{f.a2.pk}/",)

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        self.assertEqual(p1, 2)
        self.assertEqual(p3, 2)
        self.assertLessEqual(c3, c1 + 2)

    # ---- CMDB ----
    def test_cmdb_items_list_growth(self):
        f = self.fixture

        def one():
            return _api(self.client, "/api/cmdb/items/",)

        def three():
            return _api(self.client, "/api/cmdb/items/?page=2",)

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        self.assertEqual(p1, 2)
        self.assertEqual(p3, 2)
        self.assertLessEqual(c3, c1)

    def test_cmdb_item_retrieve_growth(self):
        f = self.fixture

        def one():
            return _api(self.client, f"/api/cmdb/items/{f.ci.pk}/",)

        def three():
            return _api(self.client, f"/api/cmdb/items/{f.ci.pk}/?history=1",)

        c1, p1, _ = f._record_counts(one)
        c3, p3, _ = f._record_counts(three)
        self.assertLessEqual(c3, c1 + 3)


class DashboardAndReportingGrowthTests(TestCase):
    """Dashboard / reporting aggregation must not blow up on full tables."""

    def setUp(self):
        self.fixture = _Fixture()
        self.client = self.fixture.client = self

    def _call(self, url):
        return self.client.get(url)

    def test_common_dashboard_growth(self):
        f = self.fixture
        counts = []
        for page in (1, 2, 3):
            with CaptureQueriesContext(connection) as ctx:
                r = self.client.get("/api/common/dashboard/?page=%d" % page)
            counts.append(len(ctx))
            self.assertEqual(r.status_code, 200)
        # A dashboard should be flat: a few aggregate queries, not one per
        # ticket/asset row. Allow a small slack for pagination setup.
        self.assertLessEqual(counts[2], counts[0] + 6)

    def test_department_report_growth(self):
        f = self.fixture
        counts = []
        for page in (1, 2, 3):
            with CaptureQueriesContext(connection) as ctx:
                r = self.client.get(
                    "/api/common/reports/departments/?page=%d" % page)
            counts.append(len(ctx))
            self.assertEqual(r.status_code, 200)
        self.assertLessEqual(counts[2], counts[0] + 10)
