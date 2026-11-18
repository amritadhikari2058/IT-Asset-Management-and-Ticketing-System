"""Real Ticket automation tests for Monitoring Phase 2."""

import inspect
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, User
from common.models import Notification
from common.notifications import notify_user, notify_watchers
from monitoring import ticket_automation
from monitoring.models import (
    MonitoringAlert,
    MonitoringAlertHistory,
    MonitoringAutomationPolicy,
    MonitoringEvent,
    MonitoringSource,
    TargetMapping,
)
from monitoring.ticket_automation import (
    MonitoringAutomationPolicyValidator,
    ensure_ticket_for_alert,
    process_alerts_for_ticket_automation,
    resolve_ticket_for_recovered_alert,
    retry_failed_ticket_automation,
    sync_ticket_from_alert,
)
from services.models import ServiceCatalogueItem
from tickets.models import (
    Ticket,
    TicketCategory,
    TicketHistory,
    TicketQueue,
    TicketResolutionCode,
    TicketWatcher,
)


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


class AutomationFixture(TestCase):
    """Shared real-service fixtures for Phase 2 automation tests."""

    def setUp(self):
        self.department = Department.objects.create(name="Monitoring Ops", code="MON")
        self.actor = User.objects.create_user(
            username="mon-admin", email="mon-admin@example.test",
            employee_id="MON-A", password="pw12345678",
            role="system_admin", home_department=self.department,
        )
        self.assignee = User.objects.create_user(
            username="mon-agent", email="mon-agent@example.test",
            employee_id="MON-B", password="pw12345678",
            role="it_support", home_department=self.department,
        )
        self.employee = User.objects.create_user(
            username="mon-user", email="mon-user@example.test",
            employee_id="MON-C", password="pw12345678",
            role="employee", home_department=self.department,
        )
        self.inactive = User.objects.create_user(
            username="mon-inactive", email="mon-inactive@example.test",
            employee_id="MON-D", password="pw12345678",
            role="it_support", home_department=self.department, is_active=False,
        )

        self.source = MonitoringSource.objects.create(
            name="Prometheus", code="prom", secret_hash="a" * 64
        )
        self.source_b = MonitoringSource.objects.create(
            name="Grafana", code="grafana", secret_hash="b" * 64
        )
        self.service = ServiceCatalogueItem.objects.create(
            name="Production Service", category="software", is_active=True
        )
        self.service_b = ServiceCatalogueItem.objects.create(
            name="Secondary Service", category="software", is_active=True
        )
        self.category = TicketCategory.objects.create(name="Monitoring")
        self.category_b = TicketCategory.objects.create(name="Manual Category")
        self.queue = TicketQueue.objects.create(
            name="Monitoring Queue", code="MONQ",
            department=self.department, is_active=True,
        )
        self.queue_b = TicketQueue.objects.create(
            name="Manual Queue", code="MANQ",
            department=self.department, is_active=True,
        )
        self.resolution_code = TicketResolutionCode.objects.create(
            name="Monitoring recovered", code="monitoring_recovered",
            requires_summary=False,
        )
        self.policy = MonitoringAutomationPolicy.objects.create(
            name="Default automation policy",
            is_active=True,
            source_filter=MonitoringAutomationPolicy.SourceFilter.ALL,
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            target_service="Production Service",
            ticket_category="Monitoring",
            default_priority="high",
            default_queue="MONQ",
            default_assignee=self.assignee,
            auto_create=True,
            auto_update=True,
            auto_resolve=True,
            reopen_behavior="reopen",
            maximum_retries=3,
        )
        self.policy.eligible_sources.add(self.source)
        self._alert_sequence = 0

    def _alert(self, key="a", **overrides):
        self._alert_sequence += 1
        defaults = {
            "alert_number": f"ALT{self._alert_sequence:08d}",
            "source": self.source,
            "policy": self.policy,
            "fingerprint": f"automation:{key}",
            "correlation_key": f"key:{key}",
            "title": f"Alert {key}",
            "summary": f"High latency for {key}",
            "severity": "critical",
            "status": "open",
        }
        defaults.update(overrides)
        return MonitoringAlert.objects.create(**defaults)

    def _event(self, key="e", **overrides):
        defaults = {
            "event_id": f"evt-{key}",
            "source": self.source,
            "event_type": "latency",
            "event_state": MonitoringEvent.EventState.FIRING,
            "severity": MonitoringEvent.Severity.CRITICAL,
            "title": f"Event {key}",
            "summary": f"Spike {key}",
            "occurred_at": timezone.now(),
            "fingerprint": f"event-fp-{key}",
            "raw_payload_hash": f"hash-{key}",
        }
        defaults.update(overrides)
        return MonitoringEvent.objects.create(**defaults)

    def _create_linked_ticket(self, alert=None):
        alert = alert or self._alert()
        with self.captureOnCommitCallbacks(execute=True):
            ticket, created = ensure_ticket_for_alert(alert)
        self.assertTrue(created)
        alert.refresh_from_db()
        return alert, ticket

    def _history_count(self, ticket, action):
        return TicketHistory.objects.filter(ticket=ticket, action=action).count()

    def _fail_creation(self, alert, secret="RAW-EXCEPTION-SECRET"):
        with patch.object(
            ticket_automation, "_resolve_queue", side_effect=ValueError(secret)
        ):
            with self.captureOnCommitCallbacks(execute=True):
                return ensure_ticket_for_alert(alert)


