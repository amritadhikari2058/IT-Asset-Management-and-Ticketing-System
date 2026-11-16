from django.test import TestCase
from django.utils import timezone
from django.db import IntegrityError
from monitoring.models import MonitoringSource, MonitoringEvent, MonitoringAlert


class MonitoringSourceTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source", code="test_src", secret_hash="abc123def456"
        )

    def test_source_creation_with_required_fields_and_safe_defaults(self):
        s = self.source
        self.assertEqual(s.name, "Test Source")
        self.assertEqual(s.code, "test_src")
        self.assertEqual(s.secret_hash, "abc123def456")
        self.assertEqual(s.status, MonitoringSource.Status.ACTIVE)
        self.assertEqual(s.source_type, MonitoringSource.SourceType.OTHER)

    def test_source_code_uniqueness(self):
        MonitoringSource.objects.create(name="SrcA", code="ucode", secret_hash="h1")
        with self.assertRaises(IntegrityError):
            MonitoringSource.objects.create(name="SrcB", code="ucode", secret_hash="h2")

    def test_source_string_representation(self):
        self.assertEqual(str(self.source), "Test Source")

class MonitoringEventTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source", code="test_src", secret_hash="abc123def456"
        )
        self.event = MonitoringEvent.objects.create(
            source=self.source,
            event_type="test_event",
            fingerprint="test-fp-123",
            occurred_at=timezone.now(),
            title="Test Event",
            summary="A test event summary",
        )

    def test_event_creation_required_fields(self):
        e = self.event
        self.assertEqual(e.source, self.source)
        self.assertEqual(e.event_type, "test_event")
        self.assertEqual(e.fingerprint, "test-fp-123")
        self.assertIsNotNone(e.occurred_at)
        self.assertEqual(e.title, "Test Event")
        self.assertEqual(e.summary, "A test event summary")

    def test_event_fingerprint_deterministic(self):
        s = self.source
        e1 = MonitoringEvent.objects.create(
            source=s, event_type="det_test", fingerprint="det-fp",
            occurred_at=timezone.now(), title="Det Test", summary="det data"
        )
        e2 = MonitoringEvent.objects.create(
            source=s, event_type="det_test", fingerprint="det-fp",
            occurred_at=timezone.now(), title="Det Test", summary="det data"
        )
        self.assertEqual(e1.fingerprint, e2.fingerprint)

    def test_duplicate_canonical_event_rejected(self):
        s = self.source
        MonitoringEvent.objects.create(
            source=s, event_type="can_test", fingerprint="can-fp-456",
            occurred_at=timezone.now(), title="Can Test"
        )
        with self.assertRaises(IntegrityError):
            MonitoringEvent.objects.create(
                source=s, event_type="can_test", fingerprint="can-fp-456",
                occurred_at=timezone.now(), title="Can Test"
            )

    def test_different_identity_different_fingerprint(self):
        s = self.source
        e1 = MonitoringEvent.objects.create(
            source=s, event_type="evt_a", fingerprint="fp-a-001",
            occurred_at=timezone.now(), title="Event A"
        )
        e2 = MonitoringEvent.objects.create(
            source=s, event_type="evt_b", fingerprint="fp-b-002",
            occurred_at=timezone.now(), title="Event B"
        )
        self.assertNotEqual(e1.fingerprint, e2.fingerprint)

class MonitoringAlertTestCase(TestCase):
    """Tests for MonitoringAlert model."""

    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source", code="test_src"
        )

    def test_alert_creation_with_required_fields(self):
        alert = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint="test-fingerprint-123",
            title="Test Alert",
            summary="Test alert summary",
            severity="warning",
        )
        self.assertEqual(alert.source, self.source)
        self.assertEqual(alert.fingerprint, "test-fingerprint-123")
        self.assertEqual(alert.title, "Test Alert")
        self.assertEqual(alert.summary, "Test alert summary")
        self.assertEqual(alert.severity, "warning")
        self.assertIsNotNone(alert.alert_number)
        self.assertIsNotNone(alert.pk)

    def test_alert_number_generation(self):
        alert = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint="test-fingerprint-456",
            title="Number Test Alert",
            summary="Number test summary",
            severity="info",
        )
        self.assertTrue(alert.alert_number.startswith("ALT-"), f"alert_number {alert.alert_number} should start with ALT-")

    def test_alert_default_status_is_new(self):
        alert = MonitoringAlert.objects.create(
            source=self.source,
            fingerprint="test-fingerprint-789",
            title="Default Status Alert",
            summary="Default status test",
            severity="info",
        )
        self.assertEqual(alert.status, "new")

    def test_fingerprint_status_uniqueness_constraint(self):
        MonitoringAlert.objects.create(
            source=self.source,
            fingerprint="unique-fp-1",
            title="Alert A",
            summary="First alert",
            severity="info",
            status="open",
        )
        with self.assertRaises(IntegrityError):
            MonitoringAlert.objects.create(
                source=self.source,
                fingerprint="unique-fp-1",
                title="Alert B",
                summary="Second alert",
                severity="info",
                status="open",
            )