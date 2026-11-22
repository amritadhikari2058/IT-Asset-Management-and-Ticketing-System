import csv
import gc
import hashlib
import io
import json
import os
import statistics
import time
import tracemalloc

from django.db import connection
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import Department
from accounts.tests import make_users
from assets.models import Asset, AssetCategory
from common.exports import build_rows, render_response
from common.models import AuditLog
from common.views import export_dataset


class SharedExportScalabilityTests(TestCase):
    def setUp(self):
        self.department, _, self.manager, _ = make_users()
        self.category = AssetCategory.objects.create(name="Export category")
        Asset.objects.bulk_create([
            Asset(
                asset_tag=(
                    f"SIZE5-SIZE25-SIZE100-{index:04d}" if index < 5
                    else f"SIZE25-SIZE100-{index:04d}" if index < 25
                    else f"SIZE100-{index:04d}"
                ),
                name=("=SUM(1,1)" if index == 0 else
                      "Café 器材" if index == 1 else f"Asset {index}"),
                category=self.category,
                department=self.department,
                status="available",
            )
            for index in range(100)
        ])

    def test_asset_export_preloads_foreign_keys(self):
        with self.assertNumQueries(1):
            rows = list(build_rows("assets", user=self.manager))

        self.assertEqual(len(rows), 100)
        first = next(row for row in rows if row["name"] == "=SUM(1,1)")
        self.assertEqual(first["category"], "Export category")
        self.assertEqual(first["department"], self.department.name)

    def test_department_export_aggregates_counts_in_one_query(self):
        for index in range(25):
            Department.objects.create(
                name=f"Export department {index:02d}",
                code=f"EX{index:04d}",
            )

        with self.assertNumQueries(1):
            rows = list(build_rows("departments", user=self.manager))

        self.assertEqual(len(rows), 26)
        row = next(item for item in rows
                   if item["id"] == self.department.pk)
        self.assertEqual(row["member_count"], 3)
        self.assertEqual(row["asset_count"], 100)

    def test_asset_export_query_count_stays_flat_from_5_to_100_rows(self):
        for token, count in (("SIZE5", 5), ("SIZE25", 25), ("SIZE100", 100)):
            with self.subTest(count=count):
                with self.assertNumQueries(1):
                    rows = list(build_rows(
                        "assets", user=self.manager,
                        filters={"q": token}))
                self.assertEqual(len(rows), count)

    def test_thousand_row_csv_preserves_columns_unicode_and_escaping(self):
        Asset.objects.bulk_create([
            Asset(
                asset_tag=f"SIZE100-EXTRA-{index:04d}",
                name=f"Large asset {index}",
                category=self.category,
                department=self.department,
                status="available",
            )
            for index in range(100, 1000)
        ])

        with self.assertNumQueries(1):
            response = render_response(
                "assets",
                build_rows("assets", user=self.manager,
                           filters={"q": "SIZE100"}),
                "csv",
                self.manager,
                None,
            )

        self.assertEqual(response.export_row_count, 1000)
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
        self.assertEqual(rows[0], [
            "id", "asset_tag", "name", "serial_number", "status", "location",
            "category", "department", "purchase_date", "warranty_expiry",
            "purchase_cost", "created_at", "updated_at",
        ])
        self.assertEqual(len(rows), 1001)
        exported = {row[1]: row[2:] for row in rows[1:]}
        self.assertEqual(
            exported["SIZE5-SIZE25-SIZE100-0000"][0], "'=SUM(1,1)")
        self.assertEqual(
            exported["SIZE5-SIZE25-SIZE100-0001"][0], "Café 器材")

    def test_repeatable_large_csv_memory_benchmark(self):
        Asset.objects.bulk_create([
            Asset(
                asset_tag=f"SIZE100-EXTRA-{index:04d}",
                name=f"Large asset {index}",
                category=self.category,
                department=self.department,
                status="available",
            )
            for index in range(100, 1000)
        ])

        def measure(materialize):
            elapsed_ms = []
            peak_bytes = []
            response_digest = None
            response_size = 0
            for _ in range(5):
                gc.collect()
                tracemalloc.start()
                started = time.perf_counter()
                try:
                    with self.assertNumQueries(1):
                        rows = build_rows(
                            "assets", user=self.manager,
                            filters={"q": "SIZE100"})
                        if materialize:
                            rows = list(rows)
                        response = render_response(
                            "assets", rows, "csv", self.manager, None)
                    elapsed_ms.append(
                        (time.perf_counter() - started) * 1000)
                    response_size = len(response.content)
                    response_digest = hashlib.sha256(
                        response.content).hexdigest()
                finally:
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    peak_bytes.append(peak)
                del rows, response
            return {
                "median_ms": statistics.median(elapsed_ms),
                "range_ms": [min(elapsed_ms), max(elapsed_ms)],
                "median_traced_peak_bytes": statistics.median(peak_bytes),
                "response_size_bytes": response_size,
                "response_sha256": response_digest,
            }

        materialized = measure(materialize=True)
        iterated = measure(materialize=False)
        self.assertEqual(
            materialized["response_sha256"], iterated["response_sha256"])
        self.assertEqual(
            materialized["response_size_bytes"],
            iterated["response_size_bytes"])
        self.assertLess(
            iterated["median_traced_peak_bytes"],
            materialized["median_traced_peak_bytes"])
        if os.environ.get("SCALABILITY_BENCHMARK") == "1":
            print(json.dumps({
                "database_vendor": connection.vendor,
                "rows": 1000,
                "runs": 5,
                "materialized": materialized,
                "iterator": iterated,
            }))

    def test_write_only_xlsx_preserves_workbook_features(self):
        from openpyxl import load_workbook

        with self.assertNumQueries(1):
            response = render_response(
                "assets", build_rows("assets", user=self.manager),
                "xlsx", self.manager, None)

        self.assertEqual(response.export_row_count, 100)
        workbook = load_workbook(io.BytesIO(response.content), read_only=False)
        worksheet = workbook.active
        self.assertEqual(worksheet.title, "Assets")
        self.assertEqual(
            [cell.value for cell in worksheet[1]],
            ["id", "asset_tag", "name", "serial_number", "status", "location",
             "category", "department", "purchase_date", "warranty_expiry",
             "purchase_cost", "created_at", "updated_at"])
        self.assertEqual(worksheet.freeze_panes, "A2")
        self.assertEqual(worksheet.auto_filter.ref, "A1:M102")
        self.assertEqual(worksheet.max_row, 101)
        escaped_formula = next(
            cell[0] for cell in worksheet.iter_rows(
                min_row=2, min_col=3, max_col=3)
            if cell[0].value == "'=SUM(1,1)")
        self.assertEqual(escaped_formula.data_type, "s")
        workbook.close()

    def test_empty_csv_and_xlsx_exports_keep_headers(self):
        from openpyxl import load_workbook

        with self.assertNumQueries(2):
            csv_response = render_response(
                "assets",
                build_rows("assets", user=self.manager,
                           filters={"q": "NO-MATCH"}),
                "csv", self.manager, None)
            xlsx_response = render_response(
                "assets",
                build_rows("assets", user=self.manager,
                           filters={"q": "NO-MATCH"}),
                "xlsx", self.manager, None)

        self.assertEqual(csv_response.export_row_count, 0)
        csv_rows = list(csv.reader(
            io.StringIO(csv_response.content.decode("utf-8"))))
        self.assertEqual(csv_rows, [[
            "id", "asset_tag", "name", "serial_number", "status", "location",
            "category", "department", "purchase_date", "warranty_expiry",
            "purchase_cost", "created_at", "updated_at",
        ]])
        self.assertEqual(xlsx_response.export_row_count, 0)
        workbook = load_workbook(
            io.BytesIO(xlsx_response.content), read_only=False)
        worksheet = workbook.active
        self.assertEqual(worksheet.max_row, 1)
        self.assertEqual(worksheet.freeze_panes, "A2")
        workbook.close()

    def test_pdf_and_docx_renderers_accept_generator_rows(self):
        for fmt, signature in (("pdf", b"%PDF"), ("docx", b"PK")):
            with self.subTest(format=fmt):
                response = render_response(
                    "assets", build_rows("assets", user=self.manager),
                    fmt, self.manager, None)
                self.assertEqual(response.export_row_count, 100)
                self.assertTrue(response.content.startswith(signature))

    def test_selected_export_stream_filter_keeps_audit_row_count(self):
        selected_ids = list(
            Asset.objects.order_by("id").values_list("id", flat=True)[:3])
        request = APIRequestFactory().get(
            "/api/common/exports/assets/",
            {"format": "csv", "scope": "selected",
             "ids": ",".join(str(pk) for pk in selected_ids)},
        )
        force_authenticate(request, user=self.manager)

        response = export_dataset(request, dataset="assets")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.export_row_count, 3)
        self.assertEqual(len(response.content.decode("utf-8").splitlines()), 4)
        audit = AuditLog.objects.filter(
            actor=self.manager, entity_type="exports.assets").latest("id")
        self.assertEqual(audit.details["rows"], 3)