class TicketCreationTests(AutomationFixture):
    def test_eligible_alert_creates_exactly_one_ticket_and_link(self):
        alert = self._alert("create-one")
        with self.captureOnCommitCallbacks(execute=True):
            ticket, created = ensure_ticket_for_alert(alert)
        self.assertTrue(created)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(alert.ticket_id, ticket.pk)
        self.assertTrue(alert.auto_ticket_created)
        self.assertEqual(ticket.status, "open")

    def test_existing_ticket_model_is_used_and_title_is_bounded(self):
        alert = self._alert("long-title", title="X" * 500)
        with self.captureOnCommitCallbacks(execute=True):
            ticket, _created = ensure_ticket_for_alert(alert)
        self.assertIsInstance(ticket, Ticket)
        self.assertLessEqual(len(ticket.title), 255)
        self.assertIn("Ticket.objects.create(", inspect.getsource(ensure_ticket_for_alert))
        self.assertEqual(Ticket.objects.get(pk=ticket.pk).title, ticket.title)

    def test_description_has_safe_summary_only(self):
        event = self._event(
            "secrets",
            normalized_payload={
                "password": "hunter2",
                "signature": "sig-abcdef",
                "api_key": "key-xyz",
            },
            metadata={"raw_payload": {"authorization": "Bearer TOPSECRET"}},
        )
        alert = self._alert(
            "safe-summary",
            summary="CPU high token=abc123 signature=sig-xyz password=pw999",
            latest_event=event,
        )
        with self.captureOnCommitCallbacks(execute=True):
            ticket, _created = ensure_ticket_for_alert(alert)
        self.assertIn("CPU high", ticket.description)
        for secret in ("hunter2", "sig-abcdef", "key-xyz", "TOPSECRET", "abc123", "pw999"):
            self.assertNotIn(secret, ticket.description)

    def test_priority_mapping_is_deterministic(self):
        self.policy.default_priority = ""
        self.policy.minimum_severity = MonitoringAutomationPolicy.MinimumSeverity.INFO
        self.policy.save(update_fields=["default_priority", "minimum_severity"])
        major = self._alert("major", severity="major")
        warning = self._alert("warning", severity="warning")
        with self.captureOnCommitCallbacks(execute=True):
            major_ticket, _ = ensure_ticket_for_alert(major)
            warning_ticket, _ = ensure_ticket_for_alert(warning)
        self.assertEqual(major_ticket.priority, "high")
        self.assertEqual(warning_ticket.priority, "medium")

    def test_service_category_queue_and_assignee_mapping(self):
        alert = self._alert("mappings")
        with self.captureOnCommitCallbacks(execute=True):
            ticket, _created = ensure_ticket_for_alert(alert)
        self.assertEqual(ticket.category_id, self.category.pk)
        self.assertEqual(ticket.queue_id, self.queue.pk)
        self.assertEqual(ticket.assignee_id, self.assignee.pk)
        self.assertEqual(alert.service_catalogue_item_id, self.service.pk)
        self.assertEqual(alert.category, "Monitoring")
        self.assertEqual(alert.queue, "MONQ")

    def test_inactive_default_assignee_is_not_assigned(self):
        self.policy.default_assignee = self.inactive
        self.policy.save(update_fields=["default_assignee"])
        alert = self._alert("inactive-assignee")
        with self.captureOnCommitCallbacks(execute=True):
            ticket, _created = ensure_ticket_for_alert(alert)
        self.assertIsNone(ticket.assignee_id)

    def test_exactly_one_success_history_event_is_written(self):
        alert = self._alert("history-one")
        with self.captureOnCommitCallbacks(execute=True):
            ticket, _created = ensure_ticket_for_alert(alert)
        self.assertEqual(self._history_count(ticket, "created_from_monitoring_alert"), 1)
        self.assertEqual(
            MonitoringAlertHistory.objects.filter(
                alert=alert,
                event_type=MonitoringAlertHistory.EventType.TICKET_CREATED,
            ).count(),
            1,
        )

    def test_notification_occurs_only_after_commit(self):
        alert = self._alert("post-commit")
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            ticket, _created = ensure_ticket_for_alert(alert)
        self.assertEqual(len(callbacks), 1)
        self.assertFalse(Notification.objects.exists())
        for callback in callbacks:
            callback()
        self.assertEqual(Notification.objects.filter(object_id=str(ticket.pk)).count(), 1)

    def test_no_active_policy_creates_no_ticket(self):
        self.policy.is_active = False
        self.policy.save(update_fields=["is_active"])
        alert = self._alert("no-policy")
        with self.captureOnCommitCallbacks(execute=True):
            ticket, created = ensure_ticket_for_alert(alert)
        self.assertIsNone(ticket)
        self.assertFalse(created)
        self.assertFalse(Ticket.objects.exists())


