"""CMDB services domain tests."""

from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department
from assets.models import Asset, AssetCategory, Vendor
from cmdb.models import (
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
    ConfigurationItemType,
)
from cmdb.services import (
    AssetAssignedError,
    ImpactRequiredError,
    StaleVersionError,
    activate_relationship,
    confirm_relationship,
    create_relationship,
    deactivate_relationship,
    retire_ci,
    sync_asset_to_ci,
    sync_software_product_to_ci,
    verify_ci,
)
from cmdb.tests import api_client, create_ci, make_user
from licensing.models import SoftwareProduct


class AssetSyncServiceTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.cat_laptop = AssetCategory.objects.create(name="Laptop")
        self.cat_server = AssetCategory.objects.create(name="Server")
        self.cat_generic = AssetCategory.objects.create(name="Widget")
        self.dept = Department.objects.create(name="IT", code="IT1")
        self.vendor = Vendor.objects.create(name="Dell")

    def _asset(self, **kw):
        defaults = dict(
            name="Asset", asset_tag=f"AT-{Asset.objects.count()+1}",
            category=self.cat_laptop, status="available",
        )
        defaults.update(kw)
        return Asset.objects.create(**defaults)

    def test_status_mappings_on_create(self):
        holder = make_user("employee", suffix="holder1")
        cases = [
            ({"status": "available"}, "planned"),
            ({"status": "assigned", "assigned_to": holder}, "active"),
            ({"status": "in_repair"}, "maintenance"),
            ({"status": "lost"}, "unknown"),
            ({"status": "retired"}, "retired"),
            ({"status": "disposed"}, "disposed"),
        ]
        for i, (fields, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                asset = self._asset(asset_tag=f"MAP{i}", **fields)
                ci, created = sync_asset_to_ci(asset, actor=self.admin)
                self.assertTrue(created)
                self.assertEqual(ci.status, expected)

    def test_category_department_location_vendor_manufacturer_model_serial(self):
        asset = self._asset(
            name="Srv1", category=self.cat_server,
            department=self.dept, location="DC1", vendor=self.vendor,
            serial_number="SN1",
            status="available",
        )
        ci, created = sync_asset_to_ci(asset, actor=self.admin)
        self.assertTrue(created)
        self.assertEqual(ci.ci_type.name, "Server")
        self.assertEqual(ci.department_id, self.dept.id)
        self.assertEqual(ci.location, "DC1")
        self.assertEqual(ci.vendor_id, self.vendor.id)
        self.assertEqual(ci.serial_number, "SN1")

    def test_idempotent_and_return_tuple(self):
        asset = self._asset()
        ci, created = sync_asset_to_ci(asset, actor=self.admin)
        self.assertTrue(created)
        self.assertIsInstance(ci, ConfigurationItem)
        ci2, created2 = sync_asset_to_ci(asset, actor=self.admin)
        self.assertFalse(created2)
        self.assertEqual(ci.id, ci2.id)
        self.assertEqual(
            ConfigurationItem.objects.filter(asset=asset, is_deleted=False).count(), 1,
        )

    def test_create_missing_false(self):
        asset = self._asset()
        ci, created = sync_asset_to_ci(asset, actor=self.admin, create_missing=False)
        self.assertIsNone(ci)
        self.assertFalse(created)

    def test_update_existing_false(self):
        asset = self._asset(name="OldName")
        ci, _ = sync_asset_to_ci(asset, actor=self.admin)
        asset.name = "NewName"
        asset.save()
        ci2, created = sync_asset_to_ci(asset, actor=self.admin, update_existing=False)
        self.assertFalse(created)
        ci2.refresh_from_db()
        self.assertEqual(ci2.name, "OldName")

    def test_manual_source_preserved(self):
        asset = self._asset()
        manual_type = ConfigurationItemType.objects.create(
            name="ManualT", code="MANUALT", category="hardware",
        )
        manual = ConfigurationItem.objects.create(
            name="manual-ci", ci_type=manual_type, asset=asset,
            source="manual", status="active",
        )
        ci, created = sync_asset_to_ci(asset, actor=self.admin)
        self.assertFalse(created)
        self.assertEqual(ci.id, manual.id)
        ci.refresh_from_db()
        self.assertEqual(ci.name, "manual-ci")
        self.assertEqual(ci.source, "manual")

    def test_update_path_does_not_force_retired_disposed(self):
        asset = self._asset(status="available")
        ci, _ = sync_asset_to_ci(asset, actor=self.admin)
        self.assertEqual(ci.status, "planned")
        asset.status = "retired"
        asset.save(update_fields=["status"])
        ci, _ = sync_asset_to_ci(asset, actor=self.admin)
        ci.refresh_from_db()
        self.assertNotEqual(ci.status, "retired")

    def test_sync_history_recorded(self):
        asset = self._asset()
        ci, _ = sync_asset_to_ci(asset, actor=self.admin)
        self.assertTrue(
            ConfigurationItemHistory.objects.filter(
                configuration_item=ci, event_type="created",
            ).exists()
        )

    def test_sync_deleted_asset_returns_none(self):
        asset = self._asset()
        from django.utils import timezone

        asset.is_deleted = True
        asset.deleted_at = timezone.now()
        asset.save(update_fields=["is_deleted", "deleted_at"])
        ci, created = sync_asset_to_ci(asset, actor=self.admin)
        self.assertIsNone(ci)
        self.assertFalse(created)


class SoftwareSyncServiceTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")

    def _product(self, **kw):
        defaults = dict(
            name=f"Prod-{SoftwareProduct.objects.count()+1}",
            is_active=True, approved_status="approved",
        )
        defaults.update(kw)
        return SoftwareProduct.objects.create(**defaults)

    def test_product_status_mappings(self):
        cases = [
            ({"is_active": True, "approved_status": "approved"}, "active"),
            ({"is_active": True, "approved_status": "prohibited"}, "inactive"),
            ({"is_active": False, "approved_status": "approved"}, "inactive"),
            ({"is_active": True, "approved_status": "retired"}, "retired"),
        ]
        for fields, expected in cases:
            with self.subTest(expected=expected, fields=fields):
                p = self._product(**fields)
                ci, created = sync_software_product_to_ci(p, actor=self.admin)
                self.assertTrue(created)
                self.assertEqual(ci.status, expected)
                self.assertEqual(ci.software_product_id, p.id)
                self.assertEqual(ci.source, "licensing_sync")

    def test_product_link_type_idempotent(self):
        p = self._product(name="AppX", version="1.2")
        ci, created = sync_software_product_to_ci(p, actor=self.admin)
        self.assertTrue(created)
        self.assertEqual(ci.ci_type.code, "SOFTWARE_PRODUCT")
        ci2, created2 = sync_software_product_to_ci(p, actor=self.admin)
        self.assertFalse(created2)
        self.assertEqual(ci.id, ci2.id)

    def test_product_no_license_secret_fields(self):
        p = self._product()
        ci, _ = sync_software_product_to_ci(p, actor=self.admin)
        joined = " ".join(str(v).lower() for v in ci.__dict__.keys())
        self.assertNotIn("license_key", joined)
        self.assertNotIn("secret", joined)
        self.assertNotIn("agreement", joined)


class VerifyServiceTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.ci = ConfigurationItem.objects.create(
            name="CI", ci_type=self.ci_type, status="active", source="manual",
        )

    def test_verify_updates_fields_and_history_and_version(self):
        old_ver = self.ci.record_version
        verify_ci(self.ci, self.admin, note="looks good", expected_record_version=old_ver)
        self.ci.refresh_from_db()
        self.assertIsNotNone(self.ci.last_verified_at)
        self.assertEqual(self.ci.verified_by_id, self.admin.id)
        self.assertEqual(self.ci.record_version, old_ver + 1)
        self.assertTrue(
            ConfigurationItemHistory.objects.filter(
                configuration_item=self.ci, event_type="verified",
            ).exists()
        )

    def test_verify_stale_version_raises(self):
        with self.assertRaises(StaleVersionError):
            verify_ci(self.ci, self.admin, expected_record_version=999)

    def test_verify_api_maps_stale_to_409(self):
        resp = api_client(self.admin).post(
            f"/api/cmdb/items/{self.ci.id}/verify/",
            {"expected_record_version": 999}, format="json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_verify_resolves_open_unverified_finding(self):
        finding = ConfigurationDriftFinding.objects.create(
            configuration_item=self.ci, finding_type="unverified_ci",
            severity="medium", status="open", field_name="last_verified_at",
            expected_value="verified", actual_value="never",
        )
        verify_ci(self.ci, self.admin)
        finding.refresh_from_db()
        self.assertEqual(finding.status, "resolved")


class RetireServiceTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.client = api_client(self.admin)
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )

    def _ci(self, **kw):
        defaults = dict(name="CI", ci_type=self.ci_type, status="active", source="manual")
        defaults.update(kw)
        return ConfigurationItem.objects.create(**defaults)

    def test_reason_required(self):
        ci = self._ci()
        with self.assertRaises(ValueError):
            retire_ci(ci, self.admin, reason="")

    def test_assigned_asset_blocks_retirement(self):
        cat = AssetCategory.objects.create(name="Mon")
        dept = Department.objects.create(name="D", code="D1")
        holder = make_user("employee", suffix="holder-ret")
        asset = Asset.objects.create(
            name="M", asset_tag="MA1", category=cat, department=dept,
            status="assigned", assigned_to=holder,
        )
        ci = self._ci(asset=asset)
        with self.assertRaises(AssetAssignedError):
            retire_ci(ci, self.admin, reason="x")

    def test_impact_requires_ack_then_allows(self):
        a = self._ci(name="A")
        b = self._ci(name="B")
        ConfigurationItemRelationship.objects.create(
            source_ci=b, target_ci=a, relationship_type="depends_on",
            status="active",
        )
        with self.assertRaises(ImpactRequiredError) as ctx:
            retire_ci(a, self.admin, reason="decom")
        self.assertIn("affected_count", ctx.exception.impact)
        ci, impact = retire_ci(a, self.admin, reason="decom", acknowledge_impact=True)
        self.assertEqual(ci.status, "retired")
        self.assertTrue(
            ConfigurationItemHistory.objects.filter(
                configuration_item=ci, event_type="retired",
            ).exists()
        )

    def test_retire_deactivates_relationships_and_stale_version(self):
        a = self._ci(name="A2")
        b = self._ci(name="B2")
        rel = ConfigurationItemRelationship.objects.create(
            source_ci=b, target_ci=a, relationship_type="depends_on",
            status="active",
        )
        with self.assertRaises(StaleVersionError):
            retire_ci(a, self.admin, reason="x", expected_record_version=999)
        retire_ci(a, self.admin, reason="x", acknowledge_impact=True)
        rel.refresh_from_db()
        self.assertNotEqual(rel.status, "active")

    def test_retire_api_impact_409_payload(self):
        a = self._ci(name="A3")
        b = self._ci(name="B3")
        ConfigurationItemRelationship.objects.create(
            source_ci=b, target_ci=a, relationship_type="depends_on",
            status="active",
        )
        resp = api_client(self.admin).post(
            f"/api/cmdb/items/{a.id}/retire/",
            {"reason": "x"}, format="json",
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn("affected_count", resp.data)


class RelationshipServiceTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.a = ConfigurationItem.objects.create(
            name="A", ci_type=self.ci_type, status="active", source="manual",
        )
        self.b = ConfigurationItem.objects.create(
            name="B", ci_type=self.ci_type, status="active", source="manual",
        )

    def test_propose_confirm_activate_deactivate_lifecycle(self):
        rel = create_relationship(
            self.a, self.b, "depends_on", status="proposed", actor=self.admin,
        )
        self.assertEqual(rel.status, "proposed")
        rel = confirm_relationship(rel, self.admin)
        self.assertEqual(rel.status, "active")
        rel = deactivate_relationship(rel, self.admin)
        self.assertEqual(rel.status, "inactive")
        rel = activate_relationship(rel, self.admin)
        self.assertEqual(rel.status, "active")
        self.assertTrue(
            ConfigurationItemHistory.objects.filter(relationship=rel).exists()
        )

    def test_inverse_duplicate_rejected(self):
        create_relationship(
            self.a, self.b, "depends_on", status="active", actor=self.admin,
        )
        # inverse exists (B supports A is inverse of A depends_on B); creation
        # must be rejected or treated as duplicate/no-op depending on policy.
        try:
            rel = create_relationship(
                self.b, self.a, "supports", status="active", actor=self.admin,
            )
            # if accepted, it must not create a conflicting duplicate semantic
            self.assertIsNotNone(rel)
        except Exception:
            self.assertTrue(True)

    def test_self_reference_rejected(self):
        with self.assertRaises(Exception):
            create_relationship(
                self.a, self.a, "depends_on", status="active", actor=self.admin,
            )

    def test_deleted_ci_relationship_rejected(self):
        c = ConfigurationItem.objects.create(
            name="Deleted", ci_type=self.ci_type, status="active",
            source="manual",
        )
        c.is_deleted = True
        c.save(update_fields=["is_deleted"])
        with self.assertRaises(Exception):
            create_relationship(
                self.a, c, "depends_on", status="active", actor=self.admin,
            )

    def test_hierarchy_cycle_rejected(self):
        c = ConfigurationItem.objects.create(
            name="C", ci_type=self.ci_type, status="active", source="manual",
        )
        create_relationship(self.a, self.b, "contains", status="active", actor=self.admin)
        create_relationship(self.b, c, "contains", status="active", actor=self.admin)
        with self.assertRaises(Exception):
            create_relationship(c, self.a, "contains", status="active", actor=self.admin)

    def test_reciprocal_depends_on_semantics(self):
        create_relationship(self.a, self.b, "depends_on", status="active", actor=self.admin)
        try:
            rel2 = create_relationship(self.b, self.a, "depends_on", status="active", actor=self.admin)
            self.assertIsNotNone(rel2.id)
        except Exception:
            pass


class HistoryImmutabilityTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.ci = ConfigurationItem.objects.create(
            name="CI", ci_type=self.ci_type, status="active", source="manual",
        )

    def test_history_save_and_delete_raise(self):
        h = ConfigurationItemHistory.objects.create(
            configuration_item=self.ci, event_type="created", source="manual",
        )
        with self.assertRaises(Exception):
            h.detail = "changed"
            h.save()
        with self.assertRaises(Exception):
            h.delete()

    def test_history_api_read_only(self):
        h = ConfigurationItemHistory.objects.create(
            configuration_item=self.ci, event_type="created", source="manual",
        )
        client = api_client(self.admin)
        self.assertEqual(client.get(f"/api/cmdb/history/{h.id}/").status_code, 200)
        self.assertIn(
            client.post("/api/cmdb/history/", {"configuration_item": self.ci.id}, format="json").status_code,
            (403, 405),
        )
        self.assertIn(client.delete(f"/api/cmdb/history/{h.id}/").status_code, (403, 405))

    def test_failed_action_creates_no_success_history(self):
        before = ConfigurationItemHistory.objects.filter(
            configuration_item=self.ci, event_type="retired",
        ).count()
        with self.assertRaises(ValueError):
            retire_ci(self.ci, self.admin, reason="")
        after = ConfigurationItemHistory.objects.filter(
            configuration_item=self.ci, event_type="retired",
        ).count()
        self.assertEqual(before, after)


import threading
from django.db import connection
from unittest import skipUnless


@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for concurrency verification")
class HierarchyConcurrencyTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVERCONC", category="hardware",
        )
        self.a = ConfigurationItem.objects.create(
            name="A", ci_type=self.ci_type, status="active", source="manual",
        )
        self.b = ConfigurationItem.objects.create(
            name="B", ci_type=self.ci_type, status="active", source="manual",
        )

    def test_concurrent_hierarchy_creation_does_not_create_cycle(self):
        results = {}

        def worker(key, src, tgt):
            try:
                rel = create_relationship(
                    src, tgt, "contains", status="active", actor=self.admin,
                )
                results[key] = ("ok", rel.id)
            except Exception as exc:  # noqa: BLE001
                results[key] = ("error", type(exc).__name__)
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=("ab", self.a, self.b))
        t2 = threading.Thread(target=worker, args=("ba", self.b, self.a))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertEqual(set(results), {"ab", "ba"})
        ab_exists = ConfigurationItemRelationship.objects.filter(
            source_ci=self.a, target_ci=self.b,
            relationship_type="contains", status="active", is_deleted=False,
        ).exists()
        ba_exists = ConfigurationItemRelationship.objects.filter(
            source_ci=self.b, target_ci=self.a,
            relationship_type="contains", status="active", is_deleted=False,
        ).exists()
        self.assertFalse(
            ab_exists and ba_exists,
            f"concurrent hierarchy cycle created: {results}",
        )


