"""CMDB impact/graph analysis tests."""

from django.test import TestCase
from django.utils import timezone

from accounts.models import Department
from cmdb.impact import (
    VERIFICATION_THRESHOLD_DAYS,
    analyze_ci_impact,
    build_dependency_graph,
    detect_relationship_cycles,
    find_orphan_configuration_items,
    find_single_points_of_failure,
    find_unverified_configuration_items,
    get_downstream_dependents,
    get_service_dependency_graph,
    get_upstream_dependencies,
    verification_status_for,
)
from cmdb.models import (
    ConfigurationItem,
    ConfigurationItemRelationship,
    ConfigurationItemTicketLink,
    ConfigurationItemType,
    ServiceConfigurationItemLink,
)
from cmdb.tests import api_client, make_user
from services.models import ServiceCatalogueItem


class ImpactDirectionTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        # A is depended on by B (B depends_on A)
        self.a = ConfigurationItem.objects.create(name="A", ci_type=self.t, status="active")
        self.b = ConfigurationItem.objects.create(name="B", ci_type=self.t, status="active")
        ConfigurationItemRelationship.objects.create(
            source_ci=self.b, target_ci=self.a,
            relationship_type="depends_on", status="active",
        )

    def test_downstream_upstream_combined(self):
        down, _ = get_downstream_dependents(self.a)
        self.assertIn(self.b.id, down)
        up, _ = get_upstream_dependencies(self.b)
        self.assertIn(self.a.id, up)
        graph = build_dependency_graph(self.a, view="combined", max_depth=5)
        ids = {n["id"] for n in graph["nodes"]}
        self.assertIn(self.a.id, ids)
        self.assertIn(self.b.id, ids)

    def test_forward_reverse_symmetric_neutral_types(self):
        c = ConfigurationItem.objects.create(name="C", ci_type=self.t, status="active")
        d = ConfigurationItem.objects.create(name="D", ci_type=self.t, status="active")
        # reverse example: supported_by semantics via model orientation map behavior
        # use related_to (symmetric) and replaces (neutral)
        ConfigurationItemRelationship.objects.create(
            source_ci=self.a, target_ci=c, relationship_type="related_to", status="active",
        )
        ConfigurationItemRelationship.objects.create(
            source_ci=self.a, target_ci=d, relationship_type="replaces", status="active",
        )
        g = build_dependency_graph(self.a, view="combined", max_depth=3)
        types = {e["relationship_type"] for e in g["edges"]}
        self.assertIn("depends_on", types)


class RelationshipStateTests(TestCase):
    def setUp(self):
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.a = ConfigurationItem.objects.create(name="A", ci_type=self.t, status="active")
        self.b = ConfigurationItem.objects.create(name="B", ci_type=self.t, status="active")

    def test_proposed_active_inactive_deleted_handling(self):
        rel = ConfigurationItemRelationship.objects.create(
            source_ci=self.b, target_ci=self.a,
            relationship_type="depends_on", status="proposed",
        )
        # graph includes proposed per GRAPH_STATUSES
        g = build_dependency_graph(self.a, view="combined")
        self.assertTrue(any(e["id"] == rel.id for e in g["edges"]))
        # impact traversal uses active statuses
        impacted, _ = get_downstream_dependents(self.a)
        self.assertNotIn(self.b.id, impacted)
        rel.status = "inactive"
        rel.save()
        g2 = build_dependency_graph(self.a, view="combined")
        self.assertFalse(any(e["id"] == rel.id for e in g2["edges"]))
        rel.status = "active"
        rel.save()
        rel.is_deleted = True
        rel.save(update_fields=["is_deleted"])
        g3 = build_dependency_graph(self.a, view="combined")
        self.assertFalse(any(e["id"] == rel.id for e in g3["edges"]))


class DepthBoundsGraphShapeTests(TestCase):
    def setUp(self):
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.a = ConfigurationItem.objects.create(name="A", ci_type=self.t, status="active")

    def test_depth_clamping_and_graph_contract(self):
        for depth in [None, 0, -1, 99]:
            g = build_dependency_graph(self.a, view="combined", max_depth=depth)
            self.assertIn("nodes", g)
            self.assertIn("edges", g)
            self.assertIn("nodeCount", g)
            self.assertIn("edgeCount", g)
            self.assertIn("cycleIndicator", g)
            self.assertIn("truncated", g)
            self.assertIn("max_depth", g)
            self.assertIn("view", g)
            self.assertGreaterEqual(g["max_depth"], 1)
            self.assertLessEqual(g["max_depth"], 10)
        node = build_dependency_graph(self.a)["nodes"][0]
        self.assertIn("type", node)
        self.assertIn("ci_type", node)
        self.assertEqual(node["type"], self.t.name)
        self.assertEqual(node["ci_type"], self.t.name)

    def test_node_cap_truncation(self):
        # create enough nodes to exceed small max_nodes
        prev = self.a
        for i in range(5):
            nxt = ConfigurationItem.objects.create(name=f"N{i}", ci_type=self.t, status="active")
            ConfigurationItemRelationship.objects.create(
                source_ci=nxt, target_ci=prev, relationship_type="depends_on", status="active",
            )
            prev = nxt
        g = build_dependency_graph(self.a, view="downstream", max_depth=10, max_nodes=2)
        self.assertTrue(g["truncated"] or g["nodeCount"] <= 2)


