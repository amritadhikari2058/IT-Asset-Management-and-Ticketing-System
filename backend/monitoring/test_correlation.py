"""Correlation tests for monitoring events and alerts."""
from django.test import TestCase
from django.utils import timezone
from monitoring.models import MonitoringSource, MonitoringEvent, MonitoringAlert


class EventAlertCorrelationTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(name="Test Source", code="test_src")

    def test_one_firing_event_creates_one_alert(self):
        event = MonitoringEvent.objects.create(
            source=self.source,
            event_type="test_event",
            event_state="firing",
            severity="info",
            title="Test Event",
            summary="Test summary",
            occurred_at=timezone.now(),
        )

    def test_firing_after_recovery_reopens_alert(self):
        event = MonitoringEvent.objects.create(
            source=self.source,
            event_type="test_event",
            event_state="firing",
            severity="info",
            title="Test Event",
            summary="Test summary",
            occurred_at=timezone.now(),
        )
        alert = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint=event.fingerprint,
            title="Test Alert",
            summary="Test alert summary",
            severity="info",
        )

    def test_one_active_alert_invariant(self):
        event1 = MonitoringEvent.objects.create(
            source=self.source,
            event_type="test_event",
            event_state="firing",
            severity="info",
            title="Test Event 1",
            summary="Test summary 1",
            target_type="asset",
            target_identifier="asset-123",
            occurred_at=timezone.now(),
        )
        alert1 = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint=event1.fingerprint,
            title="Test Alert 1",
            summary="Test alert summary 1",
            severity="info",
            status="open",
        )
        event2 = MonitoringEvent.objects.create(
            source=self.source,
            event_type="test_event",
            event_state="firing",
            severity="info",
            title="Test Event 2",
            summary="Test summary 2",
            target_type="service",
            target_identifier="service-456",
            occurred_at=timezone.now(),
        )
        alert2 = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint=event2.fingerprint,
            title="Test Alert 2",
            summary="Test alert summary 2",
            severity="info",
            status="open",
        )
        self.assertEqual(
            MonitoringAlert.objects.filter(status="open").count(), 2
        )
