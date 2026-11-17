"""Correlation tests for monitoring events and alerts."""

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from monitoring.correlation import build_event_fingerprint, correlate_event
from monitoring.models import MonitoringAlert, MonitoringAlertHistory, MonitoringEvent, MonitoringSource


class EventAlertCorrelationTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source", code="test_src", secret_hash="f" * 64
        )
        self.seq = 0

    def _event(self, **overrides):
        self.seq += 1
        data = {
            "event_id": overrides.pop("event_id", f"EVT-{self.seq:04d}"),
            "source": self.source,
            "event_type": "cpu_high",
            "event_state": MonitoringEvent.EventState.FIRING,
            "severity": "warning",
            "title": "CPU High",
            "summary": "CPU above threshold",
            "occurred_at": timezone.now(),
            "target_type": "host",
            "target_identifier": "host-1",
            "metric_name": "cpu_usage",
            "environment": "prod",
            "raw_payload_hash": "h" * 64,
        }
        data.update(overrides)
        return MonitoringEvent.objects.create(**data)

    def test_one_firing_event_creates_one_alert(self):
        event = self._event()
        alert, created, is_duplicate = correlate_event(event)
        self.assertIsNotNone(alert)
        self.assertTrue(created)
        self.assertFalse(is_duplicate)
        self.assertEqual(alert.fingerprint, build_event_fingerprint(event))
        self.assertEqual(alert.status, "open")
        self.assertEqual(alert.event_count, 1)
        self.assertEqual(MonitoringAlert.objects.filter(fingerprint=alert.fingerprint).count(), 1)

    def test_duplicate_firing_reuses_active_alert(self):
        e1 = self._event()
        a1, created1, dup1 = correlate_event(e1)
        e2 = self._event(title="CPU High again")
        a2, created2, dup2 = correlate_event(e2)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertTrue(dup2)
        self.assertEqual(a1.id, a2.id)
        a2.refresh_from_db()
        self.assertGreaterEqual(a2.event_count, 2)
        self.assertGreaterEqual(a2.duplicate_event_count, 1)
        self.assertTrue(
            MonitoringAlertHistory.objects.filter(alert=a2, event_type=MonitoringAlertHistory.EventType.DUPLICATE_RECEIVED).exists()
        )

    def test_firing_after_recovery_reopens_alert(self):
        e1 = self._event()
        alert, _, _ = correlate_event(e1)
        alert.status = "recovered"
        alert.recovered_at = timezone.now()
        alert.save(update_fields=["status", "recovered_at"])
        e2 = self._event(title="CPU High reopened")
        reopened, created, dup = correlate_event(e2)
        self.assertFalse(created)
        self.assertFalse(dup)
        self.assertEqual(reopened.id, alert.id)
        reopened.refresh_from_db()
        self.assertEqual(reopened.status, "open")
        self.assertTrue(
            MonitoringAlertHistory.objects.filter(alert=reopened, event_type=MonitoringAlertHistory.EventType.REOPENED).exists()
        )

    def test_one_active_alert_invariant(self):
        e1 = self._event(target_identifier="host-1")
        a1, _, _ = correlate_event(e1)
        e2 = self._event(target_identifier="host-2")
        a2, _, _ = correlate_event(e2)
        self.assertNotEqual(a1.id, a2.id)
        self.assertEqual(MonitoringAlert.objects.filter(status="open").count(), 2)

    def test_different_target_and_metric_create_separate_alerts(self):
        e1 = self._event(target_identifier="host-1", metric_name="cpu_usage")
        a1, _, _ = correlate_event(e1)
        e2 = self._event(target_identifier="host-1", metric_name="mem_usage")
        a2, _, _ = correlate_event(e2)
        self.assertNotEqual(a1.fingerprint, a2.fingerprint)
        self.assertNotEqual(a1.id, a2.id)
        self.assertEqual(MonitoringAlert.objects.filter(status="open").count(), 2)

    def test_unknown_recovery_does_not_close_unrelated_alert(self):
        e1 = self._event(target_identifier="host-1")
        alert, _, _ = correlate_event(e1)
        recovery_event = self._event(target_identifier="host-2", event_state=MonitoringEvent.EventState.RECOVERED, title="Unrelated recovery")
        result, created, dup = correlate_event(recovery_event)
        self.assertIsNone(result)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "open")

    def test_same_target_different_metric_creates_separate_alert(self):
        e1 = self._event(metric_name="cpu_usage")
        a1, _, _ = correlate_event(e1)
        e2 = self._event(metric_name="disk_usage")
        a2, _, _ = correlate_event(e2)
        self.assertNotEqual(a1.id, a2.id)

    def test_different_target_same_metric_creates_separate_alert(self):
        e1 = self._event(target_identifier="host-1")
        a1, _, _ = correlate_event(e1)
        e2 = self._event(target_identifier="host-2")
        a2, _, _ = correlate_event(e2)
        self.assertNotEqual(a1.id, a2.id)

    def test_recovery_updates_original_alert(self):
        e1 = self._event()
        alert, _, _ = correlate_event(e1)
        alert.status = "recovered"
        alert.recovered_at = timezone.now()
        alert.save(update_fields=["status", "recovered_at"])
        e2 = self._event(event_state=MonitoringEvent.EventState.FIRING, title="CPU returns")
        reopened, _, _ = correlate_event(e2)
        self.assertEqual(reopened.id, alert.id)
        reopened.refresh_from_db()
        self.assertEqual(reopened.status, "open")
        self.assertIsNone(reopened.recovered_at)

    def test_repeated_firing_no_second_active_alert(self):
        e1 = self._event()
        a1, _, _ = correlate_event(e1)
        for i in range(3):
            e = MonitoringEvent(
                event_id=f"REPEAT-{i}",
                source=self.source,
                event_type="cpu_high",
                event_state=MonitoringEvent.EventState.FIRING,
                severity="warning",
                title="CPU repeated",
                summary="CPU above threshold",
                occurred_at=timezone.now(),
                target_type="host",
                target_identifier="host-1",
                metric_name="cpu_usage",
                environment="prod",
                raw_payload_hash="h" * 64,
            )
            a, created, dup = correlate_event(e)
            self.assertEqual(a.id, a1.id)
        self.assertEqual(MonitoringAlert.objects.filter(fingerprint=a1.fingerprint, status__in=["new", "open", "acknowledged"]).count(), 1)

    def test_one_active_alert_database_constraint(self):
        e1 = self._event()
        alert, _, _ = correlate_event(e1)
        with self.assertRaises(IntegrityError):
            MonitoringAlert.objects.create(
                alert_number="ALT-999999",
                source=self.source,
                fingerprint=alert.fingerprint,
                title="duplicate",
                status="open",
            )

    def test_correlation_failure_no_partial_state(self):
        before = MonitoringAlert.objects.count()
        event = self._event(target_identifier="host-tx")
        alert, created, dup = correlate_event(event)
        self.assertTrue(created)
        recovery = self._event(target_identifier="host-other", event_state=MonitoringEvent.EventState.RECOVERED, title="recovery")
        result, created2, dup2 = correlate_event(recovery)
        self.assertIsNone(result)
        self.assertFalse(created2)
        self.assertEqual(MonitoringAlert.objects.count(), before + 1)
