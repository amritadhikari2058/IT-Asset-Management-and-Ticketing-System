"""Escalation logic for monitoring module."""

from django.utils import timezone

from .models import MonitoringEscalationPolicy, AlertEscalationState


def evaluate_escalations():
    """Evaluate pending escalations for unacknowledged alerts.

    Returns list of escalated alert IDs.
    """
    now = timezone.now()
    escalated = []

    policies = MonitoringEscalationPolicy.objects.filter(is_active=True)

    for policy in policies:
        # Find unacknowledged alerts matching policy criteria
        from .models import MonitoringAlert
        alerts = MonitoringAlert.objects.filter(
            status__in=["new", "open"],
            severity__in=["major", "critical"],
            acknowledged_at__isnull=True,
        )

        for alert in alerts:
            try:
                state = AlertEscalationState.objects.get(alert=alert, policy=policy)
            except AlertEscalationState.DoesNotExist:
                # Create new escalation state
                state = AlertEscalationState(
                    alert=alert,
                    policy=policy,
                    level=1,
                    next_escalation_at=now,
                    state="pending",
                )
                state.save()

            if state.state != "active":
                continue

            if state.next_escalation_at <= now:
                # Escalate
                escalated.append(alert.id)
                state.escalation_count = (state.escalation_count or 0) + 1
                state.last_escalated_at = now
                state.next_escalation_at = now + timezone.timedelta(
                    minutes=policy.repeat_interval_minutes
                )
                state.save(update_fields=["escalation_count", "last_escalated_at", "next_escalation_at"])

    return escalated
