"""Focused operations API tests for Monitoring module - Alert collection."""

from django.test import TestCase
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


class AlertCollectionApiTests(APITestCase):
    """Tests for the Alert collection (list) endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            username="admin_user", email="admin@example.test",
            employee_id="MON-ADMIN", role="system_admin", is_staff=True,
            is_superuser=True,
        )
        self.it_manager = User.objects.create_user(
            username="it_manager_user", email="itmgr@example.test",
            employee_id="MON-MGR", role="it_manager", is_staff=True,
        )
        self.it_support = User.objects.create_user(
            username="it_support_user", email="itsup@example.test",
            employee_id="MON-SUP", role="it_support", is_staff=True,
        )
        self.employee = User.objects.create_user(
            username="employee_user", email="emp@example.test",
            employee_id="MON-EMP", role="employee", is_staff=False,
        )
        self.inactive_user = User.objects.create_user(
            username="inactive_user", email="inact@example.test",
            employee_id="MON-INACTIVE", role="it_support", is_active=False,
        )

    def test_list_paginated_response_shape(self):
        """Test the list endpoint returns standard paginated shape."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)
        self.assertIn("results", response.data)

    def test_list_safe_fields(self):
        """Test the list response contains only safe operational fields."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.data["results"]:
            result = response.data["results"][0]
            safe_fields = {"id", "alert_number", "title", "severity", "status",
                          "source_name", "event_count", "first_seen", "last_seen"}
            for key in result.keys():
                self.assertIn(key, safe_fields, f"Unexpected field: {key}")

    def test_list_severity_filter(self):
        """Test filtering alerts by severity."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/monitoring/alerts/", {"severity": "high"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.data["results"]:
            for alert in response.data["results"]:
                self.assertEqual(alert["severity"], "high")

    def test_list_status_filter(self):
        """Test filtering alerts by status."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/monitoring/alerts/", {"status": "open"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.data["results"]:
            for alert in response.data["results"]:
                self.assertEqual(alert["status"], "open")

    def test_list_source_filter(self):
        """Test filtering alerts by source."""
        from monitoring.models import MonitoringSource
        source = MonitoringSource.objects.first()
        if source:
            self.client.force_authenticate(user=self.admin_user)
            response = self.client.get("/api/monitoring/alerts/", {"source": source.pk})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            if response.data["results"]:
                for alert in response.data["results"]:
                    self.assertEqual(alert["source_name"], source.name)

    def test_list_system_admin_allowed(self):
        """Test System Admin can list alerts."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_employee_denied(self):
        """Test Employee is denied alert list access."""
        self.client.force_authenticate(user=self.employee)
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_inactive_user_denied(self):
        """Test Inactive user is denied alert list access."""
        self.client.force_authenticate(user=self.inactive_user)
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_anonymous_denied(self):
        """Test Anonymous user is denied alert list access."""
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_no_sensitive_fields(self):
        """Test that sensitive fields are absent from list response."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.data["results"]:
            result = response.data["results"][0]
            sensitive_fields = {"raw_payload", "event_body", "secret", "previous_secret",
                              "authorization", "cookie", "traceback", "exception_text"}
            for key in result.keys():
                self.assertNotIn(key, sensitive_fields, f"Sensitive field exposed: {key}")