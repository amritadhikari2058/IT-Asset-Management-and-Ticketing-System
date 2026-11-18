"""Focused route integration tests for Monitoring module."""
from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


class RouteIntegrationTests(APITestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="admin", email="a@t.test",
                                          employee_id="ROUTE-ADMIN",
                                          role="system_admin", is_staff=True, is_superuser=True)
        self.client.force_authenticate(self.a)

    def test_import(self):
        from monitoring import urls
        self.assertIsNotNone(urls)

    def test_alert_list(self):
        self.assertEqual(self.client.get("/api/monitoring/alerts/").status_code, 200)

    def test_alert_detail(self):
        from monitoring.models import MonitoringSource, MonitoringAlert
        s = MonitoringSource.objects.create(name="S", code="c", source_type="p")
        a = MonitoringAlert.objects.create(source=s, fingerprint="f", title="T", summary="S", severity="m", status="o")
        self.assertEqual(self.client.get(f"/api/monitoring/alerts/{a.pk}/").status_code, 200)

    def test_source_list(self):
        self.assertEqual(self.client.get("/api/monitoring/sources/").status_code, 200)

    def test_source_enable(self):
        from monitoring.models import MonitoringSource
        s = MonitoringSource.objects.create(name="E", code="en", source_type="p")
        self.assertIn(self.client.post(f"/api/monitoring/sources/{s.pk}/enable/").status_code, [200, 403])

    def test_source_disable(self):
        from monitoring.models import MonitoringSource
        s = MonitoringSource.objects.create(name="D", code="dis", source_type="p")
        self.assertIn(self.client.post(f"/api/monitoring/sources/{s.pk}/disable/").status_code, [200, 403])

    def test_source_rotate_secret(self):
        from monitoring.models import MonitoringSource
        s = MonitoringSource.objects.create(name="R", code="rot", source_type="p")
        self.assertIn(self.client.post(f"/api/monitoring/sources/{s.pk}/rotate-secret/").status_code, [200, 403])

    def test_source_test(self):
        from monitoring.models import MonitoringSource
        s = MonitoringSource.objects.create(name="T", code="t", source_type="p")
        self.assertIn(self.client.post(f"/api/monitoring/sources/{s.pk}/test/").status_code, [200, 403])

    def test_policy_list(self):
        self.assertEqual(self.client.get("/api/monitoring/automation-policies/").status_code, 200)

    def test_policy_detail(self):
        from monitoring.models import MonitoringAutomationPolicy
        p = MonitoringAutomationPolicy.objects.create(name="P", minimum_severity="l")
        self.assertEqual(self.client.get(f"/api/monitoring/automation-policies/{p.pk}/").status_code, 200)

    def test_no_duplicates(self):
        from django.urls import get_resolver
        names = set()
        for p in get_resolver().url_patterns:
            if hasattr(p, "name") and p.name:
                if p.name in names:
                    self.fail(f"Dup: {p.name}")
                names.add(p.name)