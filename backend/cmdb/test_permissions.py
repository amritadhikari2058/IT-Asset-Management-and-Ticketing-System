"""CMDB permission tests (executable)."""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory
from cmdb.models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemRelationship,
    ConfigurationItemType,
)
from cmdb.tests import api_client, create_ci, make_user
from services.models import ServiceCatalogueItem


def _force_obj_deleted(obj):
    # Bypass model delete guards where needed for scope/exclusion tests.
    type(obj).objects.filter(pk=obj.pk).update(is_deleted=True)
    obj.refresh_from_db()


class CMDBPermissionBase(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.manager = make_user("it_manager")
        self.support = make_user("it_support")
        self.employee = make_user("employee")
        self.anon = APIClient()
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.ci = ConfigurationItem.objects.create(
            name="CI-1", ci_type=self.ci_type, status="active",
            source="manual", created_by=self.admin,
        )

    def _baseline(self, creator=None):
        creator = creator or self.admin
        baseline = ConfigurationBaseline.objects.create(
            name=f"BL-{ConfigurationBaseline.objects.count()+1}",
            scope_type="single_ci", status="draft", created_by=creator,
            snapshot={"cis": {}}, checksum="x",
        )
        baseline.configuration_items.add(self.ci)
        return baseline

    def _drift(self, severity="medium", status="open"):
        return ConfigurationDriftFinding.objects.create(
            configuration_item=self.ci,
            finding_type="field_changed",
            severity=severity,
            status=status,
            field_name="name",
            expected_value="a",
            actual_value="b",
            source="test",
        )


class AnonymousDeniedTests(CMDBPermissionBase):
    def test_anonymous_denied(self):
        endpoints = [
            ("get", "/api/cmdb/items/"),
            ("get", f"/api/cmdb/items/{self.ci.id}/"),
            ("get", "/api/cmdb/dashboard/"),
            ("get", "/api/cmdb/reports/"),
            ("get", "/api/cmdb/verification/"),
        ]
        for method, url in endpoints:
            with self.subTest(method=method, url=url):
                resp = getattr(self.anon, method)(url)
                self.assertIn(resp.status_code, (401, 403))


class EmployeeDeniedTests(CMDBPermissionBase):
    def setUp(self):
        super().setUp()
        self.client = api_client(self.employee)

    def test_employee_read_denied_everywhere(self):
        ServiceCatalogueItem.objects.create(name="Svc", is_active=True)
        self._baseline()
        target = ConfigurationItem.objects.create(
            name="CI-2", ci_type=self.ci_type, status="active", source="manual",
        )
        ConfigurationItemRelationship.objects.create(
            source_ci=self.ci, target_ci=target,
            relationship_type="depends_on", status="proposed",
        )
        self._drift()
        urls = [
            "/api/cmdb/items/",
            f"/api/cmdb/items/{self.ci.id}/",
            "/api/cmdb/types/",
            "/api/cmdb/relationships/",
            "/api/cmdb/service-links/",
            "/api/cmdb/baselines/",
            "/api/cmdb/drift/",
            "/api/cmdb/dashboard/",
            "/api/cmdb/reports/",
            "/api/cmdb/verification/",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_employee_post_drift_returns_403_before_405(self):
        finding = self._drift()
        resp = self.client.post(f"/api/cmdb/drift/{finding.id}/acknowledge/", {})
        self.assertEqual(resp.status_code, 403)

    def test_employee_no_object_enumeration(self):
        resp = self.client.get("/api/cmdb/items/")
        self.assertEqual(resp.status_code, 403)


class UnknownAndInactiveTests(CMDBPermissionBase):
    def test_unknown_role_denied(self):
        user = make_user("employee", suffix="unk")
        user.role = "mystery_role"
        user.save(update_fields=["role"])
        client = api_client(user)
        self.assertIn(client.get("/api/cmdb/items/").status_code, (401, 403))
        self.assertIn(client.get("/api/cmdb/dashboard/").status_code, (401, 403))

    def test_inactive_user_denied_regardless_of_role(self):
        for role in ("system_admin", "it_manager", "it_support"):
            with self.subTest(role=role):
                user = make_user(role, suffix=f"inactive-{role}")
                user.is_active = False
                user.save(update_fields=["is_active"])
                client = api_client(user)
                self.assertIn(client.get("/api/cmdb/items/").status_code, (401, 403))
                self.assertIn(client.get("/api/cmdb/dashboard/").status_code, (401, 403))


class ITSupportPermissionTests(CMDBPermissionBase):
    def setUp(self):
        super().setUp()
        self.client = api_client(self.support)

    def test_support_reads(self):
        for url in [
            "/api/cmdb/items/",
            "/api/cmdb/types/",
            "/api/cmdb/relationships/",
            "/api/cmdb/dashboard/",
            f"/api/cmdb/items/{self.ci.id}/impact/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_support_create_manual_ci_forces_manual_source(self):
        resp = self.client.post(
            "/api/cmdb/items/",
            {"name": "Manual", "ci_type": self.ci_type.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["source"], "manual")

    def test_support_spoofed_asset_sync_source_rejected(self):
        resp = self.client.post(
            "/api/cmdb/items/",
            {"name": "Spoof", "ci_type": self.ci_type.id, "source": "asset_sync"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_support_operational_patch_succeeds(self):
        resp = self.client.patch(
            f"/api/cmdb/items/{self.ci.id}/",
            {"name": "Renamed", "location": "DC1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.ci.refresh_from_db()
        self.assertEqual(self.ci.name, "Renamed")

    def test_support_protected_field_patch_fails(self):
        other_type = ConfigurationItemType.objects.create(
            name="Laptop", code="LAPTOP", category="hardware",
        )
        protected_cases = [
            {"ci_type": other_type.id},
            {"source": "asset_sync"},
            {"source_identifier": "x"},
            {"external_reference": "x"},
        ]
        for payload in protected_cases:
            with self.subTest(payload=payload):
                resp = self.client.patch(
                    f"/api/cmdb/items/{self.ci.id}/", payload, format="json",
                )
                self.assertEqual(resp.status_code, 400)
        # created_by is serializer-read-only; protected means not user-settable.
        original_created_by = self.ci.created_by_id
        resp = self.client.patch(
            f"/api/cmdb/items/{self.ci.id}/",
            {"created_by": self.support.id},
            format="json",
        )
        self.assertIn(resp.status_code, (200, 400))
        self.ci.refresh_from_db()
        self.assertEqual(self.ci.created_by_id, original_created_by)

    def test_support_verify_succeeds(self):
        resp = self.client.post(
            f"/api/cmdb/items/{self.ci.id}/verify/",
            {"verification_note": "ok"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_support_retirement_denied(self):
        resp = self.client.post(
            f"/api/cmdb/items/{self.ci.id}/retire/",
            {"reason": "old"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_support_type_management_denied(self):
        self.assertEqual(self.client.get("/api/cmdb/types/").status_code, 200)
        resp = self.client.post(
            "/api/cmdb/types/",
            {"name": "NewType", "code": "NEWTYPE", "category": "hardware"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_support_baseline_create_and_approve_denied(self):
        create = self.client.post(
            "/api/cmdb/baselines/",
            {"name": "B", "scope_type": "single_ci", "configuration_items": [self.ci.id]},
            format="json",
        )
        self.assertEqual(create.status_code, 403)
        baseline = self._baseline()
        approve = self.client.post(
            f"/api/cmdb/baselines/{baseline.id}/approve/", {}, format="json",
        )
        self.assertEqual(approve.status_code, 403)

    def test_support_drift_ack_resolve_accept(self):
        finding = self._drift()
        ack = self.client.post(
            f"/api/cmdb/drift/{finding.id}/acknowledge/", {}, format="json",
        )
        self.assertEqual(ack.status_code, 200)
        finding2 = self._drift()
        resolve = self.client.post(
            f"/api/cmdb/drift/{finding2.id}/resolve/",
            {"note": "fixed"}, format="json",
        )
        self.assertEqual(resolve.status_code, 403)
        finding3 = self._drift()
        accept = self.client.post(
            f"/api/cmdb/drift/{finding3.id}/accept/", {}, format="json",
        )
        self.assertEqual(accept.status_code, 403)

    def test_support_critical_drift_accept_denied(self):
        finding = self._drift(severity="critical")
        resp = self.client.post(
            f"/api/cmdb/drift/{finding.id}/accept/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_support_relationship_proposed_only(self):
        target = ConfigurationItem.objects.create(
            name="CI-2", ci_type=self.ci_type, status="active", source="manual",
        )
        resp = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.ci.id, "target_ci": target.id,
             "relationship_type": "depends_on"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "proposed")
        target2 = ConfigurationItem.objects.create(
            name="CI-3", ci_type=self.ci_type, status="active", source="manual",
        )
        resp2 = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.ci.id, "target_ci": target2.id,
             "relationship_type": "depends_on", "status": "active"},
            format="json",
        )
        self.assertEqual(resp2.status_code, 400)

    def test_support_read_only_drift_method_405(self):
        finding = self._drift()
        resp = self.client.put(f"/api/cmdb/drift/{finding.id}/", {}, format="json")
        self.assertEqual(resp.status_code, 405)


class ManagerPermissionTests(CMDBPermissionBase):
    def setUp(self):
        super().setUp()
        self.client = api_client(self.manager)

    def test_manager_manage_ci_relationships_services(self):
        created = self.client.post(
            "/api/cmdb/items/", {"name": "M-CI", "ci_type": self.ci_type.id},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        target = ConfigurationItem.objects.create(
            name="T", ci_type=self.ci_type, status="active", source="manual",
        )
        rel = self.client.post(
            "/api/cmdb/relationships/",
            {"source_ci": self.ci.id, "target_ci": target.id,
             "relationship_type": "depends_on", "status": "active"},
            format="json",
        )
        self.assertEqual(rel.status_code, 201)
        svc = ServiceCatalogueItem.objects.create(name="Svc2", is_active=True)
        link = self.client.post(
            "/api/cmdb/service-links/",
            {"service": svc.id, "configuration_item": self.ci.id, "role": "primary"},
            format="json",
        )
        self.assertEqual(link.status_code, 201)

    def test_manager_baseline_create_and_approve_other_not_self(self):
        bl = self.client.post(
            "/api/cmdb/baselines/",
            {"name": "MBL", "scope_type": "single_ci",
             "configuration_items": [self.ci.id]},
            format="json",
        )
        self.assertEqual(bl.status_code, 201)
        own_approve = self.client.post(
            f"/api/cmdb/baselines/{bl.data['id']}/approve/", {}, format="json",
        )
        self.assertEqual(own_approve.status_code, 403)
        other_bl = self._baseline(creator=self.admin)
        other_approve = self.client.post(
            f"/api/cmdb/baselines/{other_bl.id}/approve/", {}, format="json",
        )
        self.assertEqual(other_approve.status_code, 200)

    def test_manager_drift_resolve_accept_noncritical_false_positive(self):
        finding = self._drift()
        resolve = self.client.post(
            f"/api/cmdb/drift/{finding.id}/resolve/",
            {"note": "done"}, format="json",
        )
        self.assertEqual(resolve.status_code, 200)
        finding2 = self._drift(severity="medium")
        accept = self.client.post(
            f"/api/cmdb/drift/{finding2.id}/accept/", {}, format="json",
        )
        self.assertEqual(accept.status_code, 200)
        finding3 = self._drift()
        fp = self.client.post(
            f"/api/cmdb/drift/{finding3.id}/false-positive/",
            {"note": "noise"}, format="json",
        )
        self.assertEqual(fp.status_code, 200)

    def test_manager_retire_noncritical_policy(self):
        ci = ConfigurationItem.objects.create(
            name="RetireMe", ci_type=self.ci_type, status="active",
            criticality="low", source="manual",
        )
        resp = self.client.post(
            f"/api/cmdb/items/{ci.id}/retire/",
            {"reason": "decom"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)


class SystemAdminPermissionTests(CMDBPermissionBase):
    def setUp(self):
        super().setUp()
        self.client = api_client(self.admin)

    def test_admin_type_management(self):
        resp = self.client.post(
            "/api/cmdb/types/",
            {"name": "AdminType", "code": "ADMINTYPE", "category": "hardware"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_admin_accepts_critical_drift(self):
        finding = self._drift(severity="critical")
        resp = self.client.post(
            f"/api/cmdb/drift/{finding.id}/accept/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_retire(self):
        resp = self.client.post(
            f"/api/cmdb/items/{self.ci.id}/retire/",
            {"reason": "gone"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_governance_routes_accessible(self):
        self.assertEqual(self.client.get("/api/cmdb/baselines/").status_code, 200)
        self.assertEqual(self.client.get("/api/cmdb/drift/").status_code, 200)
        self.assertEqual(self.client.get("/api/cmdb/verification/").status_code, 200)


class ObjectScopeExclusionTests(CMDBPermissionBase):
    def setUp(self):
        super().setUp()
        self.client = api_client(self.manager)

    def test_deleted_objects_excluded(self):
        ci = ConfigurationItem.objects.create(
            name="DelCI", ci_type=self.ci_type, status="active", source="manual",
        )
        _force_obj_deleted(ci)
        listing = self.client.get("/api/cmdb/items/")
        self.assertEqual(listing.status_code, 200)
        ids = [row["id"] for row in listing.data]
        self.assertNotIn(ci.id, ids)
        detail = self.client.get(f"/api/cmdb/items/{ci.id}/")
        self.assertEqual(detail.status_code, 404)

        target = ConfigurationItem.objects.create(
            name="T2", ci_type=self.ci_type, status="active", source="manual",
        )
        rel = ConfigurationItemRelationship.objects.create(
            source_ci=self.ci, target_ci=target,
            relationship_type="depends_on", status="active",
        )
        _force_obj_deleted(rel)
        rels = self.client.get("/api/cmdb/relationships/")
        self.assertNotIn(rel.id, [r["id"] for r in rels.data])

        bl = self._baseline()
        _force_obj_deleted(bl)
        bls = self.client.get("/api/cmdb/baselines/")
        self.assertNotIn(bl.id, [b["id"] for b in bls.data])

    def test_relationship_does_not_expand_visibility(self):
        target = ConfigurationItem.objects.create(
            name="Secret", ci_type=self.ci_type, status="active", source="manual",
        )
        ConfigurationItemRelationship.objects.create(
            source_ci=self.ci, target_ci=target,
            relationship_type="depends_on", status="active",
        )
        emp = api_client(self.employee)
        self.assertEqual(emp.get(f"/api/cmdb/items/{target.id}/").status_code, 403)
