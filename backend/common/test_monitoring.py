"""Phase 26 — monitoring, alerting and incident management tests."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from accounts.tests import make_users, auth
from common.monitoring import run_health_checks, check_database
from common.monitoring_service import (record_error, resolve_error,
                                       create_or_update_alert,
                                       acknowledge_alert, resolve_alert,
                                       close_alert, create_incident,
                                       update_incident, sanitize_details)
from common.models import (BackgroundTaskRun, HealthCheckResult,
                           OperationalAlert, OperationalErrorEvent,
                           OperationalIncident)

LOC = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def token(user):
    return str(RefreshToken.for_user(user).access_token)


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class HealthCheckTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_backend_healthy(self):
        result = run_health_checks(["backend"])
        self.assertEqual(result["overall"], "healthy")
        self.assertEqual(result["components"]["backend"]["state"], "healthy")

    def test_database_healthy(self):
        result = run_health_checks(["database"])
        self.assertIn(result["components"]["database"]["state"],
                      ("healthy", "degraded"))
        self.assertIn("query_response_ms",
                      result["components"]["database"].get("details", {}))
        self.assertIsNotNone(
            result["components"]["database"]["details"].get("vendor"))

    def test_redis_not_configured_reports_unknown_not_healthy(self):
        with override_settings(CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        }):
            result = run_health_checks(["redis"])
            self.assertEqual(result["components"]["redis"]["state"],
                             "not_configured")

    def test_health_results_persisted(self):
        run_health_checks(["backend"])
        self.assertTrue(
            HealthCheckResult.objects.filter(component="backend").exists())


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class ErrorMonitoringTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_record_error_creates_event(self):
        event = record_error(component="api", title="boom",
                             message="something broke", endpoint="/tickets/",
                             status_code=500, severity="high")
        self.assertEqual(event.component, "api")
        self.assertEqual(event.occurrence_count, 1)
        self.assertIsNotNone(event.dedup_key)

    def test_error_dedup_increments_count(self):
        record_error(component="api", title="boom",
                     message="something broke", endpoint="/tickets/",
                     status_code=500)
        event = record_error(component="api", title="boom",
                             message="something broke", endpoint="/tickets/",
                             status_code=500)
        self.assertEqual(event.occurrence_count, 2)
        self.assertTrue(
            OperationalErrorEvent.objects.filter(dedup_key=event.dedup_key)
            .count() == 1)

    def test_error_sanitizes_secrets(self):
        event = record_error(component="auth", title="bad login",
                             message="failed", endpoint="/token/",
                             status_code=401,
                             details={"password": "s3cret",
                                      "authorization": "Bearer abc",
                                      "safe": "ok"})
        self.assertEqual(event.details.get("password"), "[REDACTED]")
        self.assertEqual(event.details.get("authorization"), "[REDACTED]")
        self.assertEqual(event.details.get("safe"), "ok")

    def test_error_does_not_store_raw_password_in_message(self):
        event = record_error(component="api", title="x",
                             message="password=s3cret failed")
        self.assertNotIn("s3cret", event.message)

    def test_resolve_error(self):
        event = record_error(component="api", title="boom",
                             message="m", endpoint="/tickets/", status_code=500)
        ok, resolved = resolve_error(event.pk, self.admin)
        self.assertTrue(ok)
        self.assertTrue(resolved.resolved)
        self.assertEqual(resolved.resolved_by_id, self.admin.pk)


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class AlertTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_alert_dedup_increments_occurrence(self):
        a1, created = create_or_update_alert(
            component="database", severity="critical",
            title="DB down", description="db unreachable")
        self.assertTrue(created)
        a2, created2 = create_or_update_alert(
            component="database", severity="critical",
            title="DB down", description="db still unreachable")
        self.assertFalse(created2)
        a2.refresh_from_db()
        self.assertEqual(a2.occurrence_count, 2)

    def test_ack_and_resolve(self):
        alert, _ = create_or_update_alert(
            component="redis", severity="warning",
            title="Redis down", description="no ping")
        ok, a = acknowledge_alert(alert.pk, self.mgr)
        self.assertTrue(ok)
        a.refresh_from_db()
        self.assertTrue(a.acknowledged)
        self.assertEqual(a.acknowledged_by_id, self.mgr.pk)
        self.assertEqual(a.status, "acknowledged")

        ok, a = resolve_alert(alert.pk, self.admin)
        self.assertTrue(ok)
        a.refresh_from_db()
        self.assertTrue(a.resolved)
        self.assertEqual(a.status, "resolved")

    def test_close_requires_system_admin(self):
        alert, _ = create_or_update_alert(
            component="storage", severity="warning",
            title="Storage down", description="no write")
        # IT Manager cannot close.
        auth(self.c, self.mgr)
        res = self.c.post(f"/api/common/alerts/{alert.pk}/close/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.admin)
        res = self.c.post(f"/api/common/alerts/{alert.pk}/close/")
        self.assertEqual(res.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "closed")


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class IncidentTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_incident_lifecycle(self):
        auth(self.c, self.admin)
        res = self.c.post("/api/common/incidents/", {
            "title": "DB outage", "description": "database unreachable",
            "severity": "critical", "affected_component": "database",
            "assigned_to": self.mgr.pk,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        inc_id = res.data["id"]
        # Non-assignee IT Manager cannot update severity.
        auth(self.c, self.emp)
        res = self.c.patch(f"/api/common/incidents/{inc_id}/",
                           {"severity": "informational"}, format="json")
        self.assertEqual(res.status_code, 403)
        # Assignee can update notes.
        auth(self.c, self.mgr)
        res = self.c.patch(f"/api/common/incidents/{inc_id}/",
                           {"internal_notes": "investigating"}, format="json")
        self.assertEqual(res.status_code, 200)
        # Resolve by assignee.
        res = self.c.patch(f"/api/common/incidents/{inc_id}/",
                           {"status": "resolved"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "resolved")

    def test_incident_related_ticket_link(self):
        from tickets.models import Ticket, TicketCategory
        cat = TicketCategory.objects.create(name="T")
        auth(self.c, self.admin)
        res = self.c.post("/api/common/incidents/", {
            "title": "Ticket-linked incident",
            "description": "d", "severity": "warning",
            "related_ticket": 1,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["related_ticket"], 1)

    def test_employee_cannot_access_incidents(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/incidents/")
        self.assertEqual(res.status_code, 403)


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class SanitizationTests(TestCase):
    def test_sanitize_details_redacts_secrets(self):
        out = sanitize_details({
            "password": "pw",
            "Authorization": "Bearer tok",
            "normal": "value",
            "nested": {"secret_key": "sk", "ok": 1},
            "list": [{"token": "t"}, "plain"],
        })
        self.assertEqual(out["password"], "[REDACTED]")
        self.assertEqual(out["Authorization"], "[REDACTED]")
        self.assertEqual(out["normal"], "value")
        self.assertEqual(out["nested"]["secret_key"], "[REDACTED]")
        self.assertEqual(out["nested"]["ok"], 1)
        self.assertEqual(out["list"][0]["token"], "[REDACTED]")
        self.assertEqual(out["list"][1], "plain")


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class MonitoringPermissionTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_health_requires_it_staff(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/health/")
        self.assertEqual(res.status_code, 403)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/health/")
        self.assertEqual(res.status_code, 200)

    def test_employee_cannot_access_errors_alerts_incidents(self):
        auth(self.c, self.emp)
        for url in ("/api/common/errors/", "/api/common/alerts/",
                    "/api/common/incidents/", "/api/common/api-performance/",
                    "/api/common/email-storage/"):
            res = self.c.get(url)
            self.assertEqual(res.status_code, 403, url)

    def test_it_manager_can_view_health(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/health/")
        self.assertEqual(res.status_code, 200)


@override_settings(**LOC, ALLOWED_HOSTS=["testserver", "localhost",
                                         "127.0.0.1"])
class ScheduledMonitoringTaskTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()

    def test_evaluate_component_health_runs(self):
        from common.monitoring_tasks import evaluate_component_health
        # .apply() runs the task inline without a broker.
        evaluate_component_health.apply(args=[], kwargs={})
        self.assertTrue(
            BackgroundTaskRun.objects.filter(
                task_name="common.monitoring_tasks.evaluate_component_health",
                status="succeeded").exists())
        self.assertTrue(
            HealthCheckResult.objects.filter(component="database").exists())