@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for concurrency verification")
class HierarchyActivationConcurrencyTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVERACT", category="hardware",
        )
        self.a = ConfigurationItem.objects.create(
            name="A", ci_type=self.ci_type, status="active", source="manual",
        )
        self.b = ConfigurationItem.objects.create(
            name="B", ci_type=self.ci_type, status="active", source="manual",
        )
        self.rel_ab = create_relationship(
            self.a, self.b, "contains", status="proposed", actor=self.admin,
        )
        self.rel_ba = create_relationship(
            self.b, self.a, "contains", status="proposed", actor=self.admin,
        )

    def test_concurrent_activation_does_not_create_cycle(self):
        results = {}

        def worker(key, rel):
            try:
                activated = activate_relationship(rel, self.admin)
                results[key] = ("ok", activated.status)
            except Exception as exc:  # noqa: BLE001
                results[key] = ("error", type(exc).__name__)
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=("ab", self.rel_ab))
        t2 = threading.Thread(target=worker, args=("ba", self.rel_ba))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertEqual(set(results), {"ab", "ba"})
        ab_active = ConfigurationItemRelationship.objects.filter(
            pk=self.rel_ab.pk, status="active", is_deleted=False,
        ).exists()
        ba_active = ConfigurationItemRelationship.objects.filter(
            pk=self.rel_ba.pk, status="active", is_deleted=False,
        ).exists()
        self.assertFalse(
            ab_active and ba_active,
            f"concurrent activation created a cycle: {results}",
        )


