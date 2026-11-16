"""CMDB API contract tests (exhaustive executable coverage)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department
from assets.models import Asset, AssetCategory, Vendor
from cmdb.models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemChangeLink,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
    ConfigurationItemTicketLink,
    ConfigurationItemType,
    ServiceConfigurationItemLink,
)
from cmdb.tests import api_client, create_ci, make_user
from services.models import ServiceCatalogueItem


def _mk_type(code="SRV", name="Server", category="hardware"):
    return ConfigurationItemType.objects.create(name=name, code=code, category=category)


class APIContractBase(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.manager = make_user("it_manager")
        self.support = make_user("it_support")
        self.employee = make_user("employee")
        self.client = api_client(self.admin)
        self.dept = Department.objects.create(name="Ops", code="OPS1")
        self.vendor = Vendor.objects.create(name="Acme")


class CITypeContractTests(APIContractBase):
    def test_slash_no_slash_and_aliases(self):
        for url in ["/api/cmdb/types/", "/api/cmdb/types", "/api/cmdb/configuration-item-types/", "/api/cmdb/configuration-item-types"]:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)

    def test_ci_count_excludes_deleted(self):
        ctype = _mk_type("NET", "Network", "network")
        ConfigurationItem.objects.create(name="a", ci_type=ctype)
        deleted = ConfigurationItem.objects.create(name="b", ci_type=ctype)
        type(deleted).objects.filter(pk=deleted.pk).update(is_deleted=True)
        r = self.client.get("/api/cmdb/types/")
        row = next(t for t in r.data if t["id"] == ctype.id)
        self.assertEqual(row["ci_count"], 1)

    def test_list_plain_array_and_page_envelope(self):
        _mk_type("A1", "A1")
        _mk_type("A2", "A2")
        r = self.client.get("/api/cmdb/types/")
        self.assertIsInstance(r.data, list)
        rp = self.client.get("/api/cmdb/types/?page=1")
        self.assertIsInstance(rp.data, dict)
        for key in ("count", "next", "previous", "results"):
            self.assertIn(key, rp.data)


class CIListContractTests(APIContractBase):
    def setUp(self):
        super().setUp()
        self.ctype = _mk_type()

    def test_plain_array_page_envelope_and_cap_1000(self):
        for i in range(3):
            ConfigurationItem.objects.create(name=f"CI{i}", ci_type=self.ctype)
        r = self.client.get("/api/cmdb/items/")
        self.assertIsInstance(r.data, list)
        rp = self.client.get("/api/cmdb/items/?page=1")
        for key in ("count", "next", "previous", "results"):
            self.assertIn(key, rp.data)
        for i in range(3, 1005):
            ConfigurationItem.objects.create(name=f"CI{i}", ci_type=self.ctype)
        r2 = self.client.get("/api/cmdb/items/")
        self.assertIsInstance(r2.data, list)
        self.assertLessEqual(len(r2.data), 1000)

    def test_filters(self):
        c2 = _mk_type("APP", "App", "application")
        ci = ConfigurationItem.objects.create(
            name="ProdSrv", ci_type=self.ctype, status="active",
            criticality="critical", environment="production",
            department=self.dept, location="DC-A",
        )
        ConfigurationItem.objects.create(
            name="DevApp", ci_type=c2, status="planned",
            criticality="low", environment="development",
        )
        cases = [
            ("status=active", ci.id),
            ("criticality=critical", ci.id),
            ("environment=production", ci.id),
            (f"department={self.dept.id}", ci.id),
            (f"type={self.ctype.id}", ci.id),
            ("category=hardware", ci.id),
            ("location=DC-A", ci.id),
            ("q=ProdSrv", ci.id),
            ("search=ProdSrv", ci.id),
        ]
        for qs, expected_id in cases:
            with self.subTest(qs=qs):
                r = self.client.get(f"/api/cmdb/items/?{qs}")
                self.assertEqual(r.status_code, 200)
                ids = [x["id"] for x in r.data]
                self.assertIn(expected_id, ids)


class CIDetailContractTests(APIContractBase):
    def test_detail_includes_history_and_verification_status(self):
        ctype = _mk_type()
        ci = ConfigurationItem.objects.create(name="CIH", ci_type=ctype)
        ConfigurationItemHistory.objects.create(configuration_item=ci, event_type="created", detail="x")
        r = self.client.get(f"/api/cmdb/items/{ci.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("history", r.data)
        self.assertIsInstance(r.data["history"], list)
        self.assertTrue(len(r.data["history"]) >= 1)
        self.assertIn("verification_status", r.data)
        for url in [f"/api/cmdb/items/{ci.id}", f"/api/cmdb/configuration-items/{ci.id}/", f"/api/cmdb/configuration-items/{ci.id}"]:
            self.assertEqual(self.client.get(url).status_code, 200)


class DashboardContractTests(APIContractBase):
    def test_dashboard_exact_keys_and_most_recent_unverified(self):
        ctype = _mk_type()
        old = ConfigurationItem.objects.create(name="Old", ci_type=ctype, status="active")
        ConfigurationItem.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=5))
        recent = ConfigurationItem.objects.create(name="Recent", ci_type=ctype, status="active")
        ConfigurationItem.objects.filter(pk=recent.pk).update(updated_at=timezone.now() - timedelta(days=1))
        for url in ["/api/cmdb/dashboard/", "/api/cmdb/dashboard"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            for key in ("total_cis", "active_cis", "critical_cis", "unverified_cis", "open_drift_findings", "generated_at", "most_recent_unverified"):
                self.assertIn(key, r.data)
        r = self.client.get("/api/cmdb/dashboard/")
        mru = r.data["most_recent_unverified"]
        self.assertIsNotNone(mru)
        self.assertEqual(mru["id"], recent.id)
        self.assertIsNone(mru["last_verified_at"])


class ReportsContractTests(APIContractBase):
    def test_all_kinds_alias_unknown_fallback_and_shape(self):
        kinds = ["coverage", "verification_age", "orphans", "ownership_gaps", "relationship_coverage", "drift", "critical_deps", "asset_sync", "software_sync"]
        for kind in kinds:
            with self.subTest(kind=kind):
                r = self.client.get(f"/api/cmdb/reports/{kind}/")
                self.assertEqual(r.status_code, 200)
                for key in ("kind", "rows", "columns", "summary", "generated_at"):
                    self.assertIn(key, r.data)
                self.assertEqual(r.data["kind"], kind)
        r = self.client.get("/api/cmdb/reports/unverified/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kind"], "verification_age")
        r = self.client.get("/api/cmdb/reports/unknown-kind/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kind"], "coverage")
        self.assertEqual(self.client.get("/api/cmdb/reports/").status_code, 200)
        self.assertEqual(self.client.get("/api/cmdb/reports").status_code, 200)


class GraphImpactVerificationContractTests(APIContractBase):
    def setUp(self):
        super().setUp()
        self.ctype = _mk_type()
        self.a = ConfigurationItem.objects.create(name="A", ci_type=self.ctype, status="active")
        self.b = ConfigurationItem.objects.create(name="B", ci_type=self.ctype, status="active")
        self.rel = ConfigurationItemRelationship.objects.create(
            source_ci=self.a, target_ci=self.b, relationship_type="depends_on",
            status="active", confidence="confirmed",
        )

    def test_dependency_graph_shape_and_nodes(self):
        r = self.client.get(f"/api/cmdb/items/{self.a.id}/dependencies/")
        self.assertEqual(r.status_code, 200)
        for key in ("nodes", "edges", "nodeCount", "edgeCount", "cycleIndicator", "truncated", "max_depth", "view"):
            self.assertIn(key, r.data)
        self.assertTrue(len(r.data["nodes"]) >= 1)
        node = r.data["nodes"][0]
        self.assertIn("type", node)
        self.assertIn("ci_type", node)
        self.assertEqual(node["type"], node["ci_type"])
        self.assertEqual(self.client.get(f"/api/cmdb/items/{self.a.id}/dependencies").status_code, 200)
        self.assertEqual(self.client.get(f"/api/cmdb/configuration-items/{self.a.id}/dependencies/").status_code, 200)

    def test_impact_contract(self):
        r = self.client.get(f"/api/cmdb/items/{self.a.id}/impact/")
        self.assertEqual(r.status_code, 200)
        # source identifiers exposed at top level plus impact result keys
        for key in ("id", "ci_number", "name", "affected_ci_ids", "affected_count", "affected_services", "affected_departments", "affected_owners", "critical_dependencies", "single_points_of_failure", "affected_tickets", "affected_changes", "risk_summary", "truncated", "warning"):
            self.assertIn(key, r.data)

    def test_verification_queue_contract(self):
        r = self.client.get("/api/cmdb/verification/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)
        if r.data:
            row = r.data[0]
            for key in ("verification_status", "ci_id", "verified_at", "age_days"):
                self.assertIn(key, row)
        self.assertEqual(self.client.get("/api/cmdb/verification").status_code, 200)


class RelationshipAndLinkContractTests(APIContractBase):
    def test_relationship_list_and_no_slash(self):
        ctype = _mk_type()
        a = ConfigurationItem.objects.create(name="RA", ci_type=ctype)
        b = ConfigurationItem.objects.create(name="RB", ci_type=ctype)
        ConfigurationItemRelationship.objects.create(source_ci=a, target_ci=b, relationship_type="depends_on", status="active")
        for url in ["/api/cmdb/relationships/", "/api/cmdb/relationships"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertIsInstance(r.data, list)

    def test_drift_filters_baselines_and_aliases(self):
        ctype = _mk_type()
        ci = ConfigurationItem.objects.create(name="DCI", ci_type=ctype)
        baseline = ConfigurationBaseline.objects.create(name="B1", scope_type="single_ci", status="approved", snapshot={"cis": {}}, checksum="x")
        baseline.configuration_items.add(ci)
        ConfigurationDriftFinding.objects.create(configuration_item=ci, baseline=baseline, finding_type="field_changed", severity="low", status="open", field_name="name", expected_value="x", actual_value="y", fingerprint="f1")
        ConfigurationDriftFinding.objects.create(configuration_item=ci, baseline=baseline, finding_type="status_changed", severity="high", status="open", field_name="status", expected_value="a", actual_value="b", fingerprint="f2")
        self.assertEqual(self.client.get(f"/api/cmdb/drift/?ci={ci.id}").status_code, 200)
        self.assertEqual(self.client.get("/api/cmdb/drift/?type=field_changed").status_code, 200)
        self.assertEqual(self.client.get("/api/cmdb/drift/?finding_type=status_changed").status_code, 200)
        today = timezone.now().date().isoformat()
        self.assertEqual(self.client.get(f"/api/cmdb/drift/?detected_date={today},{today}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/cmdb/baselines/?configuration_items={ci.id}").status_code, 200)
        self.assertEqual(self.client.get("/api/cmdb/drift-findings").status_code, 200)

    def test_service_alias_routes_and_lists(self):
        for base in ["/api/cmdb/service-links/", "/api/cmdb/service-links", "/api/cmdb/service-ci-links/", "/api/cmdb/service-ci-links", "/api/cmdb/ticket-links/", "/api/cmdb/change-links/"]:
            self.assertEqual(self.client.get(base).status_code, 200)


class RouteSafetyAndPermissionContractTests(APIContractBase):
    def test_route_resolution_and_no_slash(self):
        paths = ["/api/cmdb/dashboard/", "/api/cmdb/reports/", "/api/cmdb/verification/", "/api/cmdb/items/", "/api/cmdb/types/"]
        for p in paths:
            self.assertIsNotNone(resolve(p).func)
        for p in ["/api/cmdb/dashboard", "/api/cmdb/reports", "/api/cmdb/verification"]:
            self.assertIsNotNone(resolve(p).func)

    def test_permission_contracts(self):
        _mk_type("P1", "P1")
        emp = api_client(self.employee)
        for url in ["/api/cmdb/items/", "/api/cmdb/dashboard/", "/api/cmdb/reports/", "/api/cmdb/types/"]:
            self.assertEqual(emp.get(url).status_code, 403)
        sup = api_client(self.support)
        self.assertEqual(sup.get("/api/cmdb/items/").status_code, 200)
        self.assertEqual(sup.get("/api/cmdb/dashboard/").status_code, 200)
        self.assertEqual(sup.post("/api/cmdb/types/", {"name": "X", "code": "X1"}, format="json").status_code, 403)
        self.assertEqual(api_client(self.manager).post("/api/cmdb/types/", {"name": "Y", "code": "Y1"}, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/cmdb/types/", {"name": "Z", "code": "Z1"}, format="json").status_code, 201)
