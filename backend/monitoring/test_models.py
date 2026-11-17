from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from monitoring.correlation import build_event_fingerprint
from monitoring.models import MonitoringAlert, MonitoringEvent, MonitoringEventOccurrence, MonitoringSource


class MonitoringSourceTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source",
            code="test_src",
            secret_hash="a" * 64,
        )

    def test_source_creation_with_required_fields_and_safe_defaults(self):
        s = self.source
        self.assertEqual(s.name, "Test Source")
        self.assertEqual(s.code, "test_src")
        self.assertEqual(s.secret_hash, "a" * 64)
        self.assertEqual(s.status, MonitoringSource.Status.ACTIVE)
        self.assertEqual(s.source_type, MonitoringSource.SourceType.OTHER)
        self.assertTrue(s.is_active)
        self.assertEqual(s.health_status, MonitoringSource.HealthStatus.UNKNOWN)
        self.assertEqual(s.rate_limit_per_minute, 60)
        self.assertEqual(s.timestamp_tolerance_seconds, 300)

    def test_source_code_uniqueness(self):
        MonitoringSource.objects.create(name="SrcA", code="ucode", secret_hash="b" * 64)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MonitoringSource.objects.create(name="SrcB", code="ucode", secret_hash="c" * 64)
        self.assertTrue(MonitoringSource.objects.filter(code="ucode").exists())

    def test_source_string_representation(self):
        self.assertEqual(str(self.source), "Test Source")


class MonitoringEventTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Test Source",
            code="test_src",
            secret_hash="d" * 64,
        )
        self.occurred = timezone.now()
        self.event = MonitoringEvent.objects.create(
            event_id="EVT-0001",
            source=self.source,
            event_type="cpu_high",
            event_state=MonitoringEvent.EventState.FIRING,
            severity=MonitoringEvent.Severity.MAJOR,
            title="CPU High",
            summary="CPU usage above threshold",
            occurred_at=self.occurred,
            fingerprint="fp-evt-0001",
            target_type=MonitoringEvent.TargetType.HOST,
            target_identifier="host-1",
            metric_name="cpu",
            raw_payload_hash="h" * 64,
            normalized_payload={"k": "v"},
            processing_status=MonitoringEvent.ProcessingStatus.RECEIVED,
        )

    def _base_event(self, **overrides):
        data = {
            "event_id": overrides.pop("event_id", "EVT-BASE"),
            "source": self.source,
            "event_type": "disk_low",
            "event_state": MonitoringEvent.EventState.FIRING,
            "severity": MonitoringEvent.Severity.WARNING,
            "title": "Disk Low",
            "summary": "Disk space low",
            "occurred_at": self.occurred,
            "fingerprint": overrides.pop("fingerprint", "fp-base"),
            "target_type": MonitoringEvent.TargetType.HOST,
            "target_identifier": "host-2",
            "metric_name": "disk",
            "environment": "prod",
            "raw_payload_hash": "r" * 64,
        }
        data.update(overrides)
        return data

    def test_event_creation_required_fields(self):
        e = self.event
        self.assertEqual(e.source_id, self.source.id)
        self.assertEqual(e.event_id, "EVT-0001")
        self.assertEqual(e.event_type, "cpu_high")
        self.assertEqual(e.fingerprint, "fp-evt-0001")
        self.assertEqual(e.event_state, MonitoringEvent.EventState.FIRING)
        self.assertEqual(e.severity, MonitoringEvent.Severity.MAJOR)
        self.assertEqual(e.target_identifier, "host-1")
        self.assertEqual(e.metric_name, "cpu")
        self.assertEqual(e.processing_status, MonitoringEvent.ProcessingStatus.RECEIVED)
        self.assertIsNotNone(e.occurred_at)
        self.assertIsNotNone(e.received_at)

    def test_event_fingerprint_deterministic_using_builder(self):
        e1 = MonitoringEvent(**self._base_event(event_id="EVT-FP1", fingerprint="x"))
        e2 = MonitoringEvent(**self._base_event(event_id="EVT-FP2", fingerprint="y", title="Different title"))
        fp1 = build_event_fingerprint(e1)
        fp2 = build_event_fingerprint(e2)
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)

    def test_different_identity_produces_different_fingerprint(self):
        e1 = MonitoringEvent(**self._base_event(event_id="EVT-A", fingerprint="a", target_identifier="host-a"))
        e2 = MonitoringEvent(**self._base_event(event_id="EVT-B", fingerprint="b", target_identifier="host-b"))
        self.assertNotEqual(build_event_fingerprint(e1), build_event_fingerprint(e2))

    def test_duplicate_canonical_event_rejected(self):
        MonitoringEvent.objects.create(**self._base_event(event_id="EVT-D1", fingerprint="dup-fp"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MonitoringEvent.objects.create(**self._base_event(event_id="EVT-D2", fingerprint="dup-fp"))
        self.assertEqual(MonitoringEvent.objects.filter(fingerprint="dup-fp").count(), 1)

    def test_event_occurrence_creation(self):
        occ = MonitoringEventOccurrence.objects.create(
            event=self.event,
            occurred_at=self.occurred,
            event_state=MonitoringEvent.EventState.FIRING,
            payload_hash="p" * 64,
        )
        self.assertEqual(occ.event_id, self.event.id)
        self.assertEqual(occ.event_state, MonitoringEvent.EventState.FIRING)
        self.assertEqual(MonitoringEventOccurrence.objects.filter(event=self.event).count(), 1)


class MonitoringAlertTestCase(TestCase):
    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Alert Source",
            code="alert_src",
            secret_hash="e" * 64,
        )
        self.event = MonitoringEvent.objects.create(
            event_id="EVT-ALERT-1",
            source=self.source,
            event_type="mem_high",
            event_state=MonitoringEvent.EventState.FIRING,
            severity=MonitoringEvent.Severity.CRITICAL,
            title="Memory High",
            summary="Memory pressure",
            occurred_at=timezone.now(),
            fingerprint="fp-alert-evt-1",
            raw_payload_hash="m" * 64,
        )

    def _create_alert(self, **overrides):
        data = {
            "alert_number": overrides.pop("alert_number", "A-0001"),
            "title": "Memory Alert",
            "summary": "Alert summary",
            "severity": MonitoringAlert.AlertSeverity.CRITICAL,
            "status": MonitoringAlert.AlertStatus.NEW,
            "source": self.source,
            "fingerprint": overrides.pop("fingerprint", "alert-fp-1"),
            "first_event": self.event,
            "latest_event": self.event,
        }
        data.update(overrides)
        return MonitoringAlert.objects.create(**data)

    def test_alert_creation_with_required_fields(self):
        alert = self._create_alert()
        self.assertEqual(alert.alert_number, "A-0001")
        self.assertEqual(alert.source_id, self.source.id)
        self.assertEqual(alert.fingerprint, "alert-fp-1")
        self.assertEqual(alert.title, "Memory Alert")
        self.assertEqual(alert.severity, MonitoringAlert.AlertSeverity.CRITICAL)
        self.assertEqual(alert.status, MonitoringAlert.AlertStatus.NEW)
        self.assertEqual(alert.event_count, 1)
        self.assertIsNotNone(alert.first_seen_at)
        self.assertIsNotNone(alert.pk)

    def test_alert_string_representation(self):
        alert = self._create_alert(alert_number="A-STR1", fingerprint="fp-str")
        self.assertIn("A-STR1", str(alert))

    def test_one_active_alert_invariant_same_fingerprint_and_status(self):
        self._create_alert(alert_number="A-0002", fingerprint="same-fp", status=MonitoringAlert.AlertStatus.OPEN)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create_alert(alert_number="A-0003", fingerprint="same-fp", status=MonitoringAlert.AlertStatus.OPEN)
        self.assertEqual(
            MonitoringAlert.objects.filter(fingerprint="same-fp", status=MonitoringAlert.AlertStatus.OPEN).count(),
            1,
        )

    def test_recovered_alert_does_not_violate_active_uniqueness(self):
        self._create_alert(alert_number="A-0004", fingerprint="reopen-fp", status=MonitoringAlert.AlertStatus.RECOVERED)
        alert2 = self._create_alert(alert_number="A-0005", fingerprint="reopen-fp", status=MonitoringAlert.AlertStatus.OPEN)
        self.assertEqual(alert2.status, MonitoringAlert.AlertStatus.OPEN)
        self.assertEqual(MonitoringAlert.objects.filter(fingerprint="reopen-fp").count(), 2)