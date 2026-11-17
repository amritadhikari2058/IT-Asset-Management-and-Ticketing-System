"""Real Ticket automation tests for Monitoring Phase 2."""

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from monitoring.models import MonitoringSource, MonitoringAlert, MonitoringAutomationPolicy
from monitoring.ticket_automation import MonitoringAutomationPolicyValidator
from tickets.models import Ticket


class PolicyTestCase(TestCase):
    """Policy eligibility validation tests for Monitoring Automation Policy."""

    def setUp(self):
        self.source = MonitoringSource.objects.create(name="Test", code="test")

    # --- no active policy -------------------------------------------------
    def test_no_active_policy_fails_closed(self):
        """Alert with no active policy should be ineligible."""
        alert = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint="pol_no_policy_001",
            title="No Policy Alert",
            summary="No active policy applies",
            severity="medium",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "no active policy")
        # No Ticket should be created
        self.assertFalse(Ticket.objects.exists())

    # --- disabled policy ---------------------------------------------------
    def test_disabled_policy_fails_closed(self):
        """Disabled policy should cause ineligibility."""
        policy = MonitoringAutomationPolicy.objects.create(
            name="Disabled Policy",
            is_active=False,
            minimum_severity="low",
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
        )
        alert = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint="pol_disabled_001",
            title="Disabled Policy Alert",
            summary="Policy is disabled",
            severity="medium",
            status="open",
            policy=policy,
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "no active policy")
        self.assertIs(result["policy"], policy)
        self.assertFalse(Ticket.objects.exists())

    # --- effective date tests ----------------------------------------------
    def test_policy_before_effective_date_fails_closed(self):
        "Policy with effective_from in the future should be ineligible."
        source = MonitoringSource.objects.create(
            name="Future Policy Source", code="future_pol"
        )
        now = timezone.now()
        policy = MonitoringAutomationPolicy.objects.create(
            name="Future Policy",
            description="Policy effective from the future",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.SELECTIVE,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="opsgenie",
            effective_from=now + timedelta(days=1),
            effective_until=None,
        )
        alert = MonitoringAlert.objects.create(
            source=source,
            fingerprint="fp:future:policy",
            title="Future Policy Alert",
            summary="Test",
            severity="high",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertIn("effective", result.get("reason", "").lower())
        self.assertIsNone(result.get("policy"))

    def test_policy_after_expiry_fails_closed(self):
        "Policy with effective_until in the past should be ineligible."
        source = MonitoringSource.objects.create(
            name="Expired Policy Source", code="expired_pol"
        )
        now = timezone.now()
        policy = MonitoringAutomationPolicy.objects.create(
            name="Expired Policy",
            description="Policy past its expiry",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="pagerduty",
            effective_from=None,
            effective_until=now - timedelta(seconds=1),
        )
        alert = MonitoringAlert.objects.create(
            source=source,
            fingerprint="fp:expired:policy",
            title="Expired Policy Alert",
            summary="Test",
            severity="high",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertIn("effective", result.get("reason", "").lower() or "expired" in result.get("reason", "").lower())
        self.assertIsNone(result.get("policy"))

    # --- selective-source tests ------------------------------------------
    def test_selective_source_rejects_unlisted_source(self):
        "SELECTIVE policy should reject alerts from unlisted sources."
        source_a = MonitoringSource.objects.create(
            name="Listed Source", code="list_a"
        )
        source_b = MonitoringSource.objects.create(
            name="Unlisted Source", code="unlisted_b"
        )
        policy = MonitoringAutomationPolicy.objects.create(
            name="Selective Policy",
            description="Only listed sources",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.SELECTIVE,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="service_now",
        )
        policy.eligible_sources.add(source_a)
        policy.save()
        alert = MonitoringAlert.objects.create(
            source=source_b,
            fingerprint="fp:unlisted:source",
            title="Unlisted Source Alert",
            summary="Test",
            severity="high",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertIn("source", result.get("reason", "").lower())
        self.assertIsNone(result.get("policy"))
        self.assertIsNone(alert.ticket)

    def test_selective_source_accepts_listed_source(self):
        "SELECTIVE policy should accept alerts from listed sources."
        source_a = MonitoringSource.objects.create(
            name="Listed Source", code="list_a"
        )
        policy = MonitoringAutomationPolicy.objects.create(
            name="Selective Policy",
            description="Only listed sources",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.SELECTIVE,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="service_now",
        )
        policy.eligible_sources.add(source_a)
        policy.save()
        alert = MonitoringAlert.objects.create(
            source=source_a,
            fingerprint="fp:listed:source",
            title="Listed Source Alert",
            summary="Test",
            severity="high",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertTrue(result["eligible"])
        self.assertIsNone(result.get("reason"))
        self.assertIsNotNone(result.get("policy"))

    # --- severity tests --------------------------------------------------
    def test_severity_below_threshold_is_rejected(self):
        "Alert with severity below policy minimum should be rejected."
        policy = MonitoringAutomationPolicy.objects.create(
            name="High Threshold Policy",
            description="Only high and critical",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="pagerduty",
        )
        alert = MonitoringAlert.objects.create(
            source=None,
            fingerprint="fp:low:sev",
            title="Low Severity Alert",
            summary="Test",
            severity="medium",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertIn("severity", result.get("reason", "").lower())
        self.assertIsNone(result.get("policy"))

    def test_eligible_severity_is_accepted(self):
        "Alert with severity at or above policy threshold should be eligible."
        policy = MonitoringAutomationPolicy.objects.create(
            name="High Threshold Policy",
            description="Only high and critical",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="pagerduty",
        )
        alert = MonitoringAlert.objects.create(
            source=None,
            fingerprint="fp:critical:sev",
            title="Critical Severity Alert",
            summary="Test",
            severity="critical",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertTrue(result["eligible"])
        self.assertIsNone(result.get("reason"))
        self.assertIsNotNone(result.get("policy"))

    # --- alert-state test ------------------------------------------------
    def test_ineligible_alert_state_is_rejected(self):
        "Alert with state not in policy's eligible states should be rejected."
        policy = MonitoringAutomationPolicy.objects.create(
            name="State-Restricted Policy",
            description="Only open alerts",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.INFO,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="service_now",
        )
        alert = MonitoringAlert.objects.create(
            source=None,
            fingerprint="fp:acked:state",
            title="Acknowledged Alert",
            summary="Test",
            severity="info",
            status="acknowledged",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        self.assertIn("state", result.get("reason", "").lower())
        self.assertIsNone(result.get("policy"))

    # --- invalid service-mapping test ------------------------------------
    def test_invalid_service_mapping_fails_safely(self):
        "Invalid target_service mapping should return ineligible result safely."
        policy = MonitoringAutomationPolicy.objects.create(
            name="Service-Mapped Policy",
            description="With service mapping",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.INFO,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="invalid@service!name",
        )
        alert = MonitoringAlert.objects.create(
            source=None,
            fingerprint="fp:bad:svc",
            title="Bad Service Mapping Alert",
            summary="Test",
            severity="info",
            status="open",
        )
        result = MonitoringAutomationPolicyValidator.check_alert_eligibility(alert)
        self.assertFalse(result["eligible"])
        # Should not raise an exception
        self.assertIsNone(result.get("policy"))