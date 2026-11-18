from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase

from monitoring.alert_subresource_serializers import (
    MonitoringAlertEventSerializer,
    MonitoringAlertHistorySerializer,
    MonitoringAlertTicketSerializer,
)
from monitoring.alert_subresource_views import (
    AlertAccessHelper,
    AlertEventsViewSet,
    AlertHistoryViewSet,
    AlertTicketViewSet,
)
from monitoring.models import (
    MonitoringAlert,
    MonitoringAlertHistory,
    MonitoringEvent,
    MonitoringEventOccurrence,
    MonitoringSource,
)
from tickets.models import Ticket, TicketCategory


class AlertSubresourceTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            employee_id="EMP-SUB-001",
            role="system_admin",
            is_staff=True,
            is_superuser=True,
        )
        self.it_manager = User.objects.create_user(
            username="it_manager",
            email="itmgr@test.com",
            employee_id="EMP-SUB-002",
            role="it_manager",
            is_staff=True,
        )
        self.it_support = User.objects.create_user(
            username="it_support",
            email="itsup@test.com",
            employee_id="EMP-SUB-003",
            role="it_support",
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username="employee",
            email="emp@test.com",
            employee_id="EMP-SUB-004",
            role="employee",
            is_staff=False,
        )
        self.unknown_user = User.objects.create_user(
            username="unknown",
            email="unknown@test.com",
            employee_id="EMP-SUB-005",
            role="unknown_role",
            is_staff=False,
        )
        self.inactive_user = User.objects.create_user(
            username="inactive",
            email="inactive@test.com",
            employee_id="EMP-SUB-006",
            role="it_support",
            is_active=False,
        )

        self.source = MonitoringSource.objects.create(
            name="Test Source",
            code="test-src",
            source_type="prometheus_alertmanager",
        )
        self.event = MonitoringEvent.objects.create(
            event_id="test-event-1",
            source=self.source,
            event_type="test_event",
            severity="warning",
            title="Test Event",
            occurred_at=timezone.now(),
            fingerprint="test-event-fp-1",
            raw_payload_hash="event-hash",
            target_identifier="host-1",
            metric_name="cpu_usage",
            duplicate_count=2,
        )
        self.occurrence = MonitoringEventOccurrence.objects.create(
            event=self.event,
            occurred_at=timezone.now(),
            event_state=MonitoringEvent.EventState.FIRING,
            payload_hash="occurrence-hash",
        )

        category = TicketCategory.objects.create(name="Subresource Category")
        self.ticket = Ticket.objects.create(
            title="Test Ticket",
            description="Test ticket description",
            category=category,
            priority="high",
            status="open",
            requester=self.employee,
            assignee=self.it_support,
        )

        self.alert_with_ticket = MonitoringAlert.objects.create(
            source=self.source,
            alert_number="ALT-SUB-001",
            fingerprint="test-alert-001",
            title="Test Alert",
            summary="A test alert",
            severity="medium",
            status="open",
            ticket=self.ticket,
            first_event=self.event,
            latest_event=self.event,
        )
        self.alert_without_ticket = MonitoringAlert.objects.create(
            source=self.source,
            alert_number="ALT-SUB-002",
            fingerprint="test-alert-002",
            title="Test Alert 2",
            summary="Another test alert",
            severity="low",
            status="open",
            first_event=self.event,
            latest_event=self.event,
        )
        self.history_entry = MonitoringAlertHistory.objects.create(
            alert=self.alert_with_ticket,
            event=self.event,
            actor=self.admin_user,
            event_type=MonitoringAlertHistory.EventType.ACKNOWLEDGED,
            previous_status="open",
            new_status="acknowledged",
            detail="secret: hunter2, token=abc123, safe summary",
        )

    def request_for(self, user):
        request = APIRequestFactory().get("/")
        request.user = user
        return request

    def view_for(self, view_class, alert, user):
        view = view_class()
        view.request = self.request_for(user)
        view.kwargs = {"pk": alert.pk}
        view.format_kwarg = None
        return view

    def test_alert_access_helper_anonymous(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, AnonymousUser())
        self.assertIsNone(alert)
        self.assertEqual(error.status_code, 403)

    def test_alert_access_helper_inactive(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, self.inactive_user)
        self.assertIsNone(alert)
        self.assertEqual(error.status_code, 403)

    def test_alert_access_helper_unknown_role(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, self.unknown_user)
        self.assertIsNone(alert)
        self.assertEqual(error.status_code, 403)

    def test_alert_access_helper_system_admin(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, self.admin_user)
        self.assertIsNotNone(alert)
        self.assertIsNone(error)

    def test_alert_access_helper_it_manager(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, self.it_manager)
        self.assertIsNotNone(alert)
        self.assertIsNone(error)

    def test_alert_access_helper_it_support(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, self.it_support)
        self.assertIsNotNone(alert)
        self.assertIsNone(error)

    def test_alert_access_helper_employee(self):
        alert, error = AlertAccessHelper.get_alert(self.alert_with_ticket.pk, self.employee)
        self.assertIsNotNone(alert)
        self.assertIsNone(error)

    def test_events_view_set_serializer_fields(self):
        self.assertEqual(AlertEventsViewSet.serializer_class, MonitoringAlertEventSerializer)
        self.assertEqual(
            list(MonitoringAlertEventSerializer.Meta.fields),
            [
                "id",
                "event_identifier",
                "event_type",
                "severity",
                "status",
                "source_name",
                "target",
                "metric_name",
                "occurrence_count",
                "first_seen",
                "last_seen",
                "created_timestamp",
            ],
        )

    def test_history_view_set_serializer_fields(self):
        self.assertEqual(AlertHistoryViewSet.serializer_class, MonitoringAlertHistorySerializer)
        self.assertEqual(
            list(MonitoringAlertHistorySerializer.Meta.fields),
            [
                "id",
                "event_action_type",
                "safe_summary",
                "actor_display",
                "previous_state",
                "new_state",
                "created_timestamp",
            ],
        )

    def test_ticket_view_set_serializer_fields(self):
        self.assertEqual(AlertTicketViewSet.serializer_class, MonitoringAlertTicketSerializer)
        self.assertEqual(
            list(MonitoringAlertTicketSerializer.Meta.fields),
            [
                "id",
                "ticket_number",
                "title",
                "status",
                "priority",
                "service",
                "category",
                "assignee_display",
                "created_timestamp",
                "updated_timestamp",
            ],
        )

    def test_events_queryset_uses_select_related(self):
        view = self.view_for(AlertEventsViewSet, self.alert_with_ticket, self.admin_user)
        queryset = view.get_queryset()
        self.assertTrue(queryset.query.select_related)

    def test_history_queryset_ordering(self):
        view = self.view_for(AlertHistoryViewSet, self.alert_with_ticket, self.admin_user)
        queryset = view.get_queryset()
        self.assertEqual(list(queryset.query.order_by), ["-created_at", "id"])

    def test_ticket_linked_returns_200(self):
        view = self.view_for(AlertTicketViewSet, self.alert_with_ticket, self.admin_user)
        response = view.retrieve(self.request_for(self.admin_user), pk=self.alert_with_ticket.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ticket_number", response.data)
        self.assertIn("title", response.data)

    def test_ticket_missing_returns_404(self):
        view = self.view_for(AlertTicketViewSet, self.alert_without_ticket, self.admin_user)
        response = view.retrieve(self.request_for(self.admin_user), pk=self.alert_without_ticket.pk)
        self.assertEqual(response.status_code, 404)

    def test_event_serializer_exposes_safe_fields(self):
        data = MonitoringAlertEventSerializer(self.occurrence).data
        self.assertEqual(data["event_identifier"], "test-event-1")
        self.assertEqual(data["event_type"], "test_event")
        self.assertEqual(data["severity"], "warning")
        self.assertEqual(data["status"], "firing")
        self.assertEqual(data["source_name"], "Test Source")
        self.assertEqual(data["target"], "host-1")
        self.assertEqual(data["metric_name"], "cpu_usage")
        self.assertEqual(data["occurrence_count"], 3)
        for key in ("raw_payload", "authorization", "cookie", "signature", "traceback"):
            self.assertNotIn(key, data)

    def test_history_serializer_sensitive_redaction(self):
        data = MonitoringAlertHistorySerializer(self.history_entry).data
        self.assertNotIn("hunter2", data["safe_summary"])
        self.assertNotIn("abc123", data["safe_summary"])
        self.assertIn("(redacted)", data["safe_summary"])
        self.assertLessEqual(len(data["safe_summary"]), 500)

    def test_ticket_serializer_sensitive_omission(self):
        data = MonitoringAlertTicketSerializer(self.ticket).data
        self.assertEqual(data["ticket_number"], str(self.ticket.pk))
        self.assertEqual(data["category"], "Subresource Category")
        self.assertEqual(data["assignee_display"], "it_support")
        for key in ("internal_notes", "private_attachment", "requester_email", "requester_phone"):
            self.assertNotIn(key, data)