class DeduplicationTests(AutomationFixture):
    def test_repeated_calls_reuse_linked_ticket(self):
        alert = self._alert("repeat")
        with self.captureOnCommitCallbacks(execute=True):
            first, first_created = ensure_ticket_for_alert(alert)
            second, second_created = ensure_ticket_for_alert(alert)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_duplicate_events_do_not_create_duplicate_tickets(self):
        first_event = self._event("dup-1")
        second_event = self._event("dup-2", correlation_key="key:duplicate")
        alert = self._alert("dup", latest_event=first_event)
        alert.event_count = 2
        alert.duplicate_event_count = 1
        alert.latest_event = second_event
        alert.save()
        with self.captureOnCommitCallbacks(execute=True):
            ensure_ticket_for_alert(alert)
            ensure_ticket_for_alert(alert)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_distinct_alerts_create_distinct_tickets(self):
        first = self._alert("distinct-1")
        second = self._alert("distinct-2", source=self.source_b)
        with self.captureOnCommitCallbacks(execute=True):
            first_ticket, _ = ensure_ticket_for_alert(first)
            second_ticket, _ = ensure_ticket_for_alert(second)
        self.assertNotEqual(first_ticket.pk, second_ticket.pk)
        self.assertEqual(Ticket.objects.count(), 2)

    def test_lower_severity_does_not_reduce_priority(self):
        alert, ticket = self._create_linked_ticket(self._alert("priority-guard"))
        self.assertEqual(ticket.priority, "high")
        alert.severity = "major"
        alert.event_count = 2
        alert.save(update_fields=["severity", "event_count"])
        with self.captureOnCommitCallbacks(execute=True):
            synced, changed = sync_ticket_from_alert(alert)
        self.assertTrue(changed)
        self.assertEqual(synced.priority, "high")

    def test_duplicate_processing_does_not_reassign_or_duplicate_side_effects(self):
        alert, ticket = self._create_linked_ticket(self._alert("dup-effects"))
        ticket.assignee = self.employee
        ticket.save(update_fields=["assignee"])
        with self.captureOnCommitCallbacks(execute=True):
            ensure_ticket_for_alert(alert)
            ensure_ticket_for_alert(alert)
            ensure_ticket_for_alert(alert)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee_id, self.employee.pk)
        self.assertEqual(self._history_count(ticket, "created_from_monitoring_alert"), 1)
        self.assertEqual(Notification.objects.filter(object_id=str(ticket.pk)).count(), 1)


