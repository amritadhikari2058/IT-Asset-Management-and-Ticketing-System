"""CMDB management command tests (isolated DB only)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import Department
from assets.models import Asset, AssetCategory
from cmdb.models import ConfigurationBaseline, ConfigurationDriftFinding, ConfigurationItem, ConfigurationItemType, ServiceConfigurationItemLink
from cmdb.tests import make_user
from services.models import ServiceCatalogueItem


class SeedCMDBTypesCommandTests(TestCase):
    def test_dry_run_no_mutation(self):
        out = StringIO()
        call_command("seed_cmdb_types", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("DRY RUN", text)
        self.assertEqual(ConfigurationItemType.objects.count(), 0)

    def test_create_update_idempotent_and_counts(self):
        out = StringIO()
        call_command("seed_cmdb_types", "--create", stdout=out)
        text = out.getvalue()
        self.assertIn("created:", text)
        first = ConfigurationItemType.objects.count()
        self.assertGreater(first, 0)
        # make a drift to verify update-existing
        t = ConfigurationItemType.objects.filter(code="SERVER").first()
        self.assertIsNotNone(t)
        t.name = "OldName"
        t.save(update_fields=["name"])
        out2 = StringIO()
        call_command("seed_cmdb_types", "--create", "--update-existing", stdout=out2)
        t.refresh_from_db()
        self.assertEqual(t.name, "Server")
        self.assertTrue(t.is_system)
        out3 = StringIO()
        call_command("seed_cmdb_types", "--create", stdout=out3)
        self.assertEqual(ConfigurationItemType.objects.count(), first)
        self.assertNotIn("Secret", out3.getvalue())


class SyncAssetsCommandTests(TestCase):
    def setUp(self):
        self.cat1 = AssetCategory.objects.create(name="Laptop")
        self.cat2 = AssetCategory.objects.create(name="Server")
        self.dept1 = Department.objects.create(name="IT", code="ITC")
        self.dept2 = Department.objects.create(name="HR", code="HRC")
        self.a1 = Asset.objects.create(name="A1", asset_tag="AT1", category=self.cat1, department=self.dept1, status="available")
        self.a2 = Asset.objects.create(name="A2", asset_tag="AT2", category=self.cat2, department=self.dept2, status="available")

    def test_dry_run_execute_filters_and_counts(self):
        out = StringIO()
        call_command("sync_assets_to_cmdb", "--dry-run", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertEqual(ConfigurationItem.objects.count(), 0)
        out = StringIO()
        call_command("sync_assets_to_cmdb", "--execute", "--asset-id", self.a1.id, stdout=out)
        self.assertEqual(ConfigurationItem.objects.filter(asset=self.a1).count(), 1)
        self.assertEqual(ConfigurationItem.objects.filter(asset=self.a2).count(), 0)
        out = StringIO()
        call_command("sync_assets_to_cmdb", "--execute", "--category-id", self.cat2.id, stdout=out)
        self.assertEqual(ConfigurationItem.objects.filter(asset=self.a2).count(), 1)
        # batch size and counts message
        Asset.objects.create(name="A3", asset_tag="AT3", category=self.cat1, status="available")
        out = StringIO()
        call_command("sync_assets_to_cmdb", "--execute", "--batch-size", 1, stdout=out)
        self.assertIn("created:", out.getvalue())

    def test_create_update_missing_flags_and_manual_preservation(self):
        # no-create-missing
        out = StringIO()
        call_command("sync_assets_to_cmdb", "--execute", "--asset-id", self.a1.id, "--no-create-missing", stdout=out)
        self.assertFalse(ConfigurationItem.objects.filter(asset=self.a1).exists())
        # create then manual preservation
        call_command("sync_assets_to_cmdb", "--execute", "--asset-id", self.a1.id, stdout=StringIO())
        ci = ConfigurationItem.objects.get(asset=self.a1)
        ci.source = "manual"
        ci.name = "ManualName"
        ci.save(update_fields=["source", "name"])
        call_command("sync_assets_to_cmdb", "--execute", "--asset-id", self.a1.id, "--update-existing", stdout=StringIO())
        ci.refresh_from_db()
        self.assertEqual(ci.name, "ManualName")
        # no-update-existing
        ci2_asset = Asset.objects.create(name="A4", asset_tag="AT4", category=self.cat1, status="available")
        call_command("sync_assets_to_cmdb", "--execute", "--asset-id", ci2_asset.id, stdout=StringIO())
        ci2 = ConfigurationItem.objects.get(asset=ci2_asset)
        ci2_asset.name = "Changed"
        ci2_asset.save(update_fields=["name"])
        call_command("sync_assets_to_cmdb", "--execute", "--asset-id", ci2_asset.id, "--no-update-existing", stdout=StringIO())
        ci2.refresh_from_db()
        self.assertNotEqual(ci2.name, "Changed")


class EvaluateDriftCommandTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin", suffix="cmd")
        self.ctype = ConfigurationItemType.objects.create(name="Server", code="SRVCMD", category="hardware")
        self.ci = ConfigurationItem.objects.create(name="CI1", ci_type=self.ctype, status="active")
        self.baseline = ConfigurationBaseline.objects.create(name="B", scope_type="single_ci", status="approved", snapshot={"cis": {self.ci.ci_number: {"name": "Different", "status": "active", "lifecycle_state": "proposed", "criticality": "medium", "environment": "production", "version": "", "manufacturer": "", "model": "", "hostname": "", "ip_address": None, "dns_name": "", "location": "", "monitoring_state": "unknown", "data_classification": "internal", "validated_system_impact": "none", "contains_personal_data": False, "ci_type_id": self.ctype.id, "department_id": None, "owner_id": None, "technical_owner_id": None, "support_group_id": None, "vendor_id": None, "service_catalogue_item_id": None, "attributes": {}, "relationships": []}}}, checksum="x")
        self.baseline.configuration_items.add(self.ci)
        self.service = ServiceCatalogueItem.objects.create(name="SvcCmd", is_active=True)
        ServiceConfigurationItemLink.objects.create(service=self.service, configuration_item=self.ci, role="primary")

    def test_dry_run_execute_filters_and_counts(self):
        out = StringIO()
        call_command("evaluate_configuration_drift", "--dry-run", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertEqual(ConfigurationDriftFinding.objects.count(), 0)
        out = StringIO()
        call_command("evaluate_configuration_drift", "--execute", stdout=out)
        self.assertIn("evaluated:", out.getvalue())
        self.assertGreaterEqual(ConfigurationDriftFinding.objects.count(), 1)
        # filters and batch size
        out = StringIO()
        call_command("evaluate_configuration_drift", "--execute", "--ci-id", self.ci.id, "--batch-size", 1, stdout=out)
        self.assertIn("evaluated:", out.getvalue())
        out = StringIO()
        call_command("evaluate_configuration_drift", "--execute", "--baseline-id", self.baseline.id, stdout=out)
        self.assertIn("evaluated:", out.getvalue())
        out = StringIO()
        call_command("evaluate_configuration_drift", "--execute", "--service-id", self.service.id, stdout=out)
        self.assertIn("evaluated:", out.getvalue())
        self.assertNotIn("password", out.getvalue().lower())
        self.assertNotIn("secret", out.getvalue().lower())
