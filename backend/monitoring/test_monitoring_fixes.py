"""Focused tests for Monitoring backend fixes.

Tests the serializer and view corrections made during Phase 15:
1. MonitoringAlertListSerializer.get_automation_state uses correct model fields
   (automation_error_code, auto_ticket_created, auto_resolved) instead of
   the nonexistent automation_status field.
2. MonitoringSourceViewSet.get_serializer_class uses MonitoringSourceWriteSerializer
   for create and partial_update, MonitoringSourceListSerializer for list/retrieve.
3. Source secret handling: plaintext returned once on create only, never on
   list/retrieve/update.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from monitoring.models import MonitoringSource, MonitoringAlert
from monitoring.serializers import (
    MonitoringAlertListSerializer,
    MonitoringSourceListSerializer,
)
from monitoring.source_serializers import MonitoringSourceWriteSerializer
from monitoring.views import MonitoringSourceViewSet

User = get_user_model()


class MonitoringAlertListSerializerTests(TestCase):
    """Test automation state derivation uses correct model fields."""

    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="S", code="src1", source_type="prometheus_alertmanager"
        )
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin", email="a@t.test",
            employee_id="ADMIN001", role="system_admin", is_staff=True, is_superuser=True
        )
        self.client.force_authenticate(self.admin)

    def test_automation_state_none_when_no_automation(self):
        """No automation fields set -> automation_state is None."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp1", title="T",
            summary="S", severity="m", status="o",
            auto_ticket_created=False, auto_resolved=False,
            automation_error_code="",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertIsNone(serializer.data.get("automation_state"))

    def test_automation_state_ticket_created(self):
        """auto_ticket_created=True -> automation_state is ticket_created."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp2", title="T",
            summary="S", severity="m", status="o",
            auto_ticket_created=True, auto_resolved=False,
            automation_error_code="",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertEqual(serializer.data.get("automation_state"), "ticket_created")

    def test_automation_state_resolved(self):
        """auto_resolved=True -> automation_state is resolved."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp3", title="T",
            summary="S", severity="m", status="o",
            auto_ticket_created=False, auto_resolved=True,
            automation_error_code="",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertEqual(serializer.data.get("automation_state"), "resolved")

    def test_automation_state_failed(self):
        """automation_error_code set -> automation_state is failed."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp4", title="T",
            summary="S", severity="m", status="o",
            auto_ticket_created=False, auto_resolved=False,
            automation_error_code="ECONNREFUSED",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertEqual(serializer.data.get("automation_state"), "failed")

    def test_automation_state_priority_order(self):
        """Failed takes precedence over ticket_created over resolved."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp5", title="T",
            summary="S", severity="m", status="o",
            auto_ticket_created=True, auto_resolved=True,
            automation_error_code="TIMEOUT",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertEqual(serializer.data.get("automation_state"), "failed")

    def test_automation_retry_count_defaults_zero(self):
        """automation_retry_count defaults to 0 when not set."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp6", title="T",
            summary="S", severity="m", status="o",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertEqual(serializer.data.get("automation_retry_count"), 0)

    def test_automation_error_code_null_when_empty(self):
        """automation_error_code is None when empty string."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp7", title="T",
            summary="S", severity="m", status="o",
            automation_error_code="",
        )
        serializer = MonitoringAlertListSerializer(a)
        self.assertIsNone(serializer.data.get("automation_error_code"))

    def test_list_endpoint_exposes_automation_fields(self):
        """GET /api/monitoring/alerts/ includes automation fields."""
        a = MonitoringAlert.objects.create(
            source=self.source, fingerprint="fp8", title="T",
            summary="S", severity="m", status="o",
            auto_ticket_created=True,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertTrue(any(
            r.get("alert_number") == a.alert_number
            for r in results
        ), f"Alert {a.alert_number} not found in list: {results}")


class MonitoringSourceViewSetSerializerClassTests(TestCase):
    """Test that get_serializer_class returns the correct serializer per action."""

    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="S", code="src1", source_type="prometheus_alertmanager"
        )
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin", email="a@t.test",
            employee_id="ADMIN001", role="system_admin", is_staff=True, is_superuser=True
        )
        self.client.force_authenticate(self.admin)

    def test_list_uses_list_serializer(self):
        """List action returns MonitoringSourceListSerializer (no secret fields)."""
        view = MonitoringSourceViewSet()
        view.request = self.client.get("/api/monitoring/sources/").wsgi_request
        view.action = "list"
        view.kwargs = {}
        self.assertEqual(view.get_serializer_class(), MonitoringSourceListSerializer)

    def test_retrieve_uses_list_serializer(self):
        """Retrieve action returns MonitoringSourceListSerializer."""
        view = MonitoringSourceViewSet()
        view.action = "retrieve"
        view.kwargs = {"pk": self.source.pk}
        self.assertEqual(view.get_serializer_class(), MonitoringSourceListSerializer)

    def test_create_uses_write_serializer(self):
        """Create action returns MonitoringSourceWriteSerializer."""
        view = MonitoringSourceViewSet()
        view.action = "create"
        view.kwargs = {}
        self.assertEqual(view.get_serializer_class(), MonitoringSourceWriteSerializer)

    def test_partial_update_uses_write_serializer(self):
        """Partial update action returns MonitoringSourceWriteSerializer."""
        view = MonitoringSourceViewSet()
        view.action = "partial_update"
        view.kwargs = {"pk": self.source.pk}
        self.assertEqual(view.get_serializer_class(), MonitoringSourceWriteSerializer)


