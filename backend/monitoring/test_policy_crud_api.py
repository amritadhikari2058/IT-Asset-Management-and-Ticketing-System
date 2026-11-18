"""Focused tests for MonitoringAutomationPolicy CRUD API.

Tests the new serializer and ViewSet directly. Covers list, retrieve, create,
partial_update, activation/deactivation, and permission behavior.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from accounts.models import User

from monitoring.models import MonitoringAutomationPolicy, MonitoringSource
from monitoring.policy_serializers import MonitoringAutomationPolicySerializer


class PolicyCRUDApiTests(TestCase):
    """CRUD tests for MonitoringAutomationPolicy."""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin_user",
            email="admin@example.test",
            employee_id="POL-ADMIN",
            role="system_admin",
            is_staff=True,
            is_superuser=True,
        )
        self.it_manager = User.objects.create_user(
            username="it_manager_user",
            email="itmgr@example.test",
            employee_id="POL-MGR",
            role="it_manager",
            is_staff=True,
        )
        self.it_support = User.objects.create_user(
            username="it_support_user",
            email="itsup@example.test",
            employee_id="POL-SUP",
            role="it_support",
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username="employee_user",
            email="emp@example.test",
            employee_id="POL-EMP",
            role="employee",
            is_staff=False,
        )
        self.inactive_user = User.objects.create_user(
            username="inactive_user",
            email="inact@example.test",
            employee_id="POL-INACTIVE",
            role="it_support",
            is_active=False,
        )

        self.source = MonitoringSource.objects.create(name="Test Source", code="test-src")

    # --- List ---

    def test_list_system_admin_allowed(self):
        """System Admin can list policies."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        response = client.get("/api/monitoring/automation-policies/")
        self.assertEqual(response.status_code, 200)

    def test_list_it_manager_allowed(self):
        """IT Manager can list policies (read-only)."""
        client = APIClient()
        client.force_authenticate(user=self.it_manager)
        response = client.get("/api/monitoring/automation-policies/")
        self.assertEqual(response.status_code, 200)

    def test_list_it_support_allowed(self):
        """IT Support can list policies (read-only)."""
        client = APIClient()
        client.force_authenticate(user=self.it_support)
        response = client.get("/api/monitoring/automation-policies/")
        self.assertEqual(response.status_code, 200)

    def test_list_employee_denied(self):
        """Employee is denied policy list access."""
        client = APIClient()
        client.force_authenticate(user=self.employee)
        response = client.get("/api/monitoring/automation-policies/")
        self.assertEqual(response.status_code, 403)

    def test_list_inactive_user_denied(self):
        """Inactive user is denied policy list access."""
        client = APIClient()
        client.force_authenticate(user=self.inactive_user)
        response = client.get("/api/monitoring/automation-policies/")
        self.assertEqual(response.status_code, 403)

    def test_list_anonymous_denied(self):
        """Anonymous user is denied policy list access."""
        client = APIClient()
        response = client.get("/api/monitoring/automation-policies/")
        self.assertEqual(response.status_code, 403)

    # --- Retrieve ---

    def test_retrieve_system_admin_allowed(self):
        """System Admin can retrieve a policy."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Test Policy",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity="low",
            eligible_alert_states="open",
        )
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        response = client.get(f"/api/monitoring/automation-policies/{policy.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Test Policy")

    def test_retrieve_employee_denied(self):
        """Employee is denied policy retrieve access."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Test Policy",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
        )
        client = APIClient()
        client.force_authenticate(user=self.employee)
        response = client.get(f"/api/monitoring/automation-policies/{policy.pk}/")
        self.assertEqual(response.status_code, 403)

    def test_retrieve_inactive_user_denied(self):
        """Inactive user is denied policy retrieve access."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Test Policy",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
        )
        client = APIClient()
        client.force_authenticate(user=self.inactive_user)
        response = client.get(f"/api/monitoring/automation-policies/{policy.pk}/")
        self.assertEqual(response.status_code, 403)

    # --- Create ---

    def test_create_all_sources_policy(self):
        """System Admin can create an all-Sources policy."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "All Sources Policy",
            "description": "Policy applying to all sources",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "auto_create": True,
            "auto_update": True,
            "auto_resolve": True,
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(MonitoringAutomationPolicy.objects.filter(name="All Sources Policy").exists())

    def test_create_selective_policy(self):
        """System Admin can create a selective policy with sources."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Selective Policy",
            "description": "Policy for selective sources",
            "source_filter": "selective",
            "minimum_severity": "medium",
            "eligible_alert_states": "new",
            "eligible_sources": [self.source.pk],
            "auto_create": True,
            "auto_update": False,
            "auto_resolve": True,
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(MonitoringAutomationPolicy.objects.filter(name="Selective Policy").exists())

    def test_create_selective_without_sources_rejected(self):
        """Selective policy without sources is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Selective Policy",
            "description": "Selective policy with no sources",
            "source_filter": "selective",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            # no eligible_sources
            "auto_create": True,
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_effective_date_range_rejected(self):
        """Invalid effective date range is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Date Policy",
            "effective_from": (timezone.now() + timezone.timedelta(days=10)).isoformat(),
            "effective_until": (timezone.now() + timezone.timedelta(days=1)).isoformat(),
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_severity_rejected(self):
        """Invalid severity is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Severity Policy",
            "source_filter": "all",
            "minimum_severity": "criticality",  # invalid
            "eligible_alert_states": "open",
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_alert_state_rejected(self):
        """Invalid alert state is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad State Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "invalid_state",  # invalid
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_target_service_rejected(self):
        """Invalid target service is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Service Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "target_service": "invalid@service!",  # invalid characters
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_ticket_category_rejected(self):
        """Invalid ticket category is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Category Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "ticket_category": "NonExistent Category",
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_priority_rejected(self):
        """Invalid priority is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Priority Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "default_priority": "non-existent-priority",
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_reopen_behavior_rejected(self):
        """Invalid reopen behavior is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Bad Reopen Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "reopen_behavior": "invalid_behavior",
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_retry_count_below_range_rejected(self):
        """Retry count below range is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "Low Retry Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "maximum_retries": -1,  # below range
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_retry_count_above_range_rejected(self):
        """Retry count above range is rejected."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {
            "name": "High Retry Policy",
            "source_filter": "all",
            "minimum_severity": "low",
            "eligible_alert_states": "open",
            "maximum_retries": 150,  # above range
        }
        response = client.post("/api/monitoring/automation-policies/", data=data, format="json")
        self.assertEqual(response.status_code, 400)

    # --- Activation and Deactivation ---

    def test_activate_policy(self):
        """System Admin can activate a policy (via is_active update)."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="To Be Active Policy",
            is_active=False,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity="low",
        )
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        # Update is_active to True
        data = {"is_active": True}
        response = client.patch(f"/api/monitoring/automation-policies/{policy.pk}/", data=data, format="json")
        self.assertEqual(response.status_code, 200)
        policy.refresh_from_db()
        self.assertTrue(policy.is_active)

    # --- Delete/Deactivation Behavior ---

    def test_delete_policy_with_linked_alerts_deactivates(self):
        """Delete policy with linked alerts deactivates it."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Policy With History",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity="low",
        )
        # Create a linked alert
        from monitoring.models import MonitoringAlert
        source = MonitoringSource.objects.create(name="Test Source", code="history-src")
        alert = MonitoringAlert.objects.create(
            source=source,
            fingerprint="history_alert_001",
            title="History Alert",
            summary="Alert linked to policy",
            severity="medium",
            status="open",
            policy=policy,
        )

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        response = client.delete(f"/api/monitoring/automation-policies/{policy.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["action"], "deactivated")
        # Policy should be inactive, not deleted
        policy.refresh_from_db()
        self.assertFalse(policy.is_active)

    def test_delete_policy_without_linked_alerts_deletes(self):
        """Delete policy without linked alerts performs hard delete."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Clean Policy",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity="low",
        )

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        response = client.delete(f"/api/monitoring/automation-policies/{policy.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["action"], "deleted")
        # Policy should be deleted
        self.assertFalse(MonitoringAutomationPolicy.objects.filter(pk=policy.pk).exists())

    # --- Partial Update ---

    def test_partial_update(self):
        """System Admin can partially update a policy."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Original Policy",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity="info",
            eligible_alert_states="open",
            default_priority="low",
            default_queue="default",
            default_assignee=None,
            reopen_behavior="",
            maximum_retries=3,
        )
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        data = {"minimum_severity": "high"}
        response = client.patch(f"/api/monitoring/automation-policies/{policy.pk}/", data=data, format="json")
        self.assertEqual(response.status_code, 200)
        policy.refresh_from_db()
        self.assertEqual(policy.minimum_severity, "high")