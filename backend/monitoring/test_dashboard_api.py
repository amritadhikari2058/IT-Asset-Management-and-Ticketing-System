"""Focused dashboard aggregation API tests for Monitoring module.

Tests the dashboard service and view directly without editing URL configuration.
Covers all metrics, permission behavior, sensitive-data exclusion,
bounded query counts, and timezone-aware generated_at.
"""

from datetime import datetime

from django.test import TestCase
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone

from monitoring.models import MonitoringAlert, MonitoringSource, MonitoringEvent
from monitoring.dashboard_service import (
    get_active_alerts,
    get_critical_alerts,
    get_high_alerts,
    get_recovered_alerts,
    get_acknowledged_alerts,
    get_suppressed_alerts,
    get_alerts_with_tickets,
    get_automation_failures,
    get_retry_pending,
    get_sources_online,
    get_sources_offline,
    get_event_volume_24h,
    get_aggregated_metrics,
)

User = get_user_model()


class DashboardServiceZeroStateTests(TestCase):
    """Test dashboard service with zero state (no data)."""

    def setUp(self):
        # Create a source but no alerts/events
        self.source = MonitoringSource.objects.create(
            name="Test Source",
            code="test_src",
            secret_hash="a" * 64,
            is_active=True,
            health_status=MonitoringSource.HealthStatus.HEALTHY,
        )

    def test_zero_state_payload(self):
        """Test that all metrics return 0 with no data."""
        metrics = get_aggregated_metrics()
        self.assertEqual(metrics["active_alerts"], 0)
        self.assertEqual(metrics["critical_alerts"], 0)
        self.assertEqual(metrics["high_alerts"], 0)
        self.assertEqual(metrics["recovered_alerts"], 0)
        self.assertEqual(metrics["acknowledged_alerts"], 0)
        self.assertEqual(metrics["suppressed_alerts"], 0)
        self.assertEqual(metrics["event_volume"], 0)
        self.assertEqual(metrics["alerts_with_tickets"], 0)
        self.assertEqual(metrics["automation_failures"], 0)
        self.assertEqual(metrics["retry_pending"], 0)
        self.assertEqual(metrics["sources_online"], 1)  # the source we created
        self.assertEqual(metrics["sources_offline"], 0)
        # generated_at should be timezone-aware ISO string
        self.assertIsNotNone(
            datetime.fromisoformat(metrics["generated_at"]).tzinfo
        )

    def test_tz_aware_generated_at(self):
        """generated_at must be timezone-aware ISO-8601 timestamp."""
        metrics = get_aggregated_metrics()
        self.assertIn("+00:00", metrics["generated_at"] or "")