class MonitoringSourceSecretHandlingTests(TestCase):
    """Test that plaintext secret is returned once on create only."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin", email="a@t.test",
            employee_id="ADMIN001", role="system_admin", is_staff=True, is_superuser=True
        )
        self.client.force_authenticate(self.admin)

    def test_create_returns_plaintext_secret_once(self):
        """Create response includes plaintext secret."""
        resp = self.client.post("/api/monitoring/sources/", {
            "name": "Secret Source", "code": "sec-src",
            "source_type": "generic_webhook",
            "secret": "my-plaintext-secret",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("secret", resp.data)
        self.assertEqual(resp.data["secret"], "my-plaintext-secret")

    def test_create_generates_secret_when_not_provided(self):
        """Create without secret generates one and returns it."""
        resp = self.client.post("/api/monitoring/sources/", {
            "name": "Auto Secret", "code": "auto-src",
            "source_type": "generic_webhook",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("secret", resp.data)
        self.assertIsInstance(resp.data["secret"], str)
        self.assertGreater(len(resp.data["secret"]), 0)

    def test_list_never_exposes_secret(self):
        """List response never includes secret or secret_hash."""
        MonitoringSource.objects.create(
            name="List Source", code="list-src",
            source_type="generic_webhook",
        )
        resp = self.client.get("/api/monitoring/sources/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        for r in results:
            self.assertNotIn("secret", r)
            self.assertNotIn("secret_hash", r)

    def test_retrieve_never_exposes_secret(self):
        """Retrieve response never includes secret or secret_hash."""
        s = MonitoringSource.objects.create(
            name="Retrieve Source", code="ret-src",
            source_type="generic_webhook",
        )
        resp = self.client.get(f"/api/monitoring/sources/{s.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn("secret", resp.data)
        self.assertNotIn("secret_hash", resp.data)

    def test_update_never_exposes_secret(self):
        """Update response never includes secret."""
        s = MonitoringSource.objects.create(
            name="Update Source", code="upd-src",
            source_type="generic_webhook",
        )
        resp = self.client.patch(f"/api/monitoring/sources/{s.pk}/", {
            "description": "Updated description",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn("secret", resp.data)
        self.assertNotIn("secret_hash", resp.data)

    def test_update_rejects_is_active(self):
        """Update rejects direct is_active mutation."""
        s = MonitoringSource.objects.create(
            name="No Active", code="no-act",
            source_type="generic_webhook",
        )
        resp = self.client.patch(f"/api/monitoring/sources/{s.pk}/", {
            "is_active": False,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_rejects_secret_hash(self):
        """Update rejects direct secret_hash mutation."""
        s = MonitoringSource.objects.create(
            name="No Hash", code="no-hash",
            source_type="generic_webhook",
        )
        resp = self.client.patch(f"/api/monitoring/sources/{s.pk}/", {
            "secret_hash": "evil-hash",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
