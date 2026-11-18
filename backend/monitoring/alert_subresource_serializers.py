"""Serializers for Monitoring Alert sub-resource APIs."""

import re

from rest_framework import serializers

from monitoring.models import MonitoringAlertHistory, MonitoringEventOccurrence
from tickets.models import Ticket


class MonitoringAlertEventSerializer(serializers.ModelSerializer):
    event_identifier = serializers.CharField(source="event.event_id", read_only=True)
    event_type = serializers.CharField(source="event.event_type", read_only=True)
    severity = serializers.CharField(source="event.severity", read_only=True)
    status = serializers.CharField(source="event.event_state", read_only=True)
    source_name = serializers.CharField(source="event.source.name", read_only=True)
    target = serializers.SerializerMethodField()
    metric_name = serializers.CharField(source="event.metric_name", read_only=True)
    occurrence_count = serializers.SerializerMethodField()
    first_seen = serializers.DateTimeField(source="event.first_seen_at", read_only=True)
    last_seen = serializers.DateTimeField(source="event.last_seen_at", read_only=True)
    created_timestamp = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = MonitoringEventOccurrence
        fields = [
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
        ]
        read_only_fields = fields

    def get_target(self, obj):
        event = obj.event
        return event.target_identifier or event.hostname or event.service_name or ""

    def get_occurrence_count(self, obj):
        return obj.event.duplicate_count + 1

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for key in (
            "raw_payload",
            "event_body",
            "secret",
            "authorization",
            "cookie",
            "signature",
            "traceback",
            "exception_text",
        ):
            data.pop(key, None)
        return data


class MonitoringAlertHistorySerializer(serializers.ModelSerializer):
    event_action_type = serializers.CharField(source="event_type", read_only=True)
    safe_summary = serializers.SerializerMethodField()
    actor_display = serializers.SerializerMethodField()
    previous_state = serializers.CharField(source="previous_status", read_only=True)
    new_state = serializers.CharField(source="new_status", read_only=True)
    created_timestamp = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = MonitoringAlertHistory
        fields = [
            "id",
            "event_action_type",
            "safe_summary",
            "actor_display",
            "previous_state",
            "new_state",
            "created_timestamp",
        ]
        read_only_fields = fields

    def get_safe_summary(self, obj):
        summary = obj.detail or ""
        for key in (
            "secret",
            "token",
            "authorization",
            "cookie",
            "signature",
            "password",
            "payload",
            "private_path",
            "traceback",
            "exception",
        ):
            summary = re.sub(
                rf"(?i)({re.escape(key)}\s*[:=]\s*)[^\s,;]+",
                r"\1(redacted)",
                summary,
            )
        return summary[:500]

    def get_actor_display(self, obj):
        if not obj.actor:
            return ""
        return obj.actor.get_full_name() or obj.actor.username

    def to_representation(self, instance):
        data = super().to_representation(instance)
        sensitive_keys = {
            "secret",
            "token",
            "authorization",
            "cookie",
            "signature",
            "password",
            "payload",
            "private_path",
            "traceback",
            "exception",
        }
        for key in list(data):
            if key in sensitive_keys:
                data[key] = "(redacted)"
        return data


class MonitoringAlertTicketSerializer(serializers.ModelSerializer):
    ticket_number = serializers.SerializerMethodField()
    service = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.name", read_only=True)
    assignee_display = serializers.SerializerMethodField()
    created_timestamp = serializers.DateTimeField(source="created_at", read_only=True)
    updated_timestamp = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Ticket
        fields = [
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
        ]
        read_only_fields = fields

    def get_ticket_number(self, obj):
        return str(obj.pk)

    def get_service(self, obj):
        if not obj.department:
            return ""
        return obj.department.name

    def get_assignee_display(self, obj):
        if not obj.assignee:
            return ""
        return obj.assignee.get_full_name() or obj.assignee.username

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for key in (
            "internal_notes",
            "private_attachment",
            "requester_email",
            "requester_phone",
            "ssn",
            "credential_reference",
        ):
            data.pop(key, None)
        return data
