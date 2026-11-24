import json
import math
import os
import time
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from openpyxl import Workbook
from rest_framework.test import APIClient

from accounts.tests import make_users
from assets.models import Asset, AssetCategory
from tickets.models import Ticket, TicketCategory, TicketHistory
from tickets.serializers import TicketSerializer


class TicketBulkImportScalabilityTests(TestCase):
    def setUp(self):
        self.department, _, self.manager, self.employee = make_users()
        self.category = TicketCategory.objects.create(name="Hardware")
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def _row(self, index):
        return {
            "title": f"Ticket {index}",
            "description": "Import query regression",
            "category": self.category.pk,
            "department": self.department.pk,
            "assignee": self.employee.pk,
        }

    def _preview_import(self, row, token):
        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": [row], "import_token": token},
            format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["preview"][0]["valid"], response.data)

    def test_confirmation_rechecks_deactivated_category_after_preview(self):
        row = self._row("category-changed")
        self._preview_import(row, "category-changed")

        TicketCategory.objects.filter(pk=self.category.pk).update(
            is_active=False)
        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": [row], "import_token": "category-changed",
             "preview": False, "confirm": True},
            format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"]["failed"], 1)
        self.assertEqual(Ticket.objects.filter(
            title=row["title"]).count(), 0)

    def test_confirmation_rechecks_soft_deleted_department_after_preview(self):
        from accounts.models import Department

        row = self._row("department-deleted")
        self._preview_import(row, "department-deleted")
        Department.objects.filter(pk=self.department.pk).update(
            is_deleted=True)

        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": [row], "import_token": "department-deleted",
             "preview": False, "confirm": True},
            format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"]["failed"], 1)
        self.assertEqual(Ticket.objects.filter(
            title=row["title"]).count(), 0)

    def test_confirmation_rechecks_soft_deleted_asset_after_preview(self):
        asset_category = AssetCategory.objects.create(name="Import hardware")
        asset = Asset.objects.create(
            asset_tag="IMPORT-ASSET-1", name="Import asset",
            category=asset_category)
        row = self._row("asset-deleted")
        row["asset_tag"] = asset.asset_tag
        self._preview_import(row, "asset-deleted")
        Asset.objects.filter(pk=asset.pk).update(is_deleted=True)

        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": [row], "import_token": "asset-deleted",
             "preview": False, "confirm": True},
            format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"]["failed"], 1)
        self.assertEqual(Ticket.objects.filter(
            title=row["title"]).count(), 0)

    def test_confirmation_rechecks_inactive_assignee_after_preview(self):
        row = self._row("assignee-inactive")
        self._preview_import(row, "assignee-inactive")
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])

        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": [row], "import_token": "assignee-inactive",
             "preview": False, "confirm": True},
            format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"]["failed"], 1)
        self.assertEqual(Ticket.objects.filter(
            title=row["title"]).count(), 0)

    def test_integrity_error_rolls_back_only_the_failing_row(self):
        from tickets.views import _write_history

        rows = [self._row("integrity-first"),
                self._row("integrity-fails"),
                self._row("integrity-last")]

        def fail_one_history(ticket, *args, **kwargs):
            if ticket.title == "Ticket integrity-fails":
                raise IntegrityError("injected row integrity failure")
            return _write_history(ticket, *args, **kwargs)

        with patch("tickets.views._write_history", side_effect=fail_one_history):
            response = self.client.post(
                "/api/tickets/bulk_create/",
                {"tickets": rows, "preview": False, "confirm": True},
                format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"],
                         {"ok": 2, "skipped": 0, "failed": 1})
        self.assertEqual(
            list(Ticket.objects.order_by("title").values_list("title", flat=True)),
            ["Ticket integrity-first", "Ticket integrity-last"])
        self.assertFalse(TicketHistory.objects.filter(
            ticket__title="Ticket integrity-fails").exists())

    def test_preview_reference_query_count_does_not_scale_per_row(self):
        query_counts = {}
        for size in (5, 25, 100):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(
                    "/api/tickets/bulk_create/",
                    {"tickets": [self._row(i) for i in range(size)]},
                    format="json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data["preview"]), size)
            query_counts[size] = len(queries)

        self.assertLessEqual(query_counts[100], query_counts[5] + 1,
                             query_counts)

    def test_confirmation_caches_rule_and_preference_reads_per_request(self):
        class RequestQueryCounter:
            def __init__(self):
                self.rule_queries = 0
                self.preference_queries = 0

            def __call__(self, execute, sql, params, many, context):
                lowered = sql.lower()
                if (sql.lstrip().upper().startswith("SELECT")
                        and "workflow_automationrule" in lowered):
                    self.rule_queries += 1
                if ("common_usernotificationpreference" in lowered
                        and sql.lstrip().upper().startswith("SELECT")):
                    self.preference_queries += 1
                return execute(sql, params, many, context)

        counts = {}
        for size in (25, 100):
            rows = [self._row(i) for i in range(size)]
            counter = RequestQueryCounter()
            with connection.execute_wrapper(counter):
                response = self.client.post(
                    "/api/tickets/bulk_create/",
                    {"tickets": rows, "preview": False, "confirm": True},
                    format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["summary"]["ok"], size)
            counts[size] = {
                "rule": counter.rule_queries,
                "preference": counter.preference_queries,
            }

        self.assertLessEqual(counts[100]["rule"], 1)
        self.assertLessEqual(counts[100]["preference"], 2)

    def test_confirmation_batches_names_and_locks_each_referenced_row(self):
        metrics = []
        reference_tables = (
            "tickets_ticketcategory",
            "accounts_department",
            "accounts_user",
        )

        class ReferenceQueryCounter:
            def __init__(self):
                self.count = 0
                self.reference_count = 0
                self.by_table = {table: 0 for table in reference_tables}

            def __call__(self, execute, sql, params, many, context):
                self.count += 1
                if sql.lstrip().upper().startswith("SELECT"):
                    if any(table in sql.lower()
                           for table in reference_tables):
                        self.reference_count += 1
                    for table in reference_tables:
                        if table in sql.lower():
                            self.by_table[table] += 1
                return execute(sql, params, many, context)

        for size in (5, 25, 100, 500):
            rows = []
            for index in range(size):
                row = self._row(index)
                row["category"] = self.category.name
                row["department"] = self.department.code
                row.pop("assignee")
                row["assignee_employee_id"] = self.employee.employee_id
                rows.append(row)
            payload = {
                "tickets": rows,
                "preview": False,
                "confirm": True,
            }
            query_counter = ReferenceQueryCounter()
            with connection.execute_wrapper(query_counter):
                response = self.client.post(
                    "/api/tickets/bulk_create/", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["summary"]["ok"], size,
                             response.data)
            metrics.append({
                "rows": size,
                "queries": query_counter.count,
                "reference_queries": query_counter.reference_count,
                "reference_queries_by_table": query_counter.by_table,
            })
            expected = 3 * size + 3 * math.ceil(size / 250)
            self.assertEqual(query_counter.reference_count, expected,
                             metrics[-1])

        if os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1":
            print(json.dumps({
                "workflow": "ticket confirmation references",
                "measurements": metrics,
            }))

    def test_confirmation_cache_reduces_related_object_reads(self):
        benchmark = os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1"
        size = 500 if benchmark else 25
        reference_tables = (
            "tickets_ticketcategory",
            "accounts_department",
            "accounts_user",
        )

        class QueryCounter:
            def __init__(self):
                self.total = 0
                self.references = 0

            def __call__(self, execute, sql, params, many, context):
                self.total += 1
                if (sql.lstrip().upper().startswith("SELECT")
                        and any(table in sql.lower()
                                for table in reference_tables)):
                    self.references += 1
                return execute(sql, params, many, context)

        rows = [self._row(f"cached-{i}") for i in range(size)]
        payload = {"tickets": rows, "preview": False, "confirm": True}
        cached_counter = QueryCounter()
        started = time.perf_counter()
        with connection.execute_wrapper(cached_counter):
            cached_response = self.client.post(
                "/api/tickets/bulk_create/", payload, format="json")
        cached_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(cached_response.status_code, 200)

        baseline_rows = [
            self._row(f"baseline-{i}") for i in range(size)]
        connection.queries_log.clear()
        baseline_counter = QueryCounter()
        started = time.perf_counter()
        with patch("tickets.views.TicketBulkImportSerializer",
                   TicketSerializer):
            with connection.execute_wrapper(baseline_counter):
                baseline_response = self.client.post(
                    "/api/tickets/bulk_create/",
                    {"tickets": baseline_rows, "preview": False,
                     "confirm": True},
                    format="json")
        baseline_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(baseline_response.status_code, 200)

        self.assertLess(cached_counter.references, baseline_counter.references)
        if benchmark:
            print(json.dumps({
                "workflow": "ticket confirmation reference lookup comparison",
                "rows": size,
                "baseline_queries": baseline_counter.total,
                "optimized_queries": cached_counter.total,
                "baseline_reference_queries": baseline_counter.references,
                "optimized_reference_queries": cached_counter.references,
                "baseline_ms": round(baseline_ms, 2),
                "optimized_ms": round(cached_ms, 2),
                "baseline_response_bytes": len(json.dumps(
                    baseline_response.data, default=str).encode("utf-8")),
                "optimized_response_bytes": len(json.dumps(
                    cached_response.data, default=str).encode("utf-8")),
            }))

    def test_xlsx_preview_streams_rows_and_preserves_values(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["title", "description", "category", "department"])
        worksheet.append(["XLSX ticket", "Workbook row",
                          self.category.pk, self.department.pk])
        content = BytesIO()
        workbook.save(content)
        workbook.close()
        upload = SimpleUploadedFile(
            "tickets.xlsx", content.getvalue(),
            content_type=("application/vnd.openxmlformats-officedocument."
                          "spreadsheetml.sheet"))

        response = self.client.post(
            "/api/tickets/bulk_create/", {"file": upload}, format="multipart")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["affected"], 1)
        self.assertEqual(response.data["preview"][0]["title"], "XLSX ticket")
        self.assertEqual(Ticket.objects.count(), 0)

    def test_malformed_csv_is_rejected_before_ticket_creation(self):
        upload = SimpleUploadedFile(
            "tickets.csv",
            b'title,description,category\n"unterminated,description,1\n',
            content_type="text/csv")

        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"file": upload, "preview": "false", "confirm": "true"},
            format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_bulk_followups_reuse_saved_ticket_and_skip_sla_when_absent(self):
        """Follow-ups must reuse the saved object and the request's SLA cache.

        The old callback refetched the ticket by primary key and then called
        two SLA helpers which each performed their own SLA lookup.  When no
        active SLA exists those helpers are no-ops, so the whole follow-up
        phase should issue no ticket SELECT and no SLA helper call.
        """
        import tickets.views as ticket_views
        from tickets.models import TicketSLA

        class FollowupTicketSelectCounter:
            def __init__(self):
                self.count = 0

            def __call__(self, execute, sql, params, many, context):
                stripped = sql.lstrip().upper()
                if (stripped.startswith("SELECT")
                        and "tickets_ticket" in sql.lower()):
                    self.count += 1
                return execute(sql, params, many, context)

        def confirm_and_run_followups(with_sla):
            if with_sla:
                TicketSLA.objects.create(
                    priority="medium", target_resolution_hours=24,
                    is_active=True)
            row = self._row("followup-reuse")
            row["priority"] = "medium"
            callbacks = []

            def collect_on_commit(callback, using=None):
                callbacks.append(callback)

            with patch.object(ticket_views.transaction, "on_commit",
                              side_effect=collect_on_commit), \
                    patch("common.notification_delivery._notify_sla_approaching") \
                    as approaching, \
                    patch("common.notification_delivery._notify_sla_breached") \
                    as breached:
                response = self.client.post(
                    "/api/tickets/bulk_create/",
                    {"tickets": [row], "preview": False, "confirm": True},
                    format="json")

            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["summary"]["ok"], 1, response.data)
            followups = [cb for cb in callbacks
                         if getattr(cb, "__name__", "") == "_send_bulk_followups"]
            self.assertEqual(len(followups), 1)
            counter = FollowupTicketSelectCounter()
            with connection.execute_wrapper(counter):
                followups[0]()
            return counter.count, approaching, breached

        ticket_selects, approaching, breached = confirm_and_run_followups(False)
        self.assertEqual(ticket_selects, 0)
        approaching.assert_not_called()
        breached.assert_not_called()

        ticket_selects, approaching, breached = confirm_and_run_followups(True)
        self.assertEqual(ticket_selects, 0)
        approaching.assert_called()
        breached.assert_called()