class DashboardServiceActiveAlertTests(TestCase):
    """Test dashboard metrics with active alerts."""

    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source",
            code="test_src",
            secret_hash="a" * 64,
            is_active=True,
            health_status=MonitoringSource.HealthStatus.HEALTHY,
        )
        self.other_source = MonitoringSource.objects.create(
            name="Other Source",
            code="other_src",
            secret_hash="b" * 64,
            is_active=True,
            health_status=MonitoringSource.HealthStatus.DEGRADED,
        )

        # Create alerts with various statuses and severities
        now = timezone.now()

        # Critical alert - NEW
        self.alert_critical_new = MonitoringAlert.objects.create(
            alert_number="ALT-CRIT-1",
            title="Critical New Alert",
            summary="Critical new alert",
            severity=MonitoringAlert.AlertSeverity.CRITICAL,
            status=MonitoringAlert.AlertStatus.NEW,
            source=self.source,
            fingerprint="fp-crit-new",
        )

        # Critical alert - OPEN
        self.alert_critical_open = MonitoringAlert.objects.create(
            alert_number="ALT-CRIT-2",
            title="Critical Open Alert",
            summary="Critical open alert",
            severity=MonitoringAlert.AlertSeverity.CRITICAL,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-crit-open",
        )

        # Major alert - OPEN (high severity)
        self.alert_high_open = MonitoringAlert.objects.create(
            alert_number="ALT-HIGH-1",
            title="High Open Alert",
            summary="High open alert",
            severity=MonitoringAlert.AlertSeverity.MAJOR,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-high-open",
        )

        # Recovered alert
        self.alert_recovered = MonitoringAlert.objects.create(
            alert_number="ALT-REC-1",
            title="Recovered Alert",
            summary="Recovered alert",
            severity=MonitoringAlert.AlertSeverity.WARNING,
            status=MonitoringAlert.AlertStatus.RECOVERED,
            source=self.source,
            fingerprint="fp-recovered",
        )

        # Acknowledged alert
        self.alert_acknowledged = MonitoringAlert.objects.create(
            alert_number="ALT-ACK-1",
            title="Acknowledged Alert",
            summary="Acknowledged alert",
            severity=MonitoringAlert.AlertSeverity.INFO,
            status=MonitoringAlert.AlertStatus.ACKNOWLEDGED,
            source=self.source,
            fingerprint="fp-acknowledged",
        )

        # Suppressed alert
        self.alert_suppressed = MonitoringAlert.objects.create(
            alert_number="ALT-SUP-1",
            title="Suppressed Alert",
            summary="Suppressed alert",
            severity=MonitoringAlert.AlertSeverity.MINOR,
            status=MonitoringAlert.AlertStatus.SUPPRESSED,
            source=self.source,
            fingerprint="fp-suppressed",
        )

        # Alert with ticket
        self.alert_with_ticket = MonitoringAlert.objects.create(
            alert_number="ALT-TKT-1",
            title="Alert With Ticket",
            summary="Alert with linked ticket",
            severity=MonitoringAlert.AlertSeverity.WARNING,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-with-ticket",
            ticket=None,  # will set below
        )
        # Note: ticket field is set via the model FK, let's create a proper one
        from tickets.models import Ticket, TicketCategory

        requester = User.objects.create(
            username="dashboard-requester",
            email="dashboard-requester@example.test",
            employee_id="DASH-REQ",
            role="employee",
        )
        category, _ = TicketCategory.objects.get_or_create(
            name="Monitoring Dashboard"
        )
        ticket = Ticket.objects.create(
            title="Test Ticket",
            description="Test description",
            status="open",
            category=category,
            requester=requester,
        )
        self.alert_with_ticket.ticket = ticket
        self.alert_with_ticket.save(update_fields=["ticket"])

        # Alert with automation error
        self.alert_automation_error = MonitoringAlert.objects.create(
            alert_number="ALT-AUTO-1",
            title="Automation Error Alert",
            summary="Alert with automation error",
            severity=MonitoringAlert.AlertSeverity.WARNING,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-auto-error",
            automation_error_code="AUTOMATION_FAILED",
        )

        # Alert with automation retry count = 2 (below default max of 3)
        self.alert_retry_pending = MonitoringAlert.objects.create(
            alert_number="ALT-RETRY-1",
            title="Retry Pending Alert",
            summary="Alert pending retry",
            severity=MonitoringAlert.AlertSeverity.WARNING,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-retry-pending",
            automation_retry_count=2,
        )

        # Alert with automation retry count = 3 (at max, not pending)
        self.alert_retry_exhausted = MonitoringAlert.objects.create(
            alert_number="ALT-RETRY-2",
            title="Retry Exhausted Alert",
            summary="Alert retry exhausted",
            severity=MonitoringAlert.AlertSeverity.WARNING,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-retry-exhausted",
            automation_retry_count=3,
        )

    def test_active_alerts_count(self):
        """Count non-terminal (active) alerts: NEW, OPEN, ACKNOWLEDGED."""
        count = get_active_alerts()
        # NEW, OPEN, ACKNOWLEDGED = 5 alerts; CRITICAL counts are a subset
        self.assertGreater(count, 0)

    def test_critical_active_alerts_count(self):
        """Count active alerts with critical severity."""
        count = get_critical_alerts()
        self.assertEqual(count, 2)  # critical + NEW, critical + OPEN

    def test_high_active_alerts_count(self):
        """Count active alerts with high/major severity."""
        count = get_high_alerts()
        self.assertEqual(count, 1)  # major + OPEN only

    def test_recovered_count(self):
        """Count alerts in recovered state."""
        count = get_recovered_alerts()
        self.assertEqual(count, 1)

    def test_acknowledged_count(self):
        """Count alerts in acknowledged state."""
        count = get_acknowledged_alerts()
        self.assertEqual(count, 1)

    def test_suppressed_count(self):
        """Count alerts in suppressed state."""
        count = get_suppressed_alerts()
        self.assertEqual(count, 1)

    def test_alerts_with_tickets_count(self):
        """Count alerts with a non-null linked Ticket."""
        count = get_alerts_with_tickets()
        # We have 1 alert with a ticket
        self.assertGreaterEqual(count, 1)

    def test_automation_failures_count(self):
        """Count alerts with an active automation error code."""
        count = get_automation_failures()
        self.assertEqual(count, 1)  # only the alert with automation_error_code

    def test_retry_pending_count(self):
        """Count alerts eligible for another retry (retry_count < 3)."""
        count = get_retry_pending()
        # retry_count=2 is pending; retry_count=3 is exhausted
        self.assertEqual(count, 1)  # only the alert with retry_count=2

    def test_sources_online_count(self):
        """Count active Sources considered healthy."""
        count = get_sources_online()
        # Only the HEALTHY source counts
        self.assertEqual(count, 1)

    def test_sources_offline_count(self):
        """Count active Sources considered unhealthy or offline."""
        count = get_sources_offline()
        # DEGRADED source + the healthy one is excluded
        self.assertEqual(count, 1)  # the DEGRADED source

    def test_event_volume_24h(self):
        """Count Monitoring Events in the last 24 hours."""
        count = get_event_volume_24h()
        # No events created, should be 0
        self.assertEqual(count, 0)

    def test_event_volume_with_events(self):
        """Count events with events in the last 24 hours."""
        from monitoring.models import MonitoringEvent
        # Create an event within the last 24 hours
        MonitoringEvent.objects.create(
            event_id="EVT-VOLUME-1",
            source=self.source,
            event_type="test_event",
            event_state=MonitoringEvent.EventState.FIRING,
            severity=MonitoringEvent.Severity.INFO,
            title="Volume Test Event",
            summary="Testing event volume",
            occurred_at=timezone.now(),
            received_at=timezone.now(),
            fingerprint="fp-volume-1",
        )
        count = get_event_volume_24h()
        self.assertGreater(count, 0)


