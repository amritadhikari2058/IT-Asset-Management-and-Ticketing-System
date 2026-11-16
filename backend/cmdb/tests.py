"""CMDB API contract tests: endpoints, response shapes, concurrency,
permissions at endpoint level and cross-app integration.

Response contract (frontend cmdb-*.jsx):
- list endpoints return plain bounded arrays by default, paginated
  envelopes {count, next, previous, results} only when ?page=N is given
- dashboard/reports/verification/service endpoints return flat objects
  with the documented keys
- action URLs work with and without trailing slashes
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from cmdb.baselines import evaluate_configuration_drift
from cmdb.models import (
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemRelationship,
    ConfigurationItemType,
)
from cmdb.services import sync_asset_to_ci
from services.models import ServiceCatalogueItem

User = get_user_model()

_seq = [0]


def make_user(role, suffix=None):
    _seq[0] += 1
    tag = suffix or str(_seq[0])
    # No password: tests authenticate via force_authenticate and PBKDF2
    # hashing dominates suite runtime otherwise.
    return User.objects.create_user(
        username=f"{role}_u{tag}",
        role=role,
        email=f"{role}.{tag}@example.test",
        employee_id=f"EMP{role}{tag}",
    )


def api_client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def create_ci(client, name, ci_type, **fields):
    payload = {"name": name, "ci_type": ci_type.id}
    payload.update(fields)
    response = client.post("/api/cmdb/items/", payload, format="json")
    if response.status_code != 201:
        raise AssertionError(f"CI create failed: {response.status_code} "
                             f"{getattr(response, 'data', response)}")
    return response.data


class CMDBTypeTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)

    def test_create_type(self):
        r = self.client.post(
            "/api/cmdb/types/",
            {"name": "Server", "code": "SERVER", "category": "hardware"},
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["code"], "SERVER")

    def test_employee_denied(self):
        emp = make_user("employee")
        r = api_client(emp).get("/api/cmdb/types/")
        self.assertIn(r.status_code, (401, 403))

    def test_support_cannot_create_type(self):
        support = make_user("it_support")
        r = api_client(support).post(
            "/api/cmdb/types/", {"name": "Router", "code": "ROUTER"},
        )
        self.assertEqual(r.status_code, 403)

    def test_manager_can_create_type(self):
        manager = make_user("it_manager")
        r = api_client(manager).post(
            "/api/cmdb/types/",
            {"name": "Firewall", "code": "FIREWALL", "category": "network"},
        )
        self.assertEqual(r.status_code, 201)

    def test_types_expose_ci_count(self):
        ctype = ConfigurationItemType.objects.create(
            name="Switch", code="SWITCH", category="network",
        )
        ConfigurationItem.objects.create(name="sw1", ci_type=ctype)
        r = self.client.get("/api/cmdb/types/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)
        row = next(t for t in r.data if t["id"] == ctype.id)
        self.assertIn("ci_count", row)
        self.assertEqual(row["ci_count"], 1)


class CMDBItemTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )

    def test_create_item_numbering(self):
        r = self.client.post(
            "/api/cmdb/items/",
            {"name": "CI1", "ci_type": self.type.id, "status": "active"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["ci_number"].startswith("CI-"))
        self.assertEqual(r.data["record_version"], 1)

    def test_employee_denied(self):
        emp = make_user("employee")
        r = api_client(emp).get("/api/cmdb/items/")
        self.assertIn(r.status_code, (401, 403))

    def test_verify(self):
        data = create_ci(self.client, "CI2", self.type)
        r = self.client.post(
            f"/api/cmdb/items/{data['id']}/verify/",
            {"expected_record_version": data["record_version"]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data["last_verified_at"])
        self.assertEqual(r.data["verification_status"], "verified")

    def test_verify_stale_version_409(self):
        data = create_ci(self.client, "CI-stale", self.type)
        r = self.client.post(
            f"/api/cmdb/items/{data['id']}/verify/",
            {"expected_record_version": data["record_version"] + 99},
            format="json",
        )
        self.assertEqual(r.status_code, 409)

    def test_verify_without_trailing_slash(self):
        data = create_ci(self.client, "CI-noslash", self.type)
        r = self.client.post(
            f"/api/cmdb/items/{data['id']}/verify",
            {"expected_record_version": data["record_version"]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)

    def test_patch_stale_version_409(self):
        data = create_ci(self.client, "CI-patch", self.type)
        r = self.client.patch(
            f"/api/cmdb/items/{data['id']}/",
            {"description": "x", "expected_record_version": 999},
            format="json",
        )
        self.assertEqual(r.status_code, 409)

    def test_retire_requires_reason(self):
        data = create_ci(self.client, "CI3", self.type)
        r = self.client.post(
            f"/api/cmdb/items/{data['id']}/retire/",
            {"expected_record_version": data["record_version"]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_retire_with_reason(self):
        data = create_ci(self.client, "CI4", self.type)
        r = self.client.post(
            f"/api/cmdb/items/{data['id']}/retire/",
            {"reason": "done", "expected_record_version":
             data["record_version"]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "retired")

    def test_retire_denied_for_support(self):
        support = make_user("it_support")
        data = create_ci(self.client, "CI5", self.type)
        r = api_client(support).post(
            f"/api/cmdb/items/{data['id']}/retire/", {"reason": "nope"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_support_cannot_change_ci_type(self):
        support = make_user("it_support")
        other = ConfigurationItemType.objects.create(
            name="Database", code="DATABASE", category="database",
        )
        data = create_ci(api_client(support), "sup-ci", self.type)
        r = api_client(support).patch(
            f"/api/cmdb/items/{data['id']}/",
            {"ci_type": other.id},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_detail_includes_history(self):
        data = create_ci(self.client, "CI6", self.type)
        r = self.client.get(f"/api/cmdb/items/{data['id']}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("history", r.data)
        self.assertIsInstance(r.data["history"], list)
        self.assertGreaterEqual(len(r.data["history"]), 1)

    def test_history_action_array(self):
        data = create_ci(self.client, "CI7", self.type)
        r = self.client.get(f"/api/cmdb/items/{data['id']}/history/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)

    def test_items_list_plain_array_and_paginated(self):
        create_ci(self.client, "CI8", self.type)
        plain = self.client.get("/api/cmdb/items/")
        self.assertEqual(plain.status_code, 200)
        self.assertIsInstance(plain.data, list)

        paged = self.client.get("/api/cmdb/items/?page=1")
        self.assertEqual(paged.status_code, 200)
        self.assertIn("count", paged.data)
        self.assertIn("results", paged.data)
        self.assertIsInstance(paged.data["results"], list)

    def test_items_list_without_slash(self):
        r = self.client.get("/api/cmdb/items")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)

    def test_hostname_normalized(self):
        r = self.client.post(
            "/api/cmdb/items/",
            {"name": "web", "ci_type": self.type.id,
             "hostname": "WEB01.Example.COM."},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["hostname"], "web01.example.com")


class CMDBRelationshipTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.a = create_ci(self.client, "A", self.type)["id"]
        self.b = create_ci(self.client, "B", self.type)["id"]

    def test_create_relationship(self):
        r = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], "active")

    def test_self_reference_rejected(self):
        r = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.a,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_duplicate_rejected(self):
        payload = {"source_ci": self.a, "target_ci": self.b,
                   "relationship_type": "depends_on"}
        self.client.post("/api/cmdb/relationships/", payload, format="json")
        r = self.client.post("/api/cmdb/relationships/", payload,
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_support_create_forced_proposed(self):
        support = make_user("it_support")
        r = api_client(support).post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "depends_on", "status": "proposed"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], "proposed")

    def test_support_cannot_create_active(self):
        support = make_user("it_support")
        r = api_client(support).post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "depends_on", "status": "active"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_hierarchy_cycle_rejected(self):
        r1 = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "contains"},
            format="json",
        )
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.b, "target_ci": self.a,
             "relationship_type": "contains"},
            format="json",
        )
        self.assertEqual(r2.status_code, 400)

    def test_employee_denied(self):
        emp = make_user("employee")
        r = api_client(emp).post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertIn(r.status_code, (401, 403))

    def test_relationships_list_plain_array(self):
        r = self.client.get("/api/cmdb/relationships/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)

    def test_manager_activates_support_proposal(self):
        support = make_user("it_support")
        created = api_client(support).post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        rel_id = created.data["id"]

        denied = api_client(support).post(
            f"/api/cmdb/relationships/{rel_id}/activate/", {}, format="json",
        )
        self.assertEqual(denied.status_code, 403)

        activated = self.client.post(
            f"/api/cmdb/relationships/{rel_id}/activate/", {}, format="json",
        )
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(activated.data["status"], "active")


class CMDBImpactTests(TestCase):
    """Impact/dependency orientation: affected CIs are dependents.

    `B depends_on A` means B breaks when A breaks -> impact(A) contains B.
    """

    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.a = create_ci(self.client, "A", self.type)["id"]
        self.b = create_ci(self.client, "B", self.type)["id"]
        r = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.b, "target_ci": self.a,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_impact_direction(self):
        impact_a = self.client.get(f"/api/cmdb/items/{self.a}/impact/")
        self.assertEqual(impact_a.status_code, 200)
        self.assertIn(self.b, impact_a.data["affected_ci_ids"])
        self.assertEqual(impact_a.data["affected_count"], 1)

        impact_b = self.client.get(f"/api/cmdb/items/{self.b}/impact/")
        self.assertEqual(impact_b.status_code, 200)
        self.assertNotIn(self.a, impact_b.data["affected_ci_ids"])
        self.assertEqual(impact_b.data["affected_count"], 0)

    def test_impact_payload_shape(self):
        r = self.client.get(
            f"/api/cmdb/items/{self.a}/impact/?proposed_status=retired",
        )
        self.assertEqual(r.status_code, 200)
        for key in (
            "id", "ci_number", "name", "status", "affected_ci_ids",
            "affected_count", "affected_services", "affected_departments",
            "affected_owners", "critical_dependencies",
            "single_points_of_failure", "affected_tickets", "affected_changes",
            "risk_summary", "truncated", "warning", "record_version",
        ):
            self.assertIn(key, r.data)
        self.assertIn("retired", r.data["risk_summary"])

    def test_dependencies_graph_shape(self):
        r = self.client.get(f"/api/cmdb/items/{self.a}/dependencies/")
        self.assertEqual(r.status_code, 200)
        for key in ("nodes", "edges", "nodeCount", "edgeCount",
                    "cycleIndicator", "truncated", "max_depth", "view"):
            self.assertIn(key, r.data)
        self.assertEqual(r.data["nodeCount"], 2)
        self.assertIsNone(r.data["cycleIndicator"])
        node_a = next(n for n in r.data["nodes"] if n["id"] == self.a)
        self.assertEqual(node_a["type"], "Server")
        self.assertEqual(node_a["ci_type"], "Server")
        edge = r.data["edges"][0]
        for key in ("id", "source", "target", "relationship_type", "status",
                    "confidence", "source_ci_number", "target_ci_number"):
            self.assertIn(key, edge)

    def test_graph_view_filters_direction(self):
        downstream = self.client.get(
            f"/api/cmdb/items/{self.a}/dependencies/?view=downstream",
        )
        self.assertEqual(downstream.data["view"], "downstream")
        self.assertEqual(
            sorted(n["id"] for n in downstream.data["nodes"]),
            sorted([self.a, self.b]),
        )

        upstream = self.client.get(
            f"/api/cmdb/items/{self.a}/dependencies/?view=upstream",
        )
        self.assertEqual(upstream.data["view"], "upstream")
        self.assertEqual([n["id"] for n in upstream.data["nodes"]], [self.a])

    def test_cycle_indicator(self):
        r = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.a, "target_ci": self.b,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        graph = self.client.get(f"/api/cmdb/items/{self.a}/dependencies/")
        self.assertEqual(graph.data["cycleIndicator"], "cycle")

    def test_depth_clamped(self):
        r = self.client.get(
            f"/api/cmdb/items/{self.a}/dependencies/?depth=999",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["max_depth"], 10)

    def test_dependency_without_slash(self):
        r = self.client.get(f"/api/cmdb/items/{self.a}/dependencies")
        self.assertEqual(r.status_code, 200)
        self.assertIn("nodes", r.data)


class CMDBBaselineDriftTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.manager = make_user("it_manager")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        ci = create_ci(
            self.client, "CI", self.type, status="active",
            criticality="critical",
        )
        self.ci_id = ci["id"]
        self.ci = ConfigurationItem.objects.get(id=self.ci_id)

    def _create_baseline(self, name="BL1"):
        r = self.client.post(
            "/api/cmdb/baselines/",
            {"name": name, "scope_type": "single_ci",
             "configuration_items": [self.ci_id]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_create_baseline(self):
        data = self._create_baseline()
        self.assertTrue(data["checksum"])
        self.assertTrue(data["code"].startswith("BL-"))
        self.assertEqual(data["status"], "draft")
        self.assertIn("cis", data["snapshot"])

    def test_baseline_self_approval_denied(self):
        data = self._create_baseline("BL2")
        r = self.client.post(
            f"/api/cmdb/baselines/{data['id']}/approve/", {}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_submit_then_other_manager_approves(self):
        data = self._create_baseline("BL3")
        submitted = self.client.post(
            f"/api/cmdb/baselines/{data['id']}/submit/", {}, format="json",
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["status"], "pending_approval")

        approved = api_client(self.manager).post(
            f"/api/cmdb/baselines/{data['id']}/approve/", {}, format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data["status"], "approved")
        self.assertEqual(approved.data["approved_by"], self.manager.id)

    def test_same_name_baseline_supersedes(self):
        first = self._create_baseline("BL-same")
        api_client(self.manager).post(
            f"/api/cmdb/baselines/{first['id']}/approve/", {}, format="json",
        )
        second = self._create_baseline("BL-same")
        other_manager = make_user("it_manager")
        api_client(other_manager).post(
            f"/api/cmdb/baselines/{second['id']}/approve/", {}, format="json",
        )
        from cmdb.models import ConfigurationBaseline
        first_obj = ConfigurationBaseline.objects.get(id=first["id"])
        second_obj = ConfigurationBaseline.objects.get(id=second["id"])
        self.assertEqual(first_obj.status, "superseded")
        self.assertEqual(second_obj.status, "approved")

    def test_compare_and_drift_evaluation(self):
        data = self._create_baseline("BL4")
        api_client(self.manager).post(
            f"/api/cmdb/baselines/{data['id']}/approve/", {}, format="json",
        )
        self.ci.refresh_from_db()
        baseline = self.ci.baselines.filter(status="approved").first()
        self.assertIsNotNone(baseline)

        self.ci.name = "CI-renamed"
        self.ci.save(update_fields=["name", "updated_at"])

        compare = self.client.get(
            f"/api/cmdb/items/{self.ci_id}/compare-baseline/",
        )
        self.assertEqual(compare.status_code, 200)
        self.assertTrue(compare.data["drift"])
        self.assertGreaterEqual(len(compare.data["diffs"]), 1)

        findings = evaluate_configuration_drift(self.ci, baseline=baseline)
        self.assertGreaterEqual(len(findings), 1)
        open_count = ConfigurationDriftFinding.objects.filter(
            configuration_item=self.ci, status="open",
        ).count()
        self.assertGreaterEqual(open_count, 1)

        # idempotent: re-evaluation does not duplicate findings
        evaluate_configuration_drift(self.ci, baseline=baseline)
        self.assertEqual(
            ConfigurationDriftFinding.objects.filter(
                configuration_item=self.ci, is_deleted=False,
            ).count(),
            open_count,
        )

    def test_drift_masks_ip_address(self):
        self.ci.ip_address = "10.0.0.1"
        self.ci.save(update_fields=["ip_address", "updated_at"])
        data = self._create_baseline("BL-mask")
        api_client(self.manager).post(
            f"/api/cmdb/baselines/{data['id']}/approve/", {}, format="json",
        )
        self.ci.refresh_from_db()
        baseline = self.ci.baselines.filter(status="approved").first()

        self.ci.ip_address = "10.0.0.2"
        self.ci.save(update_fields=["ip_address", "updated_at"])
        findings = evaluate_configuration_drift(self.ci, baseline=baseline)
        ip_findings = [f for f in findings if f.field_name == "ip_address"]
        self.assertGreaterEqual(len(ip_findings), 1)
        self.assertEqual(ip_findings[0].expected_value, "[masked]")
        self.assertEqual(ip_findings[0].actual_value, "[masked]")

    def test_drift_list_filters(self):
        ConfigurationDriftFinding.objects.create(
            configuration_item=self.ci,
            finding_type="status_changed",
            severity="high",
            status="open",
            fingerprint="f" * 64,
            field_name="status",
        )
        r = self.client.get("/api/cmdb/drift/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)
        self.assertEqual(len(r.data), 1)

        filtered = self.client.get(
            f"/api/cmdb/drift/?ci={self.ci_id}&status=open",
        )
        self.assertEqual(len(filtered.data), 1)

        wrong = self.client.get(f"/api/cmdb/drift/?ci={self.ci_id + 999}")
        self.assertEqual(len(wrong.data), 0)

    def test_drift_create_update_delete_blocked(self):
        r = self.client.post("/api/cmdb/drift/", {}, format="json")
        self.assertEqual(r.status_code, 405)

    def _finding(self, severity="high"):
        return ConfigurationDriftFinding.objects.create(
            configuration_item=self.ci,
            finding_type="status_changed",
            severity=severity,
            status="open",
            fingerprint="a" * 64,
            field_name="status",
            expected_value="active",
            actual_value="maintenance",
        )

    def test_drift_workflow_actions(self):
        support = make_user("it_support")
        finding = self._finding()

        ack = api_client(support).post(
            f"/api/cmdb/drift/{finding.id}/acknowledge/", {}, format="json",
        )
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.data["status"], "acknowledged")

        denied = api_client(support).post(
            f"/api/cmdb/drift/{finding.id}/resolve/",
            {"note": "fixing"}, format="json",
        )
        self.assertEqual(denied.status_code, 403)

        resolved = self.client.post(
            f"/api/cmdb/drift/{finding.id}/resolve/",
            {"note": "fixed it"}, format="json",
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.data["status"], "resolved")

    def test_critical_accept_admin_only(self):
        finding = self._finding(severity="critical")
        manager_accept = api_client(self.manager).post(
            f"/api/cmdb/drift/{finding.id}/accept/", {}, format="json",
        )
        self.assertEqual(manager_accept.status_code, 403)

        admin_accept = self.client.post(
            f"/api/cmdb/drift/{finding.id}/accept/", {}, format="json",
        )
        self.assertEqual(admin_accept.status_code, 200)
        self.assertEqual(admin_accept.data["status"], "accepted")

    def test_false_positive_requires_note(self):
        finding = self._finding()
        r = self.client.post(
            f"/api/cmdb/drift/{finding.id}/false-positive/", {},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        r2 = self.client.post(
            f"/api/cmdb/drift/{finding.id}/false-positive/",
            {"note": "known change"}, format="json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["status"], "false_positive")


class CMDBDashboardReportTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        create_ci(self.client, "dash-ci", self.type, status="active",
                  criticality="critical")

    def test_dashboard(self):
        r = self.client.get("/api/cmdb/dashboard/")
        self.assertEqual(r.status_code, 200)
        for key in ("total_cis", "active_cis", "critical_cis",
                    "unverified_cis", "open_drift_findings", "generated_at"):
            self.assertIn(key, r.data)
        self.assertEqual(r.data["total_cis"], 1)
        self.assertEqual(r.data["critical_cis"], 1)

    def test_dashboard_without_slash(self):
        r = self.client.get("/api/cmdb/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertIn("total_cis", r.data)

    def test_reports_coverage(self):
        r = self.client.get("/api/cmdb/reports/?kind=coverage")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kind"], "coverage")
        self.assertIsInstance(r.data["rows"], list)
        self.assertGreaterEqual(len(r.data["rows"]), 1)
        self.assertIn("columns", r.data)
        self.assertIn("summary", r.data)
        self.assertIn("generated_at", r.data)
        self.assertIn("total", r.data["summary"])

    def test_reports_kind_path_without_slash(self):
        r = self.client.get("/api/cmdb/reports/verification_age")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kind"], "verification_age")

    def test_reports_unknown_kind_falls_back(self):
        r = self.client.get("/api/cmdb/reports/?kind=nope")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kind"], "coverage")

    def test_verification_queue_roundtrip(self):
        r = self.client.get("/api/cmdb/verification/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)
        queued_ids = [row["ci_id"] for row in r.data]
        ci_id = queued_ids[0] if queued_ids else None

        ci = ConfigurationItem.objects.filter(is_deleted=False).first()
        self.assertIsNotNone(ci)
        verify = self.client.post(
            f"/api/cmdb/verification/{ci.id}/verify", {}, format="json",
        )
        self.assertEqual(verify.status_code, 200)
        self.assertEqual(verify.data["verification_status"], "verified")

        after = self.client.get("/api/cmdb/verification/")
        self.assertNotIn(ci.id, [row["ci_id"] for row in after.data])
        if ci_id:
            self.assertNotIn(ci_id, [row["ci_id"] for row in after.data])


class CMDBServiceMappingTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.ci_data = create_ci(self.client, "svc-ci", self.type,
                                 status="active")
        self.service = ServiceCatalogueItem.objects.create(name="Email")

    def _link(self, ci_id, redundancy_group="", is_required=True):
        return self.client.post(
            "/api/cmdb/service-links/",
            {"service": self.service.id, "configuration_item": ci_id,
             "role": "primary", "is_required": is_required,
             "redundancy_group": redundancy_group},
            format="json",
        )

    def test_service_profile_and_link(self):
        profile = self.client.post(
            "/api/cmdb/service-profiles/",
            {"service": self.service.id, "service_tier": "tier_1"},
            format="json",
        )
        self.assertEqual(profile.status_code, 201, profile.data)

        link = self._link(self.ci_data["id"])
        self.assertEqual(link.status_code, 201, link.data)

    def test_service_graph(self):
        self._link(self.ci_data["id"])
        r = self.client.get(f"/api/cmdb/services/{self.service.id}/graph/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("nodeCount", r.data)
        self.assertIn("edges", r.data)

    def test_service_impact(self):
        self._link(self.ci_data["id"])
        r = self.client.get(f"/api/cmdb/services/{self.service.id}/impact/")
        self.assertEqual(r.status_code, 200)
        for key in ("service_id", "linked_cis", "affected_cis",
                    "affected_count", "single_points_of_failure"):
            self.assertIn(key, r.data)

    def test_service_spof(self):
        self._link(self.ci_data["id"])
        r = self.client.get(
            f"/api/cmdb/services/{self.service.id}/single-points-of-failure/",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(
            r.data["single_points_of_failure"][0]["ci_id"],
            self.ci_data["id"],
        )

        # a redundancy peer removes the single point of failure
        other = create_ci(self.client, "svc-ci-2", self.type, status="active")
        second = self._link(other["id"], redundancy_group="rg1")
        self.assertEqual(second.status_code, 201, second.data)
        # move the first link into the same group
        link = self.service.cmdb_ci_links.filter(
            configuration_item_id=self.ci_data["id"],
        ).first()
        link.redundancy_group = "rg1"
        link.save(update_fields=["redundancy_group", "updated_at"])

        after = self.client.get(
            f"/api/cmdb/services/{self.service.id}/single-points-of-failure/",
        )
        self.assertEqual(after.data["count"], 0)


class CMDBAssetSyncTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        from accounts.models import Department
        from assets.models import Asset, AssetCategory

        cat = AssetCategory.objects.create(name="LaptopCat")
        dept = Department.objects.create(name="IT", code="IT")
        self.asset = Asset.objects.create(
            name="Laptop1", asset_tag="LT1", category=cat, department=dept,
            status="available",
        )

    def test_sync_asset_idempotent(self):
        ci, created = sync_asset_to_ci(self.asset, actor=self.admin)
        self.assertTrue(created)
        self.assertEqual(ci.asset_id, self.asset.id)
        self.assertEqual(ci.source, "asset_sync")
        self.assertEqual(ci.status, "planned")

        ci2, created2 = sync_asset_to_ci(self.asset, actor=self.admin)
        self.assertFalse(created2)
        self.assertEqual(ci.id, ci2.id)

    def test_manual_ci_preserved(self):
        ci_type = ConfigurationItemType.objects.create(
            name="Laptop", code="LAPTOP", category="hardware",
        )
        manual = create_ci(
            self.client, "manual-ci", ci_type, asset=self.asset.id,
        )
        ci = ConfigurationItem.objects.get(id=manual["id"])
        synced, created = sync_asset_to_ci(self.asset, actor=self.admin)
        self.assertFalse(created)
        self.assertEqual(synced.id, ci.id)
        synced.refresh_from_db()
        self.assertEqual(synced.name, "manual-ci")
        self.assertEqual(synced.source, "manual")

    def test_asset_assigned_status_maps_on_create(self):
        from accounts.models import Department
        from assets.models import Asset, AssetCategory

        cat = AssetCategory.objects.create(name="Laptops")
        dept = Department.objects.create(name="Ops", code="OPS")
        holder = make_user("employee", suffix="asg")
        asset = Asset.objects.create(
            name="assigned-laptop", asset_tag="LT-ASG", category=cat,
            department=dept, status="assigned", assigned_to=holder,
        )
        ci, created = sync_asset_to_ci(asset, actor=self.admin)
        self.assertTrue(created)
        self.assertEqual(ci.status, "active")


class CMDBRetireImpactTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.a = create_ci(self.client, "A", self.type, status="active")
        self.b = create_ci(self.client, "B", self.type, status="active")
        r = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.b["id"], "target_ci": self.a["id"],
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.rel_id = r.data["id"]

    def test_retire_blocked_by_impact_then_acknowledged(self):
        blocked = self.client.post(
            f"/api/cmdb/items/{self.a['id']}/retire/",
            {"reason": "decommission",
             "expected_record_version": self.a["record_version"]},
            format="json",
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("affected_count", blocked.data)
        self.assertGreaterEqual(blocked.data["affected_count"], 1)

        acknowledged = self.client.post(
            f"/api/cmdb/items/{self.a['id']}/retire/",
            {"reason": "decommission",
             "expected_record_version": self.a["record_version"],
             "acknowledge_impact": True},
            format="json",
        )
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(acknowledged.data["status"], "retired")

        rel = ConfigurationItemRelationship.objects.get(id=self.rel_id)
        self.assertEqual(rel.status, "inactive")

    def test_retire_replacement_links_replaces(self):
        replacement = create_ci(self.client, "A2", self.type, status="active")
        r = self.client.post(
            f"/api/cmdb/items/{self.a['id']}/retire/",
            {"reason": "replace", "acknowledge_impact": True,
             "expected_record_version": self.a["record_version"],
             "replacement_ci": replacement["id"]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        rel = ConfigurationItemRelationship.objects.filter(
            relationship_type="replaces", is_deleted=False,
        ).first()
        self.assertIsNotNone(rel)
        self.assertEqual(rel.source_ci_id, replacement["id"])
        self.assertEqual(rel.target_ci_id, self.a["id"])

    def test_retire_assigned_asset_blocked(self):
        from accounts.models import Department
        from assets.models import Asset, AssetCategory

        cat = AssetCategory.objects.create(name="Monitors")
        dept = Department.objects.create(name="Field", code="FLD")
        holder = make_user("employee", suffix="mon")
        asset = Asset.objects.create(
            name="mon", asset_tag="MON1", category=cat, department=dept,
            status="assigned", assigned_to=holder,
        )
        ci_data = create_ci(
            self.client, "asset-ci", self.type, asset=asset.id,
        )
        r = self.client.post(
            f"/api/cmdb/items/{ci_data['id']}/retire/",
            {"reason": "broken"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