class SynchronizationTests(AutomationFixture):
    def test_severity_escalation_raises_priority_when_policy_permits(self):
        self.policy.default_priority = ""
        self.policy.save(update_fields=["default_priority"])
        alert, ticket = self._create_linked_ticket(
            self._alert("escalate", severity="major")
        )
        self.assertEqual(ticket.priority, "high")
        alert.severity = "critical"
        alert.event_count = 2
        alert.save(update_fields=["severity", "event_count"])
        with self.captureOnCommitCallbacks(execute=True):
            synced, changed = sync_ticket_from_alert(alert)
        self.assertTrue(changed)
        self.assertEqual(synced.priority, "critical")

    def test_manually_edited_fields_are_protected(self):
        alert, ticket = self._create_linked_ticket(self._alert("manual-protect"))
        ticket.assignee = self.employee
        ticket.description = "manual description"
        ticket.category = self.category_b
        ticket.queue = self.queue_b
        ticket.save()
        alert.service_catalogue_item = self.service_b
        alert.severity = "critical"
        alert.event_count = 3
        alert.save()

        with self.captureOnCommitCallbacks(execute=True):
            synced, _changed = sync_ticket_from_alert(alert)
        self.assertEqual(synced.assignee_id, self.employee.pk)
        self.assertEqual(synced.description, "manual description")
        self.assertEqual(synced.category_id, self.category_b.pk)
        self.assertEqual(synced.queue_id, self.queue_b.pk)
        alert.refresh_from_db()
        self.assertEqual(alert.service_catalogue_item_id, self.service_b.pk)

    def test_occurrence_updates_are_bounded(self):
        alert, ticket = self._create_linked_ticket(self._alert("bounded"))
        alert.event_count = 25
        alert.summary = "S" * 5000
        alert.save(update_fields=["event_count", "summary"])
        with self.captureOnCommitCallbacks(execute=True):
            synced, changed = sync_ticket_from_alert(alert)
        self.assertTrue(changed)
        self.assertLessEqual(len(synced.description), 4000)
        self.assertEqual(synced.description.count("Occurrence 25"), 1)

    def test_auto_update_disabled_causes_no_ticket_mutation(self):
        self.policy.auto_update = False
        self.policy.save(update_fields=["auto_update"])
        alert, ticket = self._create_linked_ticket(self._alert("no-update"))
        before = (ticket.priority, ticket.description, ticket.version)
        alert.severity = "critical"
        alert.event_count = 4
        alert.save(update_fields=["severity", "event_count"])
        synced, changed = sync_ticket_from_alert(alert)
        synced.refresh_from_db()
        self.assertFalse(changed)
        self.assertEqual((synced.priority, synced.description, synced.version), before)
        self.assertEqual(self._history_count(synced, "ticket_updated"), 0)

    def test_sync_without_linked_ticket_does_not_create_one(self):
        alert = self._alert("unlinked-sync")
        ticket, changed = sync_ticket_from_alert(alert)
        self.assertIsNone(ticket)
        self.assertFalse(changed)
        self.assertFalse(Ticket.objects.exists())


