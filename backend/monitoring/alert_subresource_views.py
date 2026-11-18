"""Views for Monitoring Alert sub-resource APIs."""
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from monitoring.models import MonitoringAlert, MonitoringEvent, MonitoringEventOccurrence, MonitoringAlertHistory
from .alert_subresource_serializers import (
    MonitoringAlertEventSerializer,
    MonitoringAlertHistorySerializer,
    MonitoringAlertTicketSerializer,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AlertTicketViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only View for GET /api/monitoring/alerts/{id}/ticket/.

    Implements a read-only single-object View.
    Behavior:
    - Linked Ticket exists: 200 with safe summary
    - No linked Ticket: 404
    - Hidden Alert: 404 or project-standard denial
    Returns only actual safe Ticket fields, such as:
    id, ticket number, title, status, priority, service display,
    category display, assignee display, created timestamp, updated timestamp.
    Does not expose: internal notes, private attachments,
    requester credentials, full Ticket history, private paths.
    Does not create, update, synchronize, resolve, or reopen the Ticket.
    """

    serializer_class = MonitoringAlertTicketSerializer
    queryset = None

    def get_queryset(self):
        """Return the ticket linked to the alert if it exists."""
        alert_id = self.kwargs.get("pk")
        user = self.request.user

        # Verify alert access
        alert, error = AlertAccessHelper.get_alert(alert_id, user)
        if error:
            return None

        # Return the ticket if it exists; otherwise None (will trigger 404)
        if alert.ticket_id:
            return alert.ticket
        return None

    def retrieve(self, request, *args, **kwargs):
        """Return ticket summary or 404 if no linked ticket."""
        alert_id = self.kwargs.get("pk")
        user = self.request.user

        # Verify alert access
        alert, error = AlertAccessHelper.get_alert(alert_id, user)
        if error:
            return error

        # Check if ticket exists
        if not alert.ticket_id:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Return the ticket with read-only serializer
        ticket = alert.ticket
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)
class AlertHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only View for GET /api/monitoring/alerts/{id}/history/.

    Uses the authoritative Alert History relation.
    Returns only safe fields.
    Sanitizes structured details recursively. Redacts values for keys containing:
    secret, token, authorization, cookie, signature, password, payload,
    private_path, traceback, exception.
    Bounds free-text summaries to 500 characters.
    Orders by timestamp and ID.
    """

    serializer_class = MonitoringAlertHistorySerializer
    pagination_class = StandardResultsSetPagination
    queryset = MonitoringAlertHistory.objects.none()

    def get_queryset(self):
        """Return history entries related to the requested alert with ordering."""
        alert_id = self.kwargs.get("pk")
        user = self.request.user

        # Verify alert access
        alert, error = AlertAccessHelper.get_alert(alert_id, user)
        if error:
            return MonitoringAlertHistory.objects.none()

        # Use the authoritative History Model with alert relation
        queryset = MonitoringAlertHistory.objects.filter(alert_id=alert_id).order_by("-created_at", "id")

        return queryset

    def list(self, request, *args, **kwargs):
        """Return paginated response with sanitized sensitive keys."""
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is None:
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)

        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)
class AlertEventsViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only View for GET /api/monitoring/alerts/{id}/events/.

    Returns paginated alert events using the Alert-to-Event or Alert-to-Occurrence relation.
    Uses actual Model relations and field names.
    Returns safe operational fields only.
    Never exposes: raw payload, request body, Authorization header, Cookie,
    signature, Source secret, private path, traceback, raw exception.
    Uses deterministic ordering by an actual timestamp and primary key.
    Uses select_related where relevant.
    """

    serializer_class = MonitoringAlertEventSerializer
    pagination_class = StandardResultsSetPagination
    queryset = MonitoringEvent.objects.none()

    def get_queryset(self):
        """Return events related to the requested alert with scope and ordering."""
        alert_id = self.kwargs.get("pk")
        user = self.request.user

        # Verify alert access
        alert, error = AlertAccessHelper.get_alert(alert_id, user)
        if error:
            return MonitoringEvent.objects.none()

        event = alert.latest_event or alert.first_event
        if not event:
            return MonitoringEventOccurrence.objects.none()

        queryset = (
            MonitoringEventOccurrence.objects.filter(event=event)
            .select_related("event", "event__source")
            .order_by("occurred_at", "id")
        )

        return queryset

    def list(self, request, *args, **kwargs):
        """Return paginated response with safe fields only."""
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is None:
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)

        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)
class AlertAccessHelper:
    """Helper to retrieve an Alert with permission enforcement.

    - Denies anonymous users
    - Denies inactive users
    - Denies unknown roles
    - Follows existing Employee scope
    - Prevents hidden-Alert enumeration
    - Returns established 403 or 404 behavior
    """

    @staticmethod
    def get_alert(alert_id, user):
        """Retrieve the alert if the user has permission, otherwise return None.

        Returns (alert, None) on success or (None, Response) on failure.
        """
        try:
            alert = MonitoringAlert.objects.get(pk=alert_id)
        except MonitoringAlert.DoesNotExist:
            return None, Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if isinstance(user, AnonymousUser) or not user.is_authenticated:
            return None, Response(
                {"detail": "Authentication credentials were not provided."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user.is_active:
            return None, Response(
                {"detail": "User account is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        role = getattr(user, "role", None)
        if role not in {"system_admin", "it_manager", "it_support", "employee"}:
            return None, Response(
                {"detail": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return alert, None
