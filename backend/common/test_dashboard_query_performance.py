from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.tests import make_users
from assets.models import Asset, AssetCategory, Disposal, Maintenance
from common.reports import dashboard_data
from tickets.models import Ticket, TicketCategory


class DashboardAggregationQueryTests(TestCase):
    def setUp(self):
        self.department, _, manager, employee = make_users()
        now = timezone.now()
        asset_category = AssetCategory.objects.create(name="Dashboard query")
        assets = [
            Asset.objects.create(
                asset_tag=f"DASH-{index}",
                name=f"Dashboard asset {index}",
                category=asset_category,
                department=self.department,
                status=status,
            )
            for index, status in enumerate(
                ("available", "in_repair", "retired"), start=1)
        ]

        ticket_category = TicketCategory.objects.create(
            name="Dashboard query")
        Ticket.objects.create(
            title="Overdue",
            description="Dashboard fixture",
            category=ticket_category,
            requester=employee,
            department=self.department,
            status="open",
            sla_due_at=now - timedelta(hours=2),
        )
        resolved = Ticket.objects.create(
            title="Resolved late",
            description="Dashboard fixture",
            category=ticket_category,
            requester=employee,
            department=self.department,
            status="resolved",
            sla_due_at=now - timedelta(hours=3),
            resolved_at=now - timedelta(hours=1),
        )
        Ticket.objects.filter(pk=resolved.pk).update(
            created_at=now - timedelta(hours=5))
        Ticket.objects.create(
            title="Paused",
            description="Dashboard fixture",
            category=ticket_category,
            requester=employee,
            department=self.department,
            status="waiting_requester",
            sla_due_at=now - timedelta(hours=4),
        )

        Maintenance.objects.create(
            asset=assets[0], title="Upcoming", scheduled_date=now + timedelta(days=1))
        Maintenance.objects.create(
            asset=assets[1], title="Late", scheduled_date=now - timedelta(days=1))
        Disposal.objects.create(
            asset=assets[2], disposal_reason="Pending disposal")
        Disposal.objects.create(
            asset=assets[2],
            disposal_reason="Approved disposal",
            approval_status="approved",
            approver=manager,
        )

    def test_dashboard_aggregates_remain_accurate(self):
        # Summary-card counts are consolidated into bounded aggregate queries.
        with self.assertNumQueries(12):
            data = dashboard_data()

        self.assertEqual(data["employees"]["total"], 3)
        self.assertEqual(data["employees"]["active"], 3)
        self.assertEqual(data["employees"]["inactive"], 0)
        self.assertEqual(data["assets"]["total"], 3)
        self.assertEqual(data["assets"]["under_maintenance"], 1)
        self.assertEqual(data["assets"]["with_open_maintenance"], 2)
        self.assertEqual(data["tickets"]["total"], 3)
        self.assertEqual(data["tickets"]["open"], 1)
        self.assertEqual(data["tickets"]["overdue"], 1)
        self.assertEqual(data["tickets"]["sla"]["overdue"], 1)
        self.assertEqual(data["tickets"]["sla"]["breached"], 2)
        self.assertEqual(data["tickets"]["sla"]["compliance_pct"], 0.0)
        self.assertEqual(data["tickets"]["avg_resolution_hours"], 4.0)
        self.assertEqual(data["maintenance"]["open"], 2)
        self.assertEqual(data["maintenance"]["overdue"], 1)
        self.assertEqual(data["disposals"]["pending_approval"], 1)
        self.assertEqual(data["disposals"]["approved_not_completed"], 1)