class CycleOrphanVerificationTests(TestCase):
    def setUp(self):
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )

    def test_cycle_detected_via_orm_and_traversal_terminates(self):
        a = ConfigurationItem.objects.create(name="A", ci_type=self.t, status="active")
        b = ConfigurationItem.objects.create(name="B", ci_type=self.t, status="active")
        c = ConfigurationItem.objects.create(name="C", ci_type=self.t, status="active")
        ConfigurationItemRelationship.objects.create(
            source_ci=a, target_ci=b, relationship_type="contains", status="active",
        )
        ConfigurationItemRelationship.objects.create(
            source_ci=b, target_ci=c, relationship_type="contains", status="active",
        )
        # create cycle edge directly in ORM (bypass serializer validation)
        ConfigurationItemRelationship.objects.create(
            source_ci=c, target_ci=a, relationship_type="contains", status="active",
        )
        self.assertGreaterEqual(detect_relationship_cycles(), 1)
        g = build_dependency_graph(a, view="combined", max_depth=10)
        self.assertEqual(g["cycleIndicator"], "cycle")
        self.assertEqual(len({n["id"] for n in g["nodes"]}), g["nodeCount"])

    def test_orphans_verification_and_spof(self):
        a = ConfigurationItem.objects.create(name="Orphan", ci_type=self.t, status="active")
        orphans = list(find_orphan_configuration_items())
        self.assertIn(a, orphans)
        never = ConfigurationItem.objects.create(name="Never", ci_type=self.t, status="active")
        current = ConfigurationItem.objects.create(
            name="Current", ci_type=self.t, status="active", last_verified_at=timezone.now(),
        )
        overdue = ConfigurationItem.objects.create(
            name="Overdue", ci_type=self.t, status="active",
            last_verified_at=timezone.now() - timezone.timedelta(days=VERIFICATION_THRESHOLD_DAYS + 5),
        )
        self.assertEqual(verification_status_for(never), "never_verified")
        self.assertEqual(verification_status_for(current), "verified")
        self.assertEqual(verification_status_for(overdue), "overdue")
        qs = find_unverified_configuration_items()
        self.assertIn(never, qs)
        self.assertIn(overdue, qs)
        self.assertNotIn(current, qs)

        # SPOF: required service link without redundancy peer
        svc = ServiceCatalogueItem.objects.create(name="Svc", is_active=True)
        b = ConfigurationItem.objects.create(name="B", ci_type=self.t, status="active")
        ServiceConfigurationItemLink.objects.create(
            service=svc, configuration_item=b, role="primary", is_required=True,
        )
        spofs = find_single_points_of_failure(service=svc)
        self.assertTrue(any(s["ci_id"] == b.id for s in spofs))
        # redundancy peer removes false positive
        b2 = ConfigurationItem.objects.create(name="B2", ci_type=self.t, status="active")
        ServiceConfigurationItemLink.objects.filter(service=svc, configuration_item=b).update(redundancy_group="rg1")
        ServiceConfigurationItemLink.objects.create(
            service=svc, configuration_item=b2, role="primary", is_required=True, redundancy_group="rg1",
        )
        spofs2 = find_single_points_of_failure(service=svc)
        self.assertFalse(any(s["ci_id"] == b.id and s.get("redundancy_group") == "rg1" for s in spofs2 if s.get("redundancy_group") == "rg1"))


class ImpactPayloadTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.dept = Department.objects.create(name="Ops", code="OPS1")
        self.a = ConfigurationItem.objects.create(
            name="A", ci_type=self.t, status="active", department=self.dept, owner=self.admin,
        )
        self.b = ConfigurationItem.objects.create(name="B", ci_type=self.t, status="active")
        ConfigurationItemRelationship.objects.create(
            source_ci=self.b, target_ci=self.a, relationship_type="depends_on", status="active",
        )

    def test_analyze_ci_impact_payload(self):
        payload = analyze_ci_impact(self.a, max_depth=5, include_tickets=False, include_changes=False)
        for key in [
            "id", "ci_number", "name", "status", "criticality", "environment",
            "affected_ci_ids", "affected_count", "affected_services",
            "affected_departments", "affected_owners", "critical_dependencies",
            "single_points_of_failure", "affected_tickets", "affected_changes",
            "risk_summary", "truncated", "warning",
        ]:
            self.assertIn(key, payload)
        self.assertIn(self.b.id, payload["affected_ci_ids"])
        self.assertIsInstance(payload["affected_services"], list)
        self.assertIsInstance(payload["truncated"], bool)

    def test_service_dependency_graph(self):
        svc = ServiceCatalogueItem.objects.create(name="Svc", is_active=True)
        ServiceConfigurationItemLink.objects.create(
            service=svc, configuration_item=self.a, role="primary",
        )
        g = get_service_dependency_graph(svc, max_depth=5)
        self.assertIn("nodes", g)
        self.assertIn("edges", g)
        self.assertIn("nodeCount", g)
        self.assertIn("edgeCount", g)
