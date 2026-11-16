"""CMDB performance and bounded-behavior contract tests."""

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from accounts.models import Department
from assets.models import Asset, AssetCategory
from cmdb.models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
    ConfigurationItemType,
    ServiceConfigurationItemLink,
)
from cmdb.tests import api_client, make_user
from services.models import ServiceCatalogueItem


class CMDBPerformanceBase(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin", suffix="perf")
        self.client = api_client(self.admin)
        self.ctype = ConfigurationItemType.objects.create(name="Server", code="SRVP", category="hardware")
        self.dept = Department.objects.create(name="Perf", code="PF1")

    def mk_ci(self, name, **kw):
        defaults = dict(ci_type=self.ctype, status="active", department=self.dept)
        defaults.update(kw)
        return ConfigurationItem.objects.create(name=name, **defaults)


class QueryBoundTests(CMDBPerformanceBase):
    def test_ci_list_query_bounds(self):
        for i in range(5):
            self.mk_ci(f"CI{i}")
        # defensible upper bound for bounded list endpoint
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/api/cmdb/items/")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data), 5)
        self.assertLessEqual(len(ctx), 5)

    def test_type_relationship_dashboard_reports_verification_history_detail(self):
        ci = self.mk_ci("Root")
        for i in range(3):
            other = self.mk_ci(f"C{i}")
            ConfigurationItemRelationship.objects.create(source_ci=ci, target_ci=other, relationship_type="depends_on", status="active")
            ConfigurationItemHistory.objects.create(configuration_item=ci, event_type="updated", detail=str(i))

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/types/").status_code, 200)
        self.assertLessEqual(len(ctx), 10)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/relationships/").status_code, 200)
        self.assertLessEqual(len(ctx), 15)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/dashboard/").status_code, 200)
        self.assertLessEqual(len(ctx), 80)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/reports/coverage/").status_code, 200)
        self.assertLessEqual(len(ctx), 40)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/verification/").status_code, 200)
        self.assertLessEqual(len(ctx), 40)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(f"/api/cmdb/items/{ci.id}/").status_code, 200)
        self.assertLessEqual(len(ctx), 20)

    def test_graph_impact_baseline_drift_lists_bounded(self):
        a = self.mk_ci("A")
        b = self.mk_ci("B")
        ConfigurationItemRelationship.objects.create(source_ci=a, target_ci=b, relationship_type="depends_on", status="active")
        svc = ServiceCatalogueItem.objects.create(name="SvcP", is_active=True)
        ServiceConfigurationItemLink.objects.create(service=svc, configuration_item=a, role="primary")
        baseline = ConfigurationBaseline.objects.create(name="PB", scope_type="single_ci", status="approved", snapshot={"cis": {}}, checksum="x")
        baseline.configuration_items.add(a)
        ConfigurationDriftFinding.objects.create(configuration_item=a, baseline=baseline, finding_type="field_changed", severity="low", status="open", field_name="name", expected_value="x", actual_value="y", fingerprint="pf1")

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(f"/api/cmdb/items/{a.id}/dependencies/").status_code, 200)
        self.assertLessEqual(len(ctx), 30)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(f"/api/cmdb/items/{a.id}/impact/").status_code, 200)
        self.assertLessEqual(len(ctx), 60)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(f"/api/cmdb/services/{svc.id}/graph/").status_code, 200)
        self.assertLessEqual(len(ctx), 40)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(f"/api/cmdb/services/{svc.id}/impact/").status_code, 200)
        self.assertLessEqual(len(ctx), 40)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/baselines/").status_code, 200)
        self.assertLessEqual(len(ctx), 15)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get("/api/cmdb/drift/").status_code, 200)
        self.assertLessEqual(len(ctx), 15)


class BoundsAndIdempotencyTests(CMDBPerformanceBase):
    def test_caps_depth_nodes_and_no_duplicate_drift_notification(self):
        # list caps already covered in API contracts; verify behavior via direct flags/payloads where possible
        a = self.mk_ci("GA")
        r = self.client.get(f"/api/cmdb/items/{a.id}/dependencies/?depth=999")
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(r.data.get("max_depth", 0), 10)
        self.assertIn("truncated", r.data)
        self.assertLessEqual(r.data.get("nodeCount", 0), 200)
        # repeated drift evaluation should not duplicate same open finding fingerprint
        baseline = ConfigurationBaseline.objects.create(name="DB", scope_type="single_ci", status="approved", snapshot={"cis": {a.ci_number: {"name": "Diff", "status": "active", "lifecycle_state": "proposed", "criticality": "medium", "environment": "production", "version": "", "manufacturer": "", "model": "", "hostname": "", "ip_address": None, "dns_name": "", "location": "", "monitoring_state": "unknown", "data_classification": "internal", "validated_system_impact": "none", "contains_personal_data": False, "ci_type_id": self.ctype.id, "department_id": self.dept.id, "owner_id": None, "technical_owner_id": None, "support_group_id": None, "vendor_id": None, "service_catalogue_item_id": None, "attributes": {}, "relationships": []}}}, checksum="x")
        baseline.configuration_items.add(a)
        from cmdb.baselines import evaluate_configuration_drift
        evaluate_configuration_drift(a, baseline=baseline, notify=True)
        c1 = ConfigurationDriftFinding.objects.filter(configuration_item=a).count()
        evaluate_configuration_drift(a, baseline=baseline, notify=True)
        c2 = ConfigurationDriftFinding.objects.filter(configuration_item=a).count()
        self.assertEqual(c1, c2)
