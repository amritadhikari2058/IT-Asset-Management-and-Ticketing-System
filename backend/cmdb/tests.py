from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from cmdb.models import ConfigurationItemType, ConfigurationItem, ConfigurationItemRelationship
from cmdb.services import sync_asset_to_ci

User = get_user_model()

def make_user(role):
    u = User.objects.create_user(username=f"{role}_u", password="pass12345", role=role, email=f"{role}@x.com", employee_id=f"EMP{role}")
    return u

class CMDBTypeTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
    def test_create_type(self):
        r = self.client.post("/api/cmdb/types/", {"name":"Server","code":"SERVER","category":"hardware"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["code"], "SERVER")
    def test_employee_denied(self):
        emp = make_user("employee")
        c = APIClient(); c.force_authenticate(emp)
        r = c.get("/api/cmdb/types/")
        self.assertIn(r.status_code, (401,403))

class CMDBItemTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.type = ConfigurationItemType.objects.create(name="Server", code="SERVER", category="hardware")
    def test_create_item_numbering(self):
        r = self.client.post("/api/cmdb/items/", {"name":"CI1","ci_type":self.type.id,"status":"active"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["ci_number"].startswith("CI-"))
    def test_employee_denied(self):
        emp = make_user("employee")
        c = APIClient(); c.force_authenticate(emp)
        r = c.get("/api/cmdb/items/")
        self.assertIn(r.status_code, (401,403))
    def test_verify(self):
        r = self.client.post("/api/cmdb/items/", {"name":"CI2","ci_type":self.type.id})
        ci_id = r.data["id"]; ver = r.data["record_version"]
        r2 = self.client.post(f"/api/cmdb/items/{ci_id}/verify/", {"expected_record_version": ver})
        self.assertEqual(r2.status_code, 200)
        self.assertIsNotNone(r2.data["last_verified_at"])
    def test_retire_requires_reason(self):
        r = self.client.post("/api/cmdb/items/", {"name":"CI3","ci_type":self.type.id})
        ci_id = r.data["id"]; ver = r.data["record_version"]
        r2 = self.client.post(f"/api/cmdb/items/{ci_id}/retire/", {"expected_record_version": ver})
        self.assertEqual(r2.status_code, 400)
    def test_retire_with_reason(self):
        r = self.client.post("/api/cmdb/items/", {"name":"CI4","ci_type":self.type.id})
        ci_id = r.data["id"]; ver = r.data["record_version"]
        r2 = self.client.post(f"/api/cmdb/items/{ci_id}/retire/", {"reason":"done","expected_record_version": ver})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["status"], "retired")

class CMDBRelationshipTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.type = ConfigurationItemType.objects.create(name="Server", code="SERVER", category="hardware")
        r1 = self.client.post("/api/cmdb/items/", {"name":"A","ci_type":self.type.id})
        r2 = self.client.post("/api/cmdb/items/", {"name":"B","ci_type":self.type.id})
        self.a = r1.data["id"]; self.b = r2.data["id"]
    def test_create_relationship(self):
        r = self.client.post("/api/cmdb/relationships/", {"source_ci":self.a,"target_ci":self.b,"relationship_type":"depends_on"})
        self.assertEqual(r.status_code, 201)
    def test_self_reference_rejected(self):
        r = self.client.post("/api/cmdb/relationships/", {"source_ci":self.a,"target_ci":self.a,"relationship_type":"depends_on"})
        self.assertEqual(r.status_code, 400)
    def test_duplicate_rejected(self):
        self.client.post("/api/cmdb/relationships/", {"source_ci":self.a,"target_ci":self.b,"relationship_type":"depends_on"})
        r = self.client.post("/api/cmdb/relationships/", {"source_ci":self.a,"target_ci":self.b,"relationship_type":"depends_on"})
        self.assertEqual(r.status_code, 400)

class CMDBImpactTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.type = ConfigurationItemType.objects.create(name="Server", code="SERVER", category="hardware")
        r1 = self.client.post("/api/cmdb/items/", {"name":"A","ci_type":self.type.id})
        r2 = self.client.post("/api/cmdb/items/", {"name":"B","ci_type":self.type.id})
        self.a = r1.data["id"]; self.b = r2.data["id"]
        self.client.post("/api/cmdb/relationships/", {"source_ci":self.a,"target_ci":self.b,"relationship_type":"depends_on"})
    def test_impact(self):
        r = self.client.get(f"/api/cmdb/items/{self.a}/impact/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.b, r.data["affected_ci_ids"])

class CMDBBaselineDriftTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.type = ConfigurationItemType.objects.create(name="Server", code="SERVER", category="hardware")
        r = self.client.post("/api/cmdb/items/", {"name":"CI","ci_type":self.type.id,"status":"active"})
        self.ci_id = r.data["id"]
        self.ci = ConfigurationItem.objects.get(id=self.ci_id)
    def test_create_baseline(self):
        r = self.client.post("/api/cmdb/baselines/", {"name":"BL1","scope_type":"single_ci","configuration_items":[self.ci_id]})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["checksum"])
    def test_baseline_self_approval_denied(self):
        r = self.client.post("/api/cmdb/baselines/", {"name":"BL2","scope_type":"single_ci","configuration_items":[self.ci_id]})
        bid = r.data["id"]
        r2 = self.client.post(f"/api/cmdb/baselines/{bid}/approve/")
        self.assertEqual(r2.status_code, 403)

class CMDBDashboardTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
    def test_dashboard(self):
        r = self.client.get("/api/cmdb/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("total_cis", r.data)

class CMDBAssetSyncTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        from assets.models import Asset, AssetCategory
        from accounts.models import Department
        cat = AssetCategory.objects.create(name="LaptopCat")
        dept = Department.objects.create(name="IT", code="IT")
        self.asset = Asset.objects.create(name="Laptop1", asset_tag="LT1", category=cat, department=dept, status="available")
    def test_sync_asset(self):
        from cmdb.services import sync_asset_to_ci
        ci, created = sync_asset_to_ci(self.asset, actor=self.admin)
        self.assertTrue(created)
        self.assertEqual(ci.asset_id, self.asset.id)
        # idempotent
        ci2, created2 = sync_asset_to_ci(self.asset, actor=self.admin)
        self.assertFalse(created2)
        self.assertEqual(ci.id, ci2.id)
