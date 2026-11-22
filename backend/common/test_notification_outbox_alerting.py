"""Operational alerting tests for notification outbox (Phase 66 hardening)."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.tests import make_users
from common.models import NotificationOutboxEvent, OperationalAlert
from common.outbox import (
    OUTBOX_ALERT_DEDUPE_PREFIX,
    enqueue_email,
    evaluate_outbox_alerts,
    get_outbox_stats,
    process_pending_batch,
)

LOCMEM = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def _enqueue(recipient, **kw):
    kw.setdefault("wakeup", False)
    kw.setdefault("event_type", "test.alert")
    kw.setdefault("to_email", getattr(recipient, "email", "r@x"))
    kw.setdefault("subject", "Subject")
    kw.setdefault("body", "Body")
    kw.setdefault("recipient", recipient)
    return enqueue_email(**kw)


@override_settings(**LOCMEM)
class OutboxAlertingTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def _stats(self, **overrides):
        stats = get_outbox_stats()
        stats.update(overrides)
        return stats

    @override_settings(NOTIFICATION_OUTBOX_ALERT_FAILED_COUNT=1)
    def test_failed_threshold_creates_alert(self):
        ev = _enqueue(self.emp)
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(status="failed")

        result = evaluate_outbox_alerts()
        self.assertTrue(result["evaluated"])

        alert = OperationalAlert.objects.get(
            dedup_key=f"{OUTBOX_ALERT_DEDUPE_PREFIX}.failed_count"
        )
        self.assertEqual(alert.status, "open")
        self.assertEqual(alert.component, "email")
        self.assertIn("failed", alert.title.lower())

    @override_settings(NOTIFICATION_OUTBOX_ALERT_FAILED_COUNT=10)
    def test_condition_clear_resolves_alert(self):
        dedup_key = f"{OUTBOX_ALERT_DEDUPE_PREFIX}.failed_count"
        OperationalAlert.objects.create(
            dedup_key=dedup_key,
            component="email",
            severity="critical",
            status="open",
            title="Outbox failed-event threshold exceeded",
            description="test",
        )

        evaluate_outbox_alerts(stats=self._stats(failed=0))
        alert = OperationalAlert.objects.get(dedup_key=dedup_key)
        self.assertEqual(alert.status, "resolved")
        self.assertTrue(alert.resolved)

    @override_settings(NOTIFICATION_OUTBOX_ALERT_EXPIRED_CLAIMS=1)
    def test_expired_claims_alert(self):
        ev = _enqueue(self.emp)
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            status="processing",
            lease_expires_at=timezone.now() - timedelta(seconds=30),
            claimed_by="dead-worker",
            attempts=1,
        )
        evaluate_outbox_alerts()
        alert = OperationalAlert.objects.get(
            dedup_key=f"{OUTBOX_ALERT_DEDUPE_PREFIX}.expired_claims"
        )
        self.assertEqual(alert.status, "open")

    @override_settings(NOTIFICATION_OUTBOX_ALERT_OLDEST_PENDING_SECONDS=60)
    def test_oldest_pending_age_alert(self):
        ev = _enqueue(self.emp)
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(
            created_at=timezone.now() - timedelta(seconds=120)
        )
        evaluate_outbox_alerts()
        alert = OperationalAlert.objects.get(
            dedup_key=f"{OUTBOX_ALERT_DEDUPE_PREFIX}.oldest_pending_age"
        )
        self.assertEqual(alert.status, "open")

    @override_settings(NOTIFICATION_OUTBOX_ALERT_BACKLOG=1)
    def test_backlog_alert(self):
        _enqueue(self.emp, event_type="a1", subject="1")
        _enqueue(self.emp, event_type="a2", subject="2")
        evaluate_outbox_alerts()
        alert = OperationalAlert.objects.get(
            dedup_key=f"{OUTBOX_ALERT_DEDUPE_PREFIX}.backlog"
        )
        self.assertEqual(alert.status, "open")

    @override_settings(NOTIFICATION_OUTBOX_ALERT_FAILED_COUNT=1)
    def test_repeated_scans_update_same_alert(self):
        ev = _enqueue(self.emp)
        NotificationOutboxEvent.objects.filter(pk=ev.pk).update(status="failed")

        evaluate_outbox_alerts()
        evaluate_outbox_alerts()
        alerts = OperationalAlert.objects.filter(
            dedup_key=f"{OUTBOX_ALERT_DEDUPE_PREFIX}.failed_count"
        )
        self.assertEqual(alerts.count(), 1)
        alert = alerts.first()
        self.assertGreaterEqual(alert.occurrence_count, 2)

    @override_settings(NOTIFICATION_OUTBOX_ALERT_FAILED_COUNT=1)
    def test_alerting_exception_does_not_stop_processing(self):
        ev = _enqueue(self.emp)
        with mock.patch("common.monitoring_service.create_or_update_alert", side_effect=RuntimeError("alert down")):
            results = process_pending_batch(batch_size=10)
        self.assertEqual(results["delivered"], 1)
        self.assertIn("alerts", results)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "delivered")