class RecoveryTests(AutomationFixture):
    def test_recovery_never_creates_a_new_ticket(self):
        alert = self._alert("recover-only", status="recovered")
        ticket, changed = resolve_ticket_for_recovered_alert(alert)
        self.assertIsNone(ticket)
        self.assertFalse(changed)
        self.assertFalse(Ticket.objects.exists())

    def test_auto_resolve_uses_authoritative_ticket_transition(self):
        alert, ticket = self._create_linked_ticket(self._alert("auto-resolve"))
        alert.status = "recovered"
        alert.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            resolved, changed = resolve_ticket_for_recovered_alert(alert)
        self.assertTrue(changed)
        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(self._history_count(resolved, "resolved"), 1)
        alert.refresh_from_db()
        self.assertTrue(alert.auto_resolved)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_auto_resolve_disabled_leaves_ticket_open(self):
        self.policy.auto_resolve = False
        self.policy.save(update_fields=["auto_resolve"])
        alert, ticket = self._create_linked_ticket(self._alert("no-resolve"))
        alert.status = "recovered"
        alert.save(update_fields=["status"])
        resolved, changed = resolve_ticket_for_recovered_alert(alert)
        self.assertFalse(changed)
        self.assertEqual(resolved.status, "open")
        self.assertEqual(self._history_count(resolved, "resolved"), 0)

    def test_manually_controlled_ticket_is_not_auto_resolved(self):
        alert, ticket = self._create_linked_ticket(self._alert("manual-resolve"))
        ticket.assignee = self.employee
        ticket.save(update_fields=["assignee"])
        alert.status = "recovered"
        alert.save(update_fields=["status"])
        resolved, changed = resolve_ticket_for_recovered_alert(alert)
        self.assertFalse(changed)
        self.assertEqual(resolved.status, "open")

    def test_non_reopenable_ticket_is_protected(self):
        alert, ticket = self._create_linked_ticket(self._alert("terminal"))
        ticket.status = "cancelled"
        ticket.save(update_fields=["status"])
        alert.status = "recovered"
        alert.save(update_fields=["status"])
        resolved, changed = resolve_ticket_for_recovered_alert(alert)
        self.assertFalse(changed)
        self.assertEqual(resolved.status, "cancelled")

    def test_recurrence_follows_configured_reopen_policy(self):
        alert, ticket = self._create_linked_ticket(self._alert("recurrence"))
        alert.status = "recovered"
        alert.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            resolve_ticket_for_recovered_alert(alert)
        alert.refresh_from_db()
        alert.status = "open"
        alert.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            reopened, changed = sync_ticket_from_alert(alert)
        self.assertTrue(changed)
        self.assertEqual(reopened.status, "in_progress")
        self.assertEqual(reopened.reopen_count, 1)
        alert.refresh_from_db()
        self.assertFalse(alert.auto_resolved)

    def test_reopen_behavior_none_prevents_reopen(self):
        self.policy.reopen_behavior = ""
        self.policy.save(update_fields=["reopen_behavior"])
        alert, ticket = self._create_linked_ticket(self._alert("no-reopen"))
        alert.status = "recovered"
        alert.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            resolve_ticket_for_recovered_alert(alert)
        alert.refresh_from_db()
        alert.status = "open"
        alert.save(update_fields=["status"])
        synced, changed = sync_ticket_from_alert(alert)
        self.assertFalse(changed)
        self.assertEqual(synced.status, "resolved")


