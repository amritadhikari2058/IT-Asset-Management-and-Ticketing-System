"""Serializers for MonitoringAutomationPolicy CRUD operations."""

import re

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework import serializers

from .models import MonitoringAutomationPolicy, MonitoringSource
from .ticket_automation import MonitoringAutomationPolicyValidator

User = get_user_model()


class MonitoringAutomationPolicySerializer(serializers.ModelSerializer):
    """Serializer for MonitoringAutomationPolicy CRUD.

    Exposes only real model fields. Server-controlled timestamps are read-only.
    eligible_sources uses ManyToMany deterministic serialization.
    """

    eligible_sources = serializers.PrimaryKeyRelatedField(
        queryset=MonitoringSource.objects.all(),
        many=True,
        required=False,
    )
    default_assignee = serializers.SlugRelatedField(
        slug_field="username",
        read_only=True,
        required=False,
    )

    class Meta:
        model = MonitoringAutomationPolicy
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "source_filter",
            "eligible_sources",
            "minimum_severity",
            "eligible_alert_states",
            "target_service",
            "ticket_category",
            "default_priority",
            "default_queue",
            "default_assignee",
            "auto_create",
            "auto_update",
            "auto_resolve",
            "reopen_behavior",
            "maximum_retries",
            "effective_from",
            "effective_until",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        """Serialize eligible sources deterministically as safe metadata."""
        from .serializers import MonitoringSourceListSerializer

        data = super().to_representation(instance)
        sources = instance.eligible_sources.all().order_by("pk")
        data["eligible_sources"] = MonitoringSourceListSerializer(
            sources, many=True
        ).data
        return data

    def validate(self, attrs):
        """Enforce cross-field business rules."""
        # effective_from must be earlier than effective_until when both exist
        effective_from = attrs.get("effective_from")
        effective_until = attrs.get("effective_until")

        if effective_from and effective_until:
            if effective_from >= effective_until:
                raise serializers.ValidationError({
                    "effective_from": "effective_from must be earlier than effective_until.",
                })

        # source_filter validation: selective requires at least one source;
        # all-sources must not have selected sources
        source_filter = attrs.get("source_filter")
        eligible_sources = attrs.get("eligible_sources", [])

        if source_filter == MonitoringAutomationPolicy.SourceFilter.SELECTIVE:
            if not eligible_sources:
                raise serializers.ValidationError({
                    "eligible_sources": "A selective-source policy requires at least one eligible source.",
                })
        elif source_filter == MonitoringAutomationPolicy.SourceFilter.ALL:
            if eligible_sources:
                raise serializers.ValidationError({
                    "eligible_sources": "An all-Sources policy must not depend on selected Sources.",
                })

        # Validate every eligible source exists and is accessible
        source_objects = eligible_sources if isinstance(eligible_sources, list) else []
        if source_objects:
            for source in source_objects:
                pk = getattr(source, "pk", source)
                if not MonitoringSource.objects.filter(pk=pk).exists():
                    raise serializers.ValidationError({
                        "eligible_sources": f"Source with pk={pk} does not exist or is not accessible.",
                    })

        # minimum_severity must use the Model's supported choices
        minimum_severity = attrs.get("minimum_severity")
        minimum_severity_choices = dict(
            MonitoringAutomationPolicy.MinimumSeverity.choices
        )
        if minimum_severity and minimum_severity not in minimum_severity_choices:
            raise serializers.ValidationError({
                "minimum_severity": f"Invalid minimum_severity. Must be one of: {list(minimum_severity_choices)}.",
            })

        # eligible_alert_states must contain only valid Alert states
        eligible_alert_states = attrs.get("eligible_alert_states")
        eligible_state_choices = dict(
            MonitoringAutomationPolicy.EligibleAlertState.choices
        )
        if eligible_alert_states and eligible_alert_states not in eligible_state_choices:
            raise serializers.ValidationError({
                "eligible_alert_states": f"Invalid eligible_alert_states. Must be one of: {list(eligible_state_choices)}.",
            })

        # target_service must pass existing service-mapping validation
        target_service = attrs.get("target_service")
        if target_service:
            _VALID_TARGET_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")
            if not _VALID_TARGET_SERVICE.match(target_service):
                raise serializers.ValidationError({
                    "target_service": "target_service must match the existing service-mapping pattern.",
                })

        # ticket_category must pass existing category-mapping validation
        ticket_category = attrs.get("ticket_category")
        if ticket_category:
            from tickets.models import TicketCategory
            if not TicketCategory.objects.filter(
                name=ticket_category, is_active=True, is_deleted=False
            ).exists():
                raise serializers.ValidationError({
                    "ticket_category": "ticket_category must pass the existing category-mapping validation.",
                })

        # default_priority must use the Ticket domain's supported values
        default_priority = attrs.get("default_priority")
        if default_priority:
            from tickets.models import Ticket
            valid_priorities = Ticket._meta.get_field("priority").choices
            valid_priority_vals = [str(v[0]) for v in valid_priorities]
            if default_priority not in valid_priority_vals:
                raise serializers.ValidationError({
                    "default_priority": f"Invalid default_priority. Must be one of: {valid_priority_vals}.",
                })

        reopen_behavior = attrs.get("reopen_behavior")
        allowed_reopen_behaviors = {
            "",
            "reopen",
            "auto_reopen",
            "yes",
            "true",
            "reopen_ticket",
            "reopen on new event",
        }
        if reopen_behavior and reopen_behavior not in allowed_reopen_behaviors:
            raise serializers.ValidationError({
                "reopen_behavior": "Invalid reopen_behavior.",
            })

        maximum_retries = attrs.get("maximum_retries")
        if maximum_retries is not None and not 0 <= maximum_retries <= 100:
            raise serializers.ValidationError({
                "maximum_retries": "maximum_retries must be between 0 and 100.",
            })

        return attrs

    def create(self, validated_data):
        """Create the policy and handle eligible_sources ManyToMany."""
        eligible_sources = validated_data.pop("eligible_sources", [])
        instance = super().create(validated_data)
        if eligible_sources is not None:
            instance.eligible_sources.set(eligible_sources)
        return instance

    def update(self, instance, validated_data):
        """Update the policy and handle eligible_sources ManyToMany."""
        eligible_sources = validated_data.pop("eligible_sources", None)
        instance = super().update(instance, validated_data)
        if eligible_sources is not None:
            instance.eligible_sources.set(eligible_sources)
        return instance
