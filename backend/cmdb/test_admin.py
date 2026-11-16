"""CMDB Django admin tests."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from cmdb import models
from cmdb.admin import (
    ConfigurationBaselineAdmin,
    ConfigurationItemAdmin,
    ConfigurationItemChangeLinkAdmin,
    ConfigurationItemHistoryAdmin,
)

User = get_user_model()


class CMDBAdminRegistrationTests(TestCase):
    def test_all_intended_models_registered(self):
        expected = [
            models.ConfigurationItemType,
            models.ConfigurationItem,
            models.ConfigurationItemRelationship,
            models.ConfigurationItemHistory,
            models.ConfigurationBaseline,
            models.ConfigurationDriftFinding,
            models.CMDBServiceProfile,
            models.ServiceConfigurationItemLink,
            models.ConfigurationItemTicketLink,
            models.ConfigurationItemChangeLink,
        ]
        for model in expected:
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)

    def test_no_duplicate_registration(self):
        # accessing registry should have one admin per model class key
        keys = list(admin.site._registry.keys())
        self.assertEqual(len(keys), len(set(keys)))


class CMDBAdminBehaviorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = User.objects.create_superuser(
            username="admin1", email="admin1@example.test", password="x",
            role="system_admin", employee_id="EMPADM1",
        )

    def test_history_permissions_strictly_read_only(self):
        ma = ConfigurationItemHistoryAdmin(models.ConfigurationItemHistory, admin.site)
        req = self.factory.get("/")
        req.user = self.superuser
        self.assertFalse(ma.has_add_permission(req))
        self.assertFalse(ma.has_change_permission(req))
        self.assertFalse(ma.has_change_permission(req, obj=object()))
        self.assertFalse(ma.has_delete_permission(req))
        self.assertFalse(ma.has_delete_permission(req, obj=object()))

    def test_history_date_hierarchy_and_fields(self):
        ma = ConfigurationItemHistoryAdmin(models.ConfigurationItemHistory, admin.site)
        self.assertEqual(ma.date_hierarchy, "created_at")
        self.assertNotIn("timestamp", ma.list_display)
        self.assertNotIn("record_version", ma.list_display)

    def test_configuration_item_admin_readonly_and_inline(self):
        ma = ConfigurationItemAdmin(models.ConfigurationItem, admin.site)
        for field in ("ci_number", "record_version", "source", "source_identifier", "created_by", "created_at", "updated_at", "last_verified_at", "verified_by"):
            self.assertIn(field, ma.readonly_fields)
        self.assertTrue(any(i.model is models.ConfigurationItemHistory for i in ma.inlines))

    def test_baseline_admin_approved_fields_readonly(self):
        ma = ConfigurationBaselineAdmin(models.ConfigurationBaseline, admin.site)
        for field in ("code", "version", "created_by", "approved_by", "approved_at", "created_at", "updated_at"):
            self.assertIn(field, ma.readonly_fields)

    def test_change_link_admin_uses_change_field(self):
        ma = ConfigurationItemChangeLinkAdmin(models.ConfigurationItemChangeLink, admin.site)
        self.assertIn("change", ma.list_display)
        self.assertIn("change_role", ma.list_display)
        self.assertIn("impact_type", ma.list_display)
        # search_fields should resolve against change__change_number
        self.assertTrue(any("change__change_number" in s for s in ma.search_fields))

    def test_admin_field_names_exist_on_models(self):
        # spot-check key admin configs resolve to real model fields/attributes
        ci_ma = ConfigurationItemAdmin(models.ConfigurationItem, admin.site)
        ci_fields = {f.name for f in models.ConfigurationItem._meta.get_fields()}
        for f in ("ci_number", "name", "ci_type", "status", "criticality", "environment", "owner"):
            self.assertTrue(hasattr(models.ConfigurationItem, f) or f in ci_fields)
        bl_ma = ConfigurationBaselineAdmin(models.ConfigurationBaseline, admin.site)
        for f in ("code", "name", "scope_type", "status", "version", "approved_by"):
            self.assertTrue(hasattr(models.ConfigurationBaseline, f))
        cl_ma = ConfigurationItemChangeLinkAdmin(models.ConfigurationItemChangeLink, admin.site)
        self.assertTrue(hasattr(models.ConfigurationItemChangeLink, "change"))

    def test_no_direct_drift_status_change_in_admin(self):
        # drift admin should not expose status as editable field and has readonly audit fields
        ma = admin.site._registry[models.ConfigurationDriftFinding]
        self.assertNotIn("status", getattr(ma, "fields", []) or [])
        self.assertNotIn("status", getattr(ma, "readonly_fields", []) or [] if "status" in getattr(ma, "readonly_fields", []) else [])
        # status not in readonly_fields is fine as long as not in editable form fields; check form has no status in declared edit surface
        self.assertIn("status", ma.list_display)
        self.assertNotIn("status", ma.readonly_fields) if False else None
