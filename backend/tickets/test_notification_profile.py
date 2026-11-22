#!/usr/bin/env python
"""Profile notification and outbox queries during ticket confirmation."""
import time
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.tests import make_users
from tickets.models import Ticket, TicketCategory
from tickets.views import TICKET_ASSIGNMENT_CATEGORY


class NotificationProfileTests(TestCase):
    """Profile notification/outbox query patterns during confirmation."""

    def setUp(self):
        self.department, self.admin, self.manager, self.employee = make_users()
        self.category = TicketCategory.objects.create(name="Hardware")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _make_rows(self, count):
        return [
            {
                "title": f"Profile Ticket {i}",
                "description": "Profile test ticket",
                "category": self.category.pk,
                "department": self.department.pk,
                "assignee": self.employee.pk,
            }
            for i in range(count)
        ]

    def _categorize_query(self, sql):
        """Classify a query into notification-related categories."""
        sql_lower = sql.lower()
        # Transaction/savepoint operations
        if sql_lower.startswith("savepoint") or sql_lower.startswith("release savepoint"):
            return "savepoint"
        # Notification-related tables
        if "common_notificationoutboxevent" in sql_lower:
            return "outbox_event"
        if "common_notification" in sql_lower:
            return "in_app_notification"
        if "common_usernotificationpreference" in sql_lower:
            return "preference"
        if "workflow_automationrule" in sql_lower:
            return "automation_rule"
        if "common_emailoutboxevent" in sql_lower:
            return "legacy_email_event"
        return "other"

    def test_notification_query_profile_500_rows(self):
        """Profile notification/outbox queries with 500 confirmation rows."""
        rows = self._make_rows(500)

        with CaptureQueriesContext(connection) as queries:
            started = time.perf_counter()
            response = self.client.post(
                "/api/tickets/bulk_create/",
                {"tickets": rows, "preview": False, "confirm": True},
                format="json",
            )
            elapsed = time.perf_counter() - started

        self.assertEqual(response.status_code, 200)
        data = response.data
        summary = data.get("summary", {})

        # Categorize all queries
        categories = {}
        notification_categories = {
            "savepoint": 0,
            "outbox_event": 0,
            "in_app_notification": 0,
            "preference": 0,
            "automation_rule": 0,
            "legacy_email_event": 0,
        }
        table_counts = {}

        for q in queries:
            cat = self._categorize_query(q["sql"])
            categories[cat] = categories.get(cat, 0) + 1
            if cat in notification_categories:
                notification_categories[cat] += 1

            sql_lower = q["sql"].lower()
            # Count table references
            for table in [
                "tickets_ticket", "tickets_tickethistory", "common_auditlog",
                "common_notificationoutboxevent", "common_notification",
                "common_usernotificationpreference", "workflow_automationrule",
                "tickets_ticketcategory", "accounts_department",
                "accounts_user", "assets_asset", "common_emailoutboxevent",
                "tickets_ticketbulkimportrowoutcome",
                "tickets_ticketbulkimportoperation",
            ]:
                if table in sql_lower:
                    table_counts[table] = table_counts.get(table, 0) + 1

        print("\n" + "=" * 70)
        print("NOTIFICATION/OUTBOX QUERY PROFILE (500 rows)")
        print("=" * 70)
        print(f"Total queries: {len(queries)}")
        print(f"Elapsed time: {elapsed:.2f}s")
        print(f"Result: ok={summary.get('ok', 'N/A')}, "
              f"failed={summary.get('failed', 'N/A')}, "
              f"skipped={summary.get('skipped', 'N/A')}")
        print(f"Queries per row: {len(queries) / 500:.2f}")

        print(f"\nQuery categories:")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")

        print(f"\nNotification-specific categories:")
        total_notif = sum(notification_categories.values())
        for cat, count in sorted(notification_categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} ({count / 500:.2f}/row)")
        print(f"  Total notification-related: {total_notif} ({total_notif / 500:.2f}/row)")

        print(f"\nTop tables referenced:")
        for table, count in sorted(table_counts.items(), key=lambda x: -x[1]):
            print(f"  {table}: {count} ({count / 500:.2f}/row)")

        # Count INSERT/SELECT/UPDATE/DELETE
        sql_types = {"SELECT": 0, "INSERT": 0, "UPDATE": 0, "DELETE": 0, "OTHER": 0}
        for q in queries:
            s = q["sql"].strip().upper()
            if s.startswith("SELECT"):
                sql_types["SELECT"] += 1
            elif s.startswith("INSERT"):
                sql_types["INSERT"] += 1
            elif s.startswith("UPDATE"):
                sql_types["UPDATE"] += 1
            elif s.startswith("DELETE"):
                sql_types["DELETE"] += 1
            else:
                sql_types["OTHER"] += 1
        print(f"\nSQL types: {sql_types}")

        print("=" * 70 + "\n")

        # Assert correctness
        self.assertEqual(summary.get("ok", 0), 500)
        self.assertEqual(summary.get("failed", 0), 0)