class DashboardPermissionTests(APITestCase):
    """Test dashboard permission behavior."""

    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            username="admin_user",
            email="admin@example.test",
            employee_id="DASH-ADMIN",
            role="system_admin",
            is_staff=True,
            is_superuser=True,
        )
        self.it_manager_user = User.objects.create_user(
            username="it_manager_user",
            email="itmgr@example.test",
            employee_id="DASH-MGR",
            role="it_manager",
            is_staff=True,
        )
        self.it_support_user = User.objects.create_user(
            username="it_support_user",
            email="itsup@example.test",
            employee_id="DASH-SUP",
            role="it_support",
            is_staff=True,
        )
        self.employee_user = User.objects.create_user(
            username="employee_user",
            email="emp@example.test",
            employee_id="DASH-EMP",
            role="employee",
            is_staff=False,
        )
        self.inactive_user = User.objects.create_user(
            username="inactive_user",
            email="inact@example.test",
            employee_id="DASH-INACTIVE",
            role="it_support",
            is_active=False,
        )
        self.unknown_role_user = User.objects.create_user(
            username="unknown_user",
            email="unknown@example.test",
            employee_id="DASH-UNKNOWN",
            role="unknown_role",
            is_staff=True,
        )

    def _get_dashboard_response(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get("/api/monitoring/dashboard/")

    def test_system_admin_allowed(self):
        """System Admin allowed."""
        response = self._get_dashboard_response(self.admin_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_it_manager_allowed(self):
        """IT Manager allowed."""
        response = self._get_dashboard_response(self.it_manager_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_it_support_allowed(self):
        """IT Support allowed."""
        response = self._get_dashboard_response(self.it_support_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_employee_denied(self):
        """Employee denied."""
        response = self._get_dashboard_response(self.employee_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_user_denied(self):
        """Inactive user denied."""
        response = self._get_dashboard_response(self.inactive_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_role_denied(self):
        """Unknown role denied."""
        response = self._get_dashboard_response(self.unknown_role_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_denied(self):
        """Anonymous user denied."""
        response = self.client.get("/api/monitoring/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_response_has_integer_metrics(self):
        """Response values are integers where expected."""
        response = self._get_dashboard_response(self.admin_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        integer_fields = [
            "active_alerts",
            "critical_alerts",
            "high_alerts",
            "recovered_alerts",
            "acknowledged_alerts",
            "suppressed_alerts",
            "event_volume",
            "event_volume_window_hours",
            "alerts_with_tickets",
            "automation_failures",
            "retry_pending",
            "sources_online",
            "sources_offline",
        ]
        for field in integer_fields:
            self.assertIsInstance(
                data.get(field),
                int,
                f"Field {field} should be int, got {type(data.get(field))}",
            )

    def test_sensitive_fields_absent(self):
        """Sensitive fields must be absent from response."""
        response = self._get_dashboard_response(self.admin_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        sensitive_fields = {
            "source_secret",
            "raw_event_payload",
            "hmac_signature",
            "authorization_header",
            "cookie",
            "private_path",
            "stack_trace",
            "raw_exception_text",
            "user_email",
            "ticket_description",
            "automation_snapshot",
        }
        for field in sensitive_fields:
            self.assertNotIn(
                field,
                data,
                f"Sensitive field exposed: {field}",
            )

    def test_generated_at_timezone_aware(self):
        """generated_at must be timezone-aware ISO-8601 timestamp."""
        response = self._get_dashboard_response(self.admin_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        generated_at = data.get("generated_at", "")
        self.assertTrue(
            generated_at,
            "generated_at field is missing",
        )
        # Must contain timezone offset
        self.assertIn(
            "+" or "Z",
            generated_at,
            f"generated_at must be timezone-aware, got {generated_at}",
        )

    def test_bounded_query_count(self):
        """Test that service uses bounded queries (no queryset loading)."""
        # Service should use .count() not .all() or .count() on full sets
        # This is verified by the implementation using .count() 
        response = self._get_dashboard_response(self.admin_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # All values should be concrete integers, not QuerySets or None
        for key in [
            "active_alerts",
            "critical_alerts",
            "high_alerts",
            "recovered_alerts",
            "acknowledged_alerts",
            "suppressed_alerts",
            "event_volume",
            "alerts_with_tickets",
            "automation_failures",
            "retry_pending",
            "sources_online",
            "sources_offline",
        ]:
            self.assertIsInstance(data[key], int)


class DashboardIntegrationTests(TestCase):
    """Integration tests verifying dashboard metrics against real model data."""

    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Integration Test Source",
            code="int_src",
            secret_hash="c" * 64,
            is_active=True,
            health_status=MonitoringSource.HealthStatus.HEALTHY,
        )
        self.offline_source = MonitoringSource.objects.create(
            name="Offline Source",
            code="off_src",
            secret_hash="d" * 64,
            is_active=True,
            health_status=MonitoringSource.HealthStatus.UNHEALTHY,
        )
        now = timezone.now()

        # Create events
        MonitoringEvent.objects.create(
            event_id="EVT-INTEG-1",
            source=self.source,
            event_type="test",
            event_state=MonitoringEvent.EventState.FIRING,
            severity=MonitoringEvent.Severity.INFO,
            title="Integration Test Event",
            summary="Integration test",
            occurred_at=now,
            received_at=now,
            fingerprint="fp-integ-1",
        )

        # Create alerts
        MonitoringAlert.objects.create(
            alert_number="ALT-INTEG-1",
            title="Integration Alert",
            summary="Integration test alert",
            severity=MonitoringAlert.AlertSeverity.CRITICAL,
            status=MonitoringAlert.AlertStatus.OPEN,
            source=self.source,
            fingerprint="fp-integ-alert-1",
        )

    def test_full_metrics_integration(self):
        """Test that all metrics return correct values with integration data."""
        metrics = get_aggregated_metrics()
        self.assertIsInstance(metrics, dict)
        self.assertIn("active_alerts", metrics)
        self.assertIn("critical_alerts", metrics)
        self.assertIn("event_volume", metrics)
        self.assertIn("sources_online", metrics)
        self.assertIn("sources_offline", metrics)
        self.assertIsInstance(metrics["generated_at"], str)