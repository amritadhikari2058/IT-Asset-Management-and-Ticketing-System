import csv
import ctypes
import gc
import io
import json
import os
import statistics
import time
import tracemalloc
import unittest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from openpyxl import Workbook
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory, AssetHistory
from tickets.models import Ticket, TicketCategory, TicketHistory


def _process_peak_rss_bytes():
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters),
            counters.cb):
        return None
    return counters.PeakWorkingSetSize


class QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, execute, sql, params, many, context):
        self.count += 1
        return execute(sql, params, many, context)


class ImportScalabilityBase(TestCase):
    def setUp(self):
        self.department, self.admin, self.manager, self.employee = make_users()
        self.client = APIClient()
        auth(self.client, self.manager)
        self.asset_category = AssetCategory.objects.create(
            name="Import benchmark asset")
        self.ticket_category = TicketCategory.objects.create(
            name="Import benchmark ticket")

    def upload(self, name, headers, rows):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(headers)
        writer.writerows(rows)
        return SimpleUploadedFile(
            name, buffer.getvalue().encode("utf-8"), content_type="text/csv")

    def profile_preview(self, url, make_upload, row_count):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.post(
                url, {"file": make_upload(), "preview": "true"},
                format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        metrics = {
            "rows": row_count,
            "queries": len(captured),
        }

        timings = []
        peaks = []
        for _ in range(3):
            gc.collect()
            connection.queries_log.clear()
            tracemalloc.start()
            started = time.perf_counter()
            response = self.client.post(
                url, {"file": make_upload(), "preview": "true"},
                format="multipart")
            timings.append((time.perf_counter() - started) * 1000)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peaks.append(peak)
            self.assertEqual(response.status_code, 200, response.data)
        metrics.update({
            "median_ms": statistics.median(timings),
            "range_ms": [min(timings), max(timings)],
            "median_peak_python_bytes": statistics.median(peaks),
        })
        return metrics

    def emit_metrics(self, workflow, metrics):
        if os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1":
            print(json.dumps({"workflow": workflow, "measurements": metrics}))

    def profile_large_preview(self, url, make_upload, row_count, success_count,
                              repetitions=2):
        durations, python_peaks, query_counts = [], [], []
        payload_bytes = 0
        for _ in range(repetitions):
            upload = make_upload()
            gc.collect()
            tracemalloc.start()
            started = time.perf_counter()
            query_counter = QueryCounter()
            with connection.execute_wrapper(query_counter):
                response = self.client.post(
                    url, {"file": upload, "preview": "true"},
                    format="multipart")
            durations.append(time.perf_counter() - started)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertEqual(response.status_code, 200, response.data)
            query_counts.append(query_counter.count)
            python_peaks.append(peak)
            payload_bytes = len(json.dumps(
                response.data, default=str).encode("utf-8"))
            self.assertEqual(success_count(response.data), row_count)
        median_seconds = statistics.median(durations)
        return {
            "rows": row_count,
            "database": connection.vendor,
            "duration_ms_median": round(median_seconds * 1000, 2),
            "rows_per_second_median": round(row_count / median_seconds, 1),
            "peak_rss_bytes": _process_peak_rss_bytes(),
            "peak_python_bytes_median": int(statistics.median(python_peaks)),
            "queries_median": int(statistics.median(query_counts)),
            "successful": row_count,
            "failed": 0,
            "response_bytes": payload_bytes,
            "repetitions": repetitions,
        }

    def profile_confirmation(self, url, make_upload, row_count,
                             success_count):
        upload = make_upload()
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        query_counter = QueryCounter()
        with connection.execute_wrapper(query_counter):
            response = self.client.post(
                url, {"file": upload, "preview": "false", "confirm": "true"},
                format="multipart")
        duration = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(response.status_code, 200, response.data)
        successful = success_count(response.data)
        self.assertEqual(successful, row_count)
        return {
            "rows": row_count,
            "database": connection.vendor,
            "duration_ms": round(duration * 1000, 2),
            "rows_per_second": round(row_count / duration, 1),
            "peak_rss_bytes": _process_peak_rss_bytes(),
            "peak_python_bytes": peak,
            "queries": query_counter.count,
            "successful": successful,
            "failed": 0,
            "response_bytes": len(json.dumps(
                response.data, default=str).encode("utf-8")),
        }


class EmployeeImportScalabilityTests(ImportScalabilityBase):
    def _rows(self, prefix, count):
        return [
            (f"{prefix}-{index:05d}",
             f"{prefix.lower()}-{index}@example.test",
             f"Employee {index}", "Scalability")
            for index in range(count)
        ]

    def _upload(self, prefix, count):
        headers = ["employee_id", "email", "first_name", "last_name"]
        rows = self._rows(prefix, count)
        return lambda: self.upload("employees.csv", headers, rows)

    def test_preview_query_counts_at_5_25_100_rows(self):
        metrics = []
        for count in (5, 25, 100):
            measure = self.profile_preview(
                "/api/accounts/users/bulk_import/",
                self._upload(f"PREVIEW{count}", count), count)
            metrics.append(measure)
            self.assertEqual(measure["rows"], count)
        self.assertEqual([item["queries"] for item in metrics], [2, 2, 2])
        self.emit_metrics("employee preview", metrics)

    def test_large_csv_preview_processes_all_rows(self):
        count = 1000
        response = self.client.post(
            "/api/accounts/users/bulk_import/",
            {"file": self._upload("EMPLOYEE1000", count)(),
             "preview": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["counts"], {"ok": count, "failed": 0})

    def test_xlsx_preview_streams_employee_rows(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["employee_id", "email", "first_name"])
        worksheet.append(["XLSX-1", "xlsx@example.test", "Spreadsheet"])
        contents = io.BytesIO()
        workbook.save(contents)
        response = self.client.post(
            "/api/accounts/users/bulk_import/",
            {"file": SimpleUploadedFile(
                "employees.xlsx", contents.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument."
                             "spreadsheetml.sheet"),
             "preview": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["counts"], {"ok": 1, "failed": 0})
        self.assertEqual(
            response.data["preview"][0]["employee_id"], "XLSX-1")

    @override_settings(EMPLOYEE_BULK_IMPORT_MAX_ROWS=2)
    def test_upload_row_limit_is_rejected_before_confirmation(self):
        response = self.client.post(
            "/api/accounts/users/bulk_import/",
            {"file": self._upload("TOOMANY", 3)(), "preview": "false",
             "confirm": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("Too many rows", str(response.data))
        self.assertEqual(
            User.objects.filter(employee_id__startswith="TOOMANY").count(), 0)

    def test_malformed_csv_is_rejected_before_confirmation(self):
        upload = SimpleUploadedFile(
            "malformed.csv",
            b"employee_id,email\nE-MALFORMED,valid@example.test\n"
            b"\"unterminated",
            content_type="text/csv")
        response = self.client.post(
            "/api/accounts/users/bulk_import/",
            {"file": upload, "preview": "false", "confirm": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(User.objects.filter(
            employee_id="E-MALFORMED").exists())

    def test_confirmation_imports_csv_rows_in_batches(self):
        count = 100
        prefix = "EMPLOYEE-CONFIRM"
        response = self.client.post(
            "/api/accounts/users/bulk_import/",
            {"file": self._upload(prefix, count)(),
             "preview": "false", "confirm": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"]["ok"], count)
        self.assertEqual(
            User.objects.filter(employee_id__startswith=prefix).count(),
            count)

    def test_confirmation_detects_duplicate_across_batch_boundary(self):
        rows = [
            (f"BOUNDARY-{index:04d}", f"boundary-{index}@example.test")
            for index in range(250)
        ]
        rows.append(("BOUNDARY-0000", "duplicate@example.test"))
        upload = self.upload("employees.csv", ["employee_id", "email"], rows)
        response = self.client.post(
            "/api/accounts/users/bulk_import/",
            {"file": upload, "preview": "false", "confirm": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"], {
            "ok": 250, "skipped": 0, "failed": 1})
        self.assertEqual(User.objects.filter(
            employee_id__startswith="BOUNDARY-").count(), 250)


class AssetImportScalabilityTests(ImportScalabilityBase):
    def _rows(self, prefix, count):
        return [
            (f"{prefix}-{index:05d}", f"Asset {index}",
             self.asset_category.name, "", self.department.code, "available")
            for index in range(count)
        ]

    def _upload(self, prefix, count):
        headers = ["asset_tag", "name", "category", "serial_number",
                   "department", "status"]
        rows = self._rows(prefix, count)
        return lambda: self.upload("assets.csv", headers, rows)

    def test_preview_reference_query_counts_at_5_25_100_rows(self):
        metrics = []
        for count in (5, 25, 100):
            measure = self.profile_preview(
                "/api/assets/bulk_create/",
                self._upload(f"PREVIEW{count}", count), count)
            metrics.append(measure)
            self.assertEqual(measure["rows"], count)
        self.assertEqual([item["queries"] for item in metrics], [4, 4, 4])
        self.emit_metrics("asset preview", metrics)

    def test_large_csv_preview_processes_all_rows(self):
        count = 1000
        response = self.client.post(
            "/api/assets/bulk_create/",
            {"file": self._upload("ASSET1000", count)(),
             "preview": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["preview"]), count)
        self.assertEqual(response.data["errors"], [])
        self.assertEqual(Asset.objects.count(), 0)

    def test_confirmation_batches_lookups_and_preserves_history(self):
        count = 100
        with CaptureQueriesContext(connection) as captured:
            response = self.client.post(
                "/api/assets/bulk_create/",
                {"file": self._upload("ASSETCONFIRM", count)(),
                 "preview": "false", "confirm": "true"},
                format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["successful"]), count)
        self.assertEqual(response.data["failed"], [])
        self.assertLess(len(captured), 600)
        self.assertEqual(Asset.objects.count(), count)
        self.assertEqual(AssetHistory.objects.count(), count)


class TicketImportScalabilityTests(ImportScalabilityBase):
    def _rows(self, prefix, count):
        return [
            (f"{prefix} Ticket {index}", "Import benchmark description",
             self.ticket_category.pk, self.department.pk, "medium")
            for index in range(count)
        ]

    def _upload(self, prefix, count):
        headers = ["title", "description", "category", "department",
                   "priority"]
        rows = self._rows(prefix, count)
        return lambda: self.upload("tickets.csv", headers, rows)

    def test_preview_query_counts_at_5_25_100_rows(self):
        metrics = []
        for count in (5, 25, 100):
            measure = self.profile_preview(
                "/api/tickets/bulk_create/",
                self._upload(f"PREVIEW{count}", count), count)
            metrics.append(measure)
            self.assertEqual(measure["rows"], count)
        self.emit_metrics("ticket preview", metrics)

    def test_missing_references_are_rejected(self):
        rows = [{
            "title": f"Invalid references {index}",
            "description": "Reference validation test",
            "category": 999999,
            "department": 999999,
            "assignee": 999999,
            "asset": 999999,
        } for index in range(5)]
        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"tickets": rows, "preview": True},
            format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["affected"], 0)
        self.assertEqual(len(response.data["invalid"]), len(rows))
        for item in response.data["invalid"]:
            self.assertEqual(
                set(item["errors"]),
                {"category", "department", "assignee", "asset"})

    def test_confirmation_keeps_row_level_partial_success_and_history(self):
        count = 25
        rows = self._rows("CONFIRM", count)
        rows[12] = (
            "Invalid reference ticket", "Import benchmark description",
            999999, self.department.pk, "medium")
        upload = self.upload(
            "tickets.csv",
            ["title", "description", "category", "department", "priority"],
            rows)
        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"file": upload,
             "preview": "false", "confirm": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"], {
            "ok": count - 1, "skipped": 0, "failed": 1})
        self.assertEqual(Ticket.objects.count(), count - 1)
        self.assertEqual(TicketHistory.objects.count(), count - 1)

    def test_large_csv_preview_processes_all_rows_within_configured_limit(self):
        count = 500
        response = self.client.post(
            "/api/tickets/bulk_create/",
            {"file": self._upload("TICKET500", count)(),
             "preview": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["affected"], count)
        self.assertEqual(len(response.data["preview"]), count)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(TicketHistory.objects.count(), 0)


class LargeImportBenchmarkTests(ImportScalabilityBase):
    def _benchmark_preview(self, url, filename, headers, rows, count,
                           success_count):
        contents = self.upload(filename, headers, rows).read()
        return self.profile_large_preview(
            url,
            lambda: SimpleUploadedFile(
                filename, contents, content_type="text/csv"),
            count, success_count)

    @unittest.skipUnless(
        os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1",
        "set IMPORT_SCALABILITY_BENCHMARK=1 to run large import benchmarks")
    def test_progressively_larger_employee_previews(self):
        measurements = {}
        employee_headers = ["employee_id", "email", "first_name",
                            "last_name"]
        for count in (1000, 5000, 10000, 25000):
            rows = [
                (f"BENCH{count}-{index:05d}",
                 f"bench-{count}-{index}@example.test",
                 f"Employee {index}", "Benchmark")
                for index in range(count)
            ]
            measurements[count] = self._benchmark_preview(
                "/api/accounts/users/bulk_import/",
                "employees.csv", employee_headers, rows, count,
                lambda data: data["counts"]["ok"])
        self.emit_metrics("employee previews", measurements)

    @unittest.skipUnless(
        os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1",
        "set IMPORT_SCALABILITY_BENCHMARK=1 to run large import benchmarks")
    def test_progressively_larger_asset_previews(self):
        measurements = {}
        asset_headers = ["asset_tag", "name", "category", "serial_number",
                         "department", "status"]
        for count in (1000, 5000, 10000, 25000):
            rows = [
                (f"BENCH-{count}-{index:05d}", f"Asset {index}",
                 self.asset_category.name, "", self.department.code,
                 "available")
                for index in range(count)
            ]
            measurements[count] = self._benchmark_preview(
                "/api/assets/bulk_create/",
                "assets.csv", asset_headers, rows, count,
                lambda data: len(data["preview"]))
        self.emit_metrics("asset previews", measurements)

    @unittest.skipUnless(
        os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1",
        "set IMPORT_SCALABILITY_BENCHMARK=1 to run large import benchmarks")
    def test_larger_ticket_previews_with_existing_row_cap(self):
        measurements = {}
        ticket_headers = ["title", "description", "category", "department",
                          "priority"]
        for count in (100, 500):
            rows = [
                (f"Benchmark Ticket {index}", "Import benchmark description",
                 self.ticket_category.pk, self.department.pk, "medium")
                for index in range(count)
            ]
            measurements[count] = self._benchmark_preview(
                "/api/tickets/bulk_create/",
                "tickets.csv", ticket_headers, rows, count,
                lambda data: data["affected"])
        self.emit_metrics("ticket previews", measurements)

    @unittest.skipUnless(
        os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1",
        "set IMPORT_SCALABILITY_BENCHMARK=1 to run large import benchmarks")
    def test_asset_confirmation_query_regression(self):
        headers = ["asset_tag", "name", "category", "serial_number",
                   "department", "status"]
        measurements = {}
        for count in (100, 1000):
            rows = [
                (f"CONFIRM-{count}-{index:05d}", f"Asset {index}",
                 self.asset_category.name, "", self.department.code,
                 "available")
                for index in range(count)
            ]
            contents = self.upload("assets.csv", headers, rows).read()
            metrics = self.profile_confirmation(
                "/api/assets/bulk_create/",
                lambda: SimpleUploadedFile(
                    "assets.csv", contents, content_type="text/csv"),
                count, lambda data: len(data["successful"]))
            measurements[count] = metrics
            self.assertLess(metrics["queries"], count * 6)
        self.emit_metrics("asset confirmations", measurements)
        self.assertEqual(Asset.objects.count(), 1100)

    @unittest.skipUnless(
        os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1",
        "set IMPORT_SCALABILITY_BENCHMARK=1 to run large import benchmarks")
    def test_employee_confirmation_large_import(self):
        count = 1000
        prefix = "EMPLOYEE-CONFIRM-BENCH"
        headers = ["employee_id", "email", "first_name", "last_name"]
        rows = [
            (f"{prefix}-{index:05d}",
             f"confirm-bench-{index}@example.test",
             f"Employee {index}", "Benchmark")
            for index in range(count)
        ]
        contents = self.upload("employees.csv", headers, rows).read()
        metrics = self.profile_confirmation(
            "/api/accounts/users/bulk_import/",
            lambda: SimpleUploadedFile(
                "employees.csv", contents, content_type="text/csv"),
            count, lambda data: data["summary"]["ok"])
        self.emit_metrics("employee confirmation", metrics)
        self.assertEqual(
            User.objects.filter(employee_id__startswith=prefix).count(),
            count)

    @unittest.skipUnless(
        os.environ.get("IMPORT_SCALABILITY_BENCHMARK") == "1",
        "set IMPORT_SCALABILITY_BENCHMARK=1 to run large import benchmarks")
    def test_ticket_confirmation_at_existing_row_cap(self):
        count = 500
        headers = ["title", "description", "category", "department",
                   "priority"]
        rows = [
            (f"Confirmed benchmark ticket {index}",
             "Import benchmark description", self.ticket_category.pk,
             self.department.pk, "medium")
            for index in range(count)
        ]
        contents = self.upload("tickets.csv", headers, rows).read()
        metrics = self.profile_confirmation(
            "/api/tickets/bulk_create/",
            lambda: SimpleUploadedFile(
                "tickets.csv", contents, content_type="text/csv"),
            count, lambda data: data["summary"]["ok"])
        self.emit_metrics("ticket confirmation", metrics)
        self.assertEqual(Ticket.objects.count(), count)
        self.assertEqual(TicketHistory.objects.count(), count)

