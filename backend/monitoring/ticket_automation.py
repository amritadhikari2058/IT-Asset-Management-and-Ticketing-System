"""Ticket automation eligibility utilities for Monitoring alerts."""

import re

from django.utils import timezone

from monitoring.models import MonitoringAutomationPolicy

_SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "warning": 1,
    "medium": 2,
    "minor": 2,
    "high": 3,
    "major": 3,
    "critical": 4,
}

_VALID_TARGET_SERVICE = re.compile(r"^[A-Za-z0-9_-]+$")


class MonitoringAutomationPolicyValidator:
    """Validates whether an alert is eligible for automated ticket creation."""

    @classmethod
    def check_alert_eligibility(cls, alert):
        if getattr(alert, "policy_id", None):
            policy = alert.policy
            if not policy.is_active:
                return {"eligible": False, "reason": "no active policy", "policy": policy}
            return cls._evaluate(alert, policy)

        policies = MonitoringAutomationPolicy.objects.filter(is_active=True)
        if not policies.exists():
            return {"eligible": False, "reason": "no active policy", "policy": None}

        result = None
        for policy in policies:
            result = cls._evaluate(alert, policy)
            if result["eligible"]:
                return result
        return result

    @staticmethod
    def _evaluate(alert, policy):
        now = timezone.now()

        if policy.effective_from and now < policy.effective_from:
            return {"eligible": False, "reason": "policy not yet effective", "policy": None}
        if policy.effective_until and now > policy.effective_until:
            return {"eligible": False, "reason": "policy no longer effective", "policy": None}

        if policy.source_filter == MonitoringAutomationPolicy.SourceFilter.SELECTIVE:
            if alert.source_id is None or not policy.eligible_sources.filter(pk=alert.source_id).exists():
                return {"eligible": False, "reason": "source not permitted by policy", "policy": None}

        if _SEVERITY_RANK.get(alert.severity, -1) < _SEVERITY_RANK.get(policy.minimum_severity, 0):
            return {"eligible": False, "reason": "severity below policy minimum", "policy": None}

        if alert.status != policy.eligible_alert_states:
            return {"eligible": False, "reason": "alert state not eligible", "policy": None}

        if policy.target_service and not _VALID_TARGET_SERVICE.match(policy.target_service):
            return {"eligible": False, "reason": "invalid target service", "policy": None}

        return {"eligible": True, "reason": None, "policy": policy}
