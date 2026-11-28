"""Real routed authentication tests for Monitoring user-facing APIs."""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from monitoring.models import MonitoringAutomationPolicy


class MonitoringRoutedAuthenticationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="monitor_auth_admin",
            email="monitor-auth-admin@example.test",
            employee_id="MON-AUTH-ADMIN",
            role="system_admin",
            is_staff=True,
            is_superuser=True,
        )
        self.manager = User.objects.create_user(
            username="monitor_auth_manager",
            email="monitor-auth-manager@example.test",
            employee_id="MON-AUTH-MANAGER",
            role="it_manager",
            is_staff=True,
        )
        self.support = User.objects.create_user(
            username="monitor_auth_support",
            email="monitor-auth-support@example.test",
            employee_id="MON-AUTH-SUPPORT",
            role="it_support",
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username="monitor_auth_employee",
            email="monitor-auth-employee@example.test",
            employee_id="MON-AUTH-EMPLOYEE",
            role="employee",
        )
        self.inactive_admin = User.objects.create_user(
            username="monitor_auth_inactive",
            email="monitor-auth-inactive@example.test",
            employee_id="MON-AUTH-INACTIVE",
            role="system_admin",
            is_active=False,
        )
        self.policy = MonitoringAutomationPolicy.objects.create(
            name="Routed Authentication Policy",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity="low",
            eligible_alert_states="open",
        )

    def client_for(self, user):
        client = APIClient()
        client.force_login(user)
        return client

    def test_dashboard_allows_admin_manager_and_support(self):
        for user in (self.admin, self.manager, self.support):
            with self.subTest(role=user.role):
                response = self.client_for(user).get("/api/monitoring/dashboard/")
                self.assertEqual(response.status_code, 200)

    def test_dashboard_denies_employee_inactive_and_anonymous(self):
        for user in (self.employee, self.inactive_admin):
            with self.subTest(username=user.username):
                response = self.client_for(user).get("/api/monitoring/dashboard/")
                self.assertIn(response.status_code, (401, 403) if not user.is_active else (403,))

        response = APIClient().get("/api/monitoring/dashboard/")
        self.assertIn(response.status_code, (401, 403))

    def test_policy_list_and_retrieve_allow_admin_manager_and_support(self):
        for user in (self.admin, self.manager, self.support):
            with self.subTest(role=user.role):
                client = self.client_for(user)
                self.assertEqual(
                    client.get("/api/monitoring/automation-policies/").status_code,
                    200,
                )
                self.assertEqual(
                    client.get(
                        f"/api/monitoring/automation-policies/{self.policy.pk}/"
                    ).status_code,
                    200,
                )

    def test_policy_list_denies_employee_inactive_and_anonymous(self):
        for user in (self.employee, self.inactive_admin):
            with self.subTest(username=user.username):
                response = self.client_for(user).get(
                    "/api/monitoring/automation-policies/"
                )
                self.assertIn(response.status_code, (401, 403) if not user.is_active else (403,))

        response = APIClient().get("/api/monitoring/automation-policies/")
        self.assertIn(response.status_code, (401, 403))

    def test_policy_write_is_limited_to_active_system_admin(self):
        payload = {
            "name": "Session Auth Created Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
        }

        for user in (self.manager, self.support, self.employee, self.inactive_admin):
            with self.subTest(username=user.username):
                response = self.client_for(user).post(
                    "/api/monitoring/automation-policies/",
                    data=payload,
                    format="json",
                )
                self.assertIn(response.status_code, (401, 403) if not user.is_active else (403,))

        response = self.client_for(self.admin).post(
            "/api/monitoring/automation-policies/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_alert_list_requires_authenticated_system_admin(self):
        response = self.client_for(self.admin).get("/api/monitoring/alerts/")
        self.assertEqual(response.status_code, 200)

        for user in (self.manager, self.support, self.employee, self.inactive_admin):
            with self.subTest(username=user.username):
                response = self.client_for(user).get("/api/monitoring/alerts/")
                self.assertIn(response.status_code, (401, 403) if not user.is_active else (403,))

        response = APIClient().get("/api/monitoring/alerts/")
        self.assertIn(response.status_code, (401, 403))
