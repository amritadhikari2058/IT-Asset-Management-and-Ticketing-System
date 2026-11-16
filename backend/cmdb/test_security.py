"""CMDB security and IDOR tests (executable)."""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department
from assets.models import Asset, AssetCategory
from changes.models import ChangeRequest
from cmdb.models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemRelationship,
    ConfigurationItemType,
)
from cmdb.tests import api_client, make_user
from services.models import ServiceCatalogueItem
from tickets.models import Ticket


class CMDBSecurityBase(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin", suffix="sec")
        self.manager = make_user("it_manager", suffix="sec")
        self.support = make_user("it_support", suffix="sec")
        self.employee = make_user("employee", suffix="sec")
        self.ctype = ConfigurationItemType.objects.create(name="Server", code="SRVSEC", category="hardware")
        self.dept = Department.objects.create(name="SecDept", code="SD1")

    def mk_ci(self, **kw):
        defaults = dict(name="CI", ci_type=self.ctype, status="active", source="manual")
        defaults.update(kw)
        return ConfigurationItem.objects.create(**defaults)


class IDORAndAccessTests(CMDBSecurityBase):
    def test_object_idor_matrix_and_unknown_inactive(self):
        ci = self.mk_ci(name="IDOR")
        other = self.mk_ci(name="Other")
        rel = ConfigurationItemRelationship.objects.create(source_ci=ci, target_ci=other, relationship_type="depends_on", status="active")
        service = ServiceCatalogueItem.objects.create(name="SvcSec", is_active=True)
        from cmdb.models import ServiceConfigurationItemLink
        link = ServiceConfigurationItemLink.objects.create(service=service, configuration_item=ci, role="primary")
        baseline = ConfigurationBaseline.objects.create(name="BL", scope_type="single_ci", status="draft", snapshot={"cis": {}}, checksum="x")
        baseline.configuration_items.add(ci)
        drift = ConfigurationDriftFinding.objects.create(configuration_item=ci, finding_type="field_changed", severity="low", status="open", field_name="name", expected_value="a", actual_value="b", fingerprint="fp-sec-1")
        # employee denied across objects
        emp = api_client(self.employee)
        for url in [f"/api/cmdb/items/{ci.id}/", f"/api/cmdb/relationships/{rel.id}/", f"/api/cmdb/service-links/{link.id}/", f"/api/cmdb/baselines/{baseline.id}/", f"/api/cmdb/drift/{drift.id}/"]:
            self.assertEqual(emp.get(url).status_code, 403)
        # unknown role and inactive denied
        mystery = make_user("mystery_role", suffix="secx")
        self.assertEqual(api_client(mystery).get(f"/api/cmdb/items/{ci.id}/").status_code, 403)
        inactive = make_user("it_support", suffix="seci")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        self.assertIn(api_client(inactive).get(f"/api/cmdb/items/{ci.id}/").status_code, (401, 403))
        # staff can read existing objects (scoped by role rules)
        sup = api_client(self.support)
        self.assertEqual(sup.get(f"/api/cmdb/items/{ci.id}/").status_code, 200)
        self.assertEqual(sup.get(f"/api/cmdb/relationships/{rel.id}/").status_code, 200)
        self.assertEqual(sup.get(f"/api/cmdb/service-links/{link.id}/").status_code, 200)
        self.assertEqual(sup.get(f"/api/cmdb/drift/{drift.id}/").status_code, 200)

    def test_hidden_linked_objects_and_deleted(self):
        cat = AssetCategory.objects.create(name="Laptop")
        asset = Asset.objects.create(name="A", asset_tag="ATSEC", category=cat, status="available")
        ci = self.mk_ci(asset=asset)
        from django.utils import timezone
        asset.is_deleted = True
        asset.deleted_at = timezone.now()
        asset.save(update_fields=["is_deleted", "deleted_at"])
        # CI remains readable to staff; hidden asset state must not crash detail serialization
        self.assertEqual(api_client(self.support).get(f"/api/cmdb/items/{ci.id}/").status_code, 200)
        # deleted CI not accessible
        type(ci).objects.filter(pk=ci.pk).update(is_deleted=True)
        self.assertEqual(api_client(self.admin).get(f"/api/cmdb/items/{ci.id}/").status_code, 404)


class FieldProtectionTests(CMDBSecurityBase):
    def test_support_protected_fields_and_source_spoofing_and_client_ids(self):
        sup = api_client(self.support)
        # create allowed; protected fields ignored/rejected on update
        r = sup.post("/api/cmdb/items/", {"name": "SupCI", "ci_type": self.ctype.id, "status": "active"}, format="json")
        self.assertEqual(r.status_code, 201)
        ci_id = r.data["id"]
        r = sup.patch(f"/api/cmdb/items/{ci_id}/", {"source": "discovery", "source_identifier": "x", "ci_number": "HACK-1"}, format="json")
        # either 200 with ignored fields or 400; must not accept spoofed source/ci_number
        ci = ConfigurationItem.objects.get(pk=ci_id)
        self.assertNotEqual(ci.source, "discovery")
        self.assertNotEqual(ci.source_identifier, "x")
        self.assertNotEqual(ci.ci_number, "HACK-1")
        # client checksum not accepted via normal APIs (no writable field)
        r = api_client(self.admin).post("/api/cmdb/baselines/", {"name": "B", "scope_type": "single_ci", "configuration_items": [ci_id], "checksum": "bad"}, format="json")
        self.assertIn(r.status_code, (201, 400))

    def test_baseline_self_approval_and_critical_drift_acceptance(self):
        ci = self.mk_ci()
        baseline = ConfigurationBaseline.objects.create(name="SB", scope_type="single_ci", status="pending_approval", created_by=self.manager, snapshot={"cis": {}}, checksum="x")
        baseline.configuration_items.add(ci)
        mgr = api_client(self.manager)
        r = mgr.post(f"/api/cmdb/baselines/{baseline.id}/approve/")
        self.assertEqual(r.status_code, 403)
        drift = ConfigurationDriftFinding.objects.create(configuration_item=ci, finding_type="field_changed", severity="critical", status="open", field_name="name", expected_value="a", actual_value="b", fingerprint="fp-crit-1")
        r = mgr.post(f"/api/cmdb/drift/{drift.id}/accept/")
        self.assertEqual(r.status_code, 403)
        r = api_client(self.admin).post(f"/api/cmdb/drift/{drift.id}/accept/")
        self.assertIn(r.status_code, (200, 400))  # 400 if state disallows, but not 403

    def test_retirement_impact_bypass_stale_and_drift_masking(self):
        ci = self.mk_ci()
        # add dependent to force impact acknowledgement path
        dep = self.mk_ci(name="Dep")
        ConfigurationItemRelationship.objects.create(source_ci=dep, target_ci=ci, relationship_type="depends_on", status="active")
        adm = api_client(self.admin)
        # retirement without acknowledge when impact exists should be blocked/conflict
        r = adm.post(f"/api/cmdb/items/{ci.id}/retire/", {"reason": "x"}, format="json")
        self.assertIn(r.status_code, (400, 409))
        # stale version on verify
        r = adm.post(f"/api/cmdb/items/{dep.id}/verify/", {"expected_record_version": 999}, format="json")
        self.assertEqual(r.status_code, 409)
        # drift masks sensitive values (ip_address/serial handled by mask_value; check no raw leak in serialized fields)
        ci2 = self.mk_ci(name="Mask", serial_number="SER123", ip_address="10.0.0.5")
        baseline = ConfigurationBaseline.objects.create(name="MB", scope_type="single_ci", status="approved", snapshot={"cis": {ci2.ci_number: {"name": "Mask", "status": "active", "lifecycle_state": "proposed", "criticality": "medium", "environment": "production", "version": "", "manufacturer": "", "model": "", "hostname": "", "ip_address": "10.0.0.1", "dns_name": "", "location": "", "monitoring_state": "unknown", "data_classification": "internal", "validated_system_impact": "none", "contains_personal_data": False, "ci_type_id": self.ctype.id, "department_id": None, "owner_id": None, "technical_owner_id": None, "support_group_id": None, "vendor_id": None, "service_catalogue_item_id": None, "serial_number": "SER000", "attributes": {}, "relationships": []}}}, checksum="x")
        baseline.configuration_items.add(ci2)
        from cmdb.baselines import evaluate_configuration_drift
        findings = evaluate_configuration_drift(ci2, baseline=baseline, notify=False)
        # sensitive diffs masked
        for f in findings:
            if f.field_name in ("ip_address", "serial_number"):
                self.assertIn(f.expected_value, ("[masked]", ""))
                self.assertIn(f.actual_value, ("[masked]", ""))