class RetryBatchTests(AutomationFixture):
    def test_failure_stores_safe_error_code_only(self):
        alert = self._alert("safe-failure")
        ticket, created = self._fail_creation(alert)
        self.assertIsNone(ticket)
        self.assertFalse(created)
        alert.refresh_from_db()
        self.assertEqual(alert.automation_error_code, "TICKET_AUTOMATION_FAILED")
        self.assertNotIn("RAW-EXCEPTION-SECRET", alert.automation_error_summary)
        self.assertEqual(
            MonitoringAlertHistory.objects.filter(
                alert=alert,
                event_type=MonitoringAlertHistory.EventType.AUTOMATION_FAILED,
            ).count(),
            1,
        )

    def test_retry_count_increments_once_per_failed_attempt(self):
        alert = self._alert("retry-count")
        self._fail_creation(alert)
        alert.refresh_from_db()
        self.assertEqual(alert.automation_retry_count, 1)
        self._fail_creation(alert)
        alert.refresh_from_db()
        self.assertEqual(alert.automation_retry_count, 2)

    def test_retry_limit_is_enforced(self):
        self.policy.maximum_retries = 1
        self.policy.save(update_fields=["maximum_retries"])
        alert = self._alert("retry-limit")
        self._fail_creation(alert)
        summary = retry_failed_ticket_automation(alert)
        self.assertEqual(summary["skipped"], 1)
        alert.refresh_from_db()
        self.assertEqual(alert.automation_retry_count, 1)

    def test_successful_retry_clears_error_without_duplicate_ticket(self):
        alert = self._alert("retry-success")
        self._fail_creation(alert)
        summary = retry_failed_ticket_automation(alert)
        self.assertEqual(summary["succeeded"], 1)
        alert.refresh_from_db()
        self.assertEqual(alert.automation_error_code, "")
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(alert.ticket_id, Ticket.objects.get().pk)

    def test_no_blocking_sleep_is_used(self):
        source = inspect.getsource(ticket_automation)
        self.assertNotIn("sleep(", source)
        self.assertNotIn("time.sleep", source)

    def test_batch_size_is_bounded(self):
        self.assertEqual(ticket_automation._bound_batch_size(1000), 100)
        self.assertEqual(ticket_automation._bound_batch_size(0), 1)

    def test_batch_order_is_deterministic(self):
        first = self._alert("batch-first")
        second = self._alert("batch-second")
        third = self._alert("batch-third")
        now = timezone.now()
        MonitoringAlert.objects.filter(pk=first.pk).update(first_seen_at=now - timedelta(minutes=3))
        MonitoringAlert.objects.filter(pk=second.pk).update(first_seen_at=now - timedelta(minutes=2))
        MonitoringAlert.objects.filter(pk=third.pk).update(first_seen_at=now - timedelta(minutes=1))
        with self.captureOnCommitCallbacks(execute=True):
            summary = process_alerts_for_ticket_automation()
        self.assertEqual(summary["created"], 3)
        titles = list(Ticket.objects.order_by("pk").values_list("title", flat=True))
        normalized = [title.replace("[MON-CRITICAL] ", "") for title in titles]
        self.assertEqual(normalized, [first.title, second.title, third.title])

    def test_one_failing_alert_does_not_stop_unrelated_alerts(self):
        bad_policy = MonitoringAutomationPolicy.objects.create(
            name="Bad service policy",
            target_service="missing-service",
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
        )
        bad = self._alert("bad", policy=bad_policy)
        good = self._alert("good")
        with self.captureOnCommitCallbacks(execute=True):
            summary = process_alerts_for_ticket_automation()
        self.assertEqual(summary["created"], 1)
        self.assertEqual(Ticket.objects.count(), 1)
        bad.refresh_from_db()
        good.refresh_from_db()
        self.assertEqual(bad.automation_error_code, "INVALID_SERVICE")
        self.assertIsNotNone(good.ticket_id)

    def test_same_failure_is_not_processed_indefinitely(self):
        bad_policy = MonitoringAutomationPolicy.objects.create(
            name="Limited retries policy",
            target_service="missing-service",
            minimum_severity=MonitoringAutomationPolicy.MinimumSeverity.HIGH,
            eligible_alert_states=MonitoringAutomationPolicy.EligibleAlertState.OPEN,
            maximum_retries=1,
        )
        bad = self._alert("limited", policy=bad_policy)
        with self.captureOnCommitCallbacks(execute=True):
            process_alerts_for_ticket_automation()
            first_summary = process_alerts_for_ticket_automation()
        self.assertEqual(first_summary["skipped"], 1)
        bad.refresh_from_db()
        self.assertEqual(bad.automation_retry_count, 1)
        self.assertEqual(bad.automation_error_code, "INVALID_SERVICE")