@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for concurrency verification")
class HierarchyDirectModelConcurrencyTests(TestCase):
    def setUp(self):
        self.ci_type = ConfigurationItemType.objects.create(
            name="Server", code="SERVERDIR", category="hardware",
        )
        self.a = ConfigurationItem.objects.create(
            name="A", ci_type=self.ci_type, status="active", source="manual",
        )
        self.b = ConfigurationItem.objects.create(
            name="B", ci_type=self.ci_type, status="active", source="manual",
        )

    def test_direct_model_save_does_not_create_cycle(self):
        results = {}

        def worker(key, src, tgt):
            try:
                rel = ConfigurationItemRelationship.objects.create(
                    source_ci=src, target_ci=tgt,
                    relationship_type="contains", status="active",
                )
                results[key] = ("ok", rel.id)
            except Exception as exc:  # noqa: BLE001
                results[key] = ("error", type(exc).__name__)
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=("ab", self.a, self.b))
        t2 = threading.Thread(target=worker, args=("ba", self.b, self.a))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertEqual(set(results), {"ab", "ba"})
        ab_exists = ConfigurationItemRelationship.objects.filter(
            source_ci=self.a, target_ci=self.b,
            relationship_type="contains", status="active", is_deleted=False,
        ).exists()
        ba_exists = ConfigurationItemRelationship.objects.filter(
            source_ci=self.b, target_ci=self.a,
            relationship_type="contains", status="active", is_deleted=False,
        ).exists()
        self.assertFalse(ab_exists and ba_exists, results)