class SecurityNotificationTests(AutomationFixture):
    def test_raw_payload_and_credentials_excluded_from_ticket_and_notification(self):
        event = self._event(
            "leak",
            normalized_payload={"password": "leak-pass", "signature": "leak-sig"},
            raw_payload_hash="leak-hash",
        )
        alert = self._alert(
            "leak",
            summary="Disk full api_key=leak-key authorization=leak-auth",
            latest_event=event,
        )
        with self.captureOnCommitCallbacks(execute=True):
            ticket, _created = ensure_ticket_for_alert(alert)
        notification = Notification.objects.get(object_id=str(ticket.pk))
        for secret in ("leak-pass", "leak-sig", "leak-hash", "leak-key", "leak-auth"):
            self.assertNotIn(secret, ticket.description)
            self.assertNotIn(secret, notification.body)
            self.assertNotIn(secret, notification.title)

    def test_notify_user_uses_notification_model_and_skips_invalid_users(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_user(self.employee, "monitoring_test", "Test title", "token=abc message")
            notify_user(self.inactive, "monitoring_test", "Inactive", "body")
            notify_user(None, "monitoring_test", "Missing", "body")
        self.assertEqual(Notification.objects.count(), 1)
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient_id, self.employee.pk)
        self.assertNotIn("abc", notification.body)
        self.assertEqual(notification.entity_type, "notification.monitoring_test")

    def test_notify_watchers_deduplicates_recipients_and_skips_actor(self):
        alert, ticket = self._create_linked_ticket(self._alert("watchers"))
        TicketWatcher.objects.create(ticket=ticket, user=self.employee)
        TicketWatcher.objects.create(ticket=ticket, user=self.actor)
        TicketWatcher.objects.create(ticket=ticket, user=self.inactive)
        with self.captureOnCommitCallbacks(execute=True):
            notify_watchers(ticket, self.actor, "Watcher notice", "safe body")
            notify_watchers(ticket, self.actor, "Watcher notice", "safe body")
        self.assertEqual(Notification.objects.filter(recipient=self.employee).count(), 1)
        self.assertFalse(Notification.objects.filter(recipient=self.actor).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.inactive).exists())
        self.assertEqual(alert.ticket_id, ticket.pk)

    def test_notifications_do_not_trigger_recursive_automation(self):
        alert, ticket = self._create_linked_ticket(self._alert("no-recursion"))
        history_before = MonitoringAlertHistory.objects.filter(alert=alert).count()
        with self.captureOnCommitCallbacks(execute=True):
            notify_user(self.employee, "monitoring_test", "Notice", "body")
            notify_watchers(ticket, None, "Notice", "body")
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(MonitoringAlertHistory.objects.filter(alert=alert).count(), history_before)

    def test_notifications_follow_post_commit_behavior(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_user(self.employee, "monitoring_test", "Deferred", "body")
        self.assertEqual(len(callbacks), 1)
        self.assertFalse(Notification.objects.exists())
        for callback in callbacks:
            callback()
        self.assertEqual(Notification.objects.count(), 1)


class TransactionConcurrencyTests(AutomationFixture):
    def test_database_uniqueness_enforces_one_ticket_per_alert(self):
        first = self._alert("unique-1")
        second = self._alert("unique-2")
        _alert, ticket = self._create_linked_ticket(first)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MonitoringAlert.objects.filter(pk=second.pk).update(ticket=ticket)

    def test_concurrent_race_recovery_returns_winning_ticket(self):
        alert = self._alert("race")
        with self.captureOnCommitCallbacks(execute=True):
            winner, created = ensure_ticket_for_alert(alert)
        self.assertTrue(created)
        with self.captureOnCommitCallbacks(execute=True):
            loser, recreated = ensure_ticket_for_alert(MonitoringAlert.objects.get(pk=alert.pk))
        self.assertFalse(recreated)
        self.assertEqual(winner.pk, loser.pk)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_failed_transaction_leaves_no_orphan_ticket_or_linkage(self):
        alert = self._alert("orphan")
        ticket, created = self._fail_creation(alert)
        self.assertIsNone(ticket)
        self.assertFalse(created)
        alert.refresh_from_db()
        self.assertIsNone(alert.ticket_id)
        self.assertFalse(alert.auto_ticket_created)
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(TicketHistory.objects.exists())
        self.assertFalse(Notification.objects.exists())
