"""Real ticket automation services for Monitoring Phase 2.

All public functions in this module execute production code: they use the
existing Ticket model, authoritative ticket resolution services, real
database transactions, and shared in-app notifications.
"""

import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from common.audit import log_action
from common.notifications import notify_user
from monitoring.models import (
    MonitoringAlert,
    MonitoringAlertHistory,
    MonitoringAutomationPolicy,
    TargetMapping,
)
from services.models import ServiceCatalogueItem
from tickets.models import (
    Ticket,
    TicketCategory,
    TicketHistory,
    TicketQueue,
    TicketResolutionCode,
)


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

_TICKET_PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_ALERT_PRIORITY = {
    "info": "low",
    "low": "low",
    "warning": "medium",
    "medium": "medium",
    "minor": "medium",
    "high": "high",
    "major": "high",
    "critical": "critical",
}

_VALID_TARGET_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")
_SENSITIVE_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|signature|authorization|"
    r"credential|private[_-]?key)\b\s*[:=]\s*[\"']?[^\s,;}\"']+"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_AUTOMATION_ACTIONS = frozenset({
    "created_from_monitoring_alert",
    "ticket_updated",
})
_NON_CREATION_STATUSES = frozenset({"recovered", "resolved", "closed"})
_FIRING_STATUSES = frozenset({"new", "open", "acknowledged"})
_REOPEN_BEHAVIORS = frozenset({"reopen", "auto_reopen", "yes", "true", "reopen_ticket"})

_MAX_TITLE = 255
_MAX_DESCRIPTION = 4000
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BATCH_SIZE = 50
_MAX_BATCH_SIZE = 100

_HISTORY_EVENTS = {
    "created_from_monitoring_alert": MonitoringAlertHistory.EventType.TICKET_CREATED,
    "ticket_updated": MonitoringAlertHistory.EventType.TICKET_UPDATED,
    "alert_reopened": MonitoringAlertHistory.EventType.REOPENED,
}


class AutomationError(Exception):
    """Safe, code-only automation failure."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class MonitoringAutomationPolicyValidator:
    """Validates whether an alert is eligible for automated ticket creation."""

    @classmethod
    def check_alert_eligibility(cls, alert, ignore_alert_state=False):
        if getattr(alert, "policy_id", None):
            policy = alert.policy
            if not policy.is_active:
                return {"eligible": False, "reason": "no active policy", "policy": policy}
            return cls._evaluate(alert, policy, ignore_alert_state)

        policies = MonitoringAutomationPolicy.objects.filter(is_active=True).order_by("name", "pk")
        if not policies.exists():
            return {"eligible": False, "reason": "no active policy", "policy": None}

        result = None
        for policy in policies:
            result = cls._evaluate(alert, policy, ignore_alert_state)
            if result["eligible"]:
                return result
        return result

    @staticmethod
    def _evaluate(alert, policy, ignore_alert_state=False):
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

        if not ignore_alert_state and alert.status != policy.eligible_alert_states:
            return {"eligible": False, "reason": "alert state not eligible", "policy": None}

        if policy.target_service and not _VALID_TARGET_SERVICE.match(policy.target_service):
            return {"eligible": False, "reason": "invalid target service", "policy": None}

        return {"eligible": True, "reason": None, "policy": policy}


def _safe_text(value, limit):
    text = "" if value is None else str(value)
    text = _SENSITIVE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _safe_summary(alert):
    source_code = getattr(getattr(alert, "source", None), "code", "") or ""
    first_seen = getattr(alert, "first_seen_at", None)
    parts = [
        f"Alert {alert.alert_number} severity={alert.severity} status={alert.status}",
        _safe_text(alert.summary or alert.title, 1200),
        f"Source: {source_code}" if source_code else "",
        f"First seen: {first_seen.isoformat()}" if first_seen else "",
    ]
    return "\n".join(part for part in parts if part)[:_MAX_DESCRIPTION]


def _ticket_title(alert):
    return _safe_text(f"[MON-{str(alert.severity).upper()}] {alert.title}", _MAX_TITLE)


def _usable_user(user):
    return bool(
        user
        and getattr(user, "pk", None)
        and getattr(user, "is_active", True)
        and not getattr(user, "is_deleted", False)
    )


def _is_it_staff(user):
    return bool(
        _usable_user(user)
        and (
            getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
            or getattr(user, "is_superuser", False)
        )
    )


def _resolve_actor(alert, policy, require_staff=True):
    candidates = [
        getattr(policy, "default_assignee", None),
        getattr(alert, "assigned_to", None),
        getattr(alert, "acknowledged_by", None),
    ]
    for user in candidates:
        if _usable_user(user) and (not require_staff or _is_it_staff(user)):
            return user

    users = get_user_model().objects.filter(is_active=True, is_deleted=False)
    if require_staff:
        actor = users.filter(
            Q(role__in=("system_admin", "it_manager", "it_support")) | Q(is_superuser=True)
        ).order_by("pk").first()
        if actor is None:
            raise AutomationError("NO_AUTOMATION_ACTOR")
        return actor

    actor = users.order_by("pk").first()
    if actor is None:
        raise AutomationError("NO_AUTOMATION_ACTOR")
    return actor


def _resolve_assignee(policy):
    candidate = getattr(policy, "default_assignee", None)
    return candidate if _usable_user(candidate) else None


def _resolve_service(alert, policy):
    name = (getattr(policy, "target_service", "") or "").strip()
    if name:
        service = (
            ServiceCatalogueItem.objects.filter(
                name__iexact=name, is_active=True, is_deleted=False
            )
            .order_by("pk")
            .first()
        )
        if service is None:
            raise AutomationError("INVALID_SERVICE")
        return service

    current = getattr(alert, "service_catalogue_item", None)
    if current is not None:
        return current if current.is_active and not current.is_deleted else None

    if alert.source_id and getattr(alert, "target_identifier", ""):
        mapping = (
            TargetMapping.objects.filter(
                source_id=alert.source_id,
                source_target_identifier=alert.target_identifier,
                is_active=True,
                service_catalogue_item__isnull=False,
            )
            .order_by("-confidence", "-created_at", "-pk")
            .first()
        )
        if mapping is not None and mapping.service_catalogue_item.is_active:
            return mapping.service_catalogue_item
    return None


def _resolve_category(policy, alert):
    name = (
        (getattr(policy, "ticket_category", "") or "")
        or (getattr(alert, "category", "") or "")
        or "Monitoring"
    ).strip()[:100] or "Monitoring"
    category, _created = TicketCategory.objects.get_or_create(
        name=name, defaults={"is_active": True}
    )
    return category


def _resolve_queue(policy, alert):
    code = (
        (getattr(policy, "default_queue", "") or "")
        or (getattr(alert, "queue", "") or "")
    ).strip()
    if not code:
        return None
    queue = (
        TicketQueue.objects.filter(
            Q(code__iexact=code) & Q(is_active=True) & Q(is_deleted=False)
        )
        .order_by("pk")
        .first()
    )
    if queue is None:
        raise AutomationError("INVALID_QUEUE")
    return queue


def _resolve_department(alert, actor):
    from accounts.models import Department

    name = (getattr(alert, "department", "") or "").strip()
    if name:
        department = Department.objects.filter(
            Q(name__iexact=name) | Q(code__iexact=name)
        ).order_by("pk").first()
        if department is not None:
            return department
    return getattr(actor, "home_department", None)


def _resolve_priority(alert, policy):
    configured = (getattr(policy, "default_priority", "") or "").strip().lower()
    if configured in _TICKET_PRIORITY_RANK:
        return configured
    return _ALERT_PRIORITY.get(alert.severity, "medium")


def _snapshot(alert, ticket, service, history_id=None):
    return {
        "ticket_id": ticket.pk,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "category_id": ticket.category_id,
        "queue_id": ticket.queue_id,
        "assignee_id": ticket.assignee_id,
        "service_catalogue_item_id": service.pk if service else None,
        "event_count": alert.event_count,
        "severity": alert.severity,
        "version": ticket.version,
        "history_id": history_id,
    }


def _manual_fields(ticket, alert, snapshot):
    manual = set()
    comparisons = (
        ("description", ticket.description, snapshot.get("description")),
        ("priority", ticket.priority, snapshot.get("priority")),
        ("category", ticket.category_id, snapshot.get("category_id")),
        ("queue", ticket.queue_id, snapshot.get("queue_id")),
        ("assignee", ticket.assignee_id, snapshot.get("assignee_id")),
        (
            "service",
            alert.service_catalogue_item_id,
            snapshot.get("service_catalogue_item_id"),
        ),
    )
    for field, current, previous in comparisons:
        if current != previous:
            manual.add(field)

    history_id = snapshot.get("history_id")
    if history_id and TicketHistory.objects.filter(
        ticket=ticket, id__gt=history_id
    ).exclude(action__in=_AUTOMATION_ACTIONS).exists():
        manual.add("manual_history")
    return manual


def _write_monitoring_history(alert, event_type, detail=""):
    return MonitoringAlertHistory.objects.create(
        alert=alert,
        event=alert.latest_event,
        event_type=event_type,
        detail=_safe_text(detail, 500),
    )


def _write_automation_history(ticket, alert, action, old=None, new=None):
    entry = TicketHistory.objects.create(
        ticket=ticket,
        actor=None,
        action=action,
        old_values=old or {},
        new_values=new or {},
        note=_safe_text(f"Monitoring alert {alert.alert_number}", 500),
    )
    _write_monitoring_history(alert, _HISTORY_EVENTS[action], f"Ticket #{ticket.pk}")
    return entry


def _notify_after_commit(alert, ticket, title, message, category):
    recipient = ticket.assignee or ticket.requester

    def _emit():
        notify_user(
            recipient,
            category,
            title,
            message,
            entity_type="monitoring.automation",
            object_id=str(ticket.pk),
            dedupe=True,
            post_commit=False,
        )

    transaction.on_commit(_emit)


def _refresh(alert):
    try:
        alert.refresh_from_db()
    except Exception:
        pass


def _code_for_exception(exc):
    if isinstance(exc, AutomationError):
        return exc.code
    if isinstance(exc, IntegrityError):
        return "DATABASE_CONFLICT"
    return {
        "ValidationError": "INVALID_TICKET_TRANSITION",
        "PermissionDenied": "AUTOMATION_PERMISSION_DENIED",
        "ConflictError": "TICKET_CONCURRENCY_CONFLICT",
    }.get(type(exc).__name__, "TICKET_AUTOMATION_FAILED")


def _record_failure(alert, code):
    code = _safe_text(code or "TICKET_AUTOMATION_FAILED", 50).upper() or "TICKET_AUTOMATION_FAILED"
    try:
        with transaction.atomic():
            MonitoringAlert.objects.filter(pk=alert.pk).update(
                automation_error_code=code,
                automation_error_summary=f"Automation failed ({code}).",
                automation_retry_count=F("automation_retry_count") + 1,
                automation_last_attempt_at=timezone.now(),
            )
            _write_monitoring_history(
                MonitoringAlert.objects.get(pk=alert.pk),
                MonitoringAlertHistory.EventType.AUTOMATION_FAILED,
                code,
            )
    except Exception:
        pass
    _refresh(alert)


def _clear_failure_fields(alert):
    MonitoringAlert.objects.filter(pk=alert.pk).update(
        automation_error_code="",
        automation_error_summary="",
        automation_last_attempt_at=timezone.now(),
    )


def _append_occurrence(description, alert):
    line = _safe_text(
        f"Occurrence {alert.event_count}: severity={alert.severity} "
        f"at {alert.last_seen_at.isoformat() if alert.last_seen_at else ''}",
        240,
    )
    base = description or ""
    if line in base:
        return base[-_MAX_DESCRIPTION:]
    return (base + "\n" + line)[-_MAX_DESCRIPTION:]


def _eligible_policy(alert, ignore_state=False):
    result = MonitoringAutomationPolicyValidator.check_alert_eligibility(
        alert, ignore_alert_state=ignore_state
    )
    if not result.get("eligible") or result.get("policy") is None:
        return None
    return result["policy"]


def _is_recurrence(alert, ticket, policy):
    return bool(
        (getattr(policy, "reopen_behavior", "") or "").strip().lower() in _REOPEN_BEHAVIORS
        and alert.status in _FIRING_STATUSES
        and ticket.status in ("resolved", "closed")
        and alert.auto_resolved
    )


def ensure_ticket_for_alert(alert, actor=None):
    """Create exactly one Ticket for an eligible alert and link it atomically."""
    ticket = None
    created = False
    try:
        with transaction.atomic():
            locked = MonitoringAlert.objects.select_for_update().get(pk=alert.pk)

            if locked.ticket_id:
                ticket = locked.ticket
                if locked.automation_error_code:
                    _clear_failure_fields(locked)
                _refresh(alert)
                return ticket, False

            policy = _eligible_policy(locked)
            if policy is None or not policy.auto_create:
                return None, False
            if locked.status in _NON_CREATION_STATUSES:
                return None, False

            automation_actor = actor or _resolve_actor(locked, policy, require_staff=True)
            service = _resolve_service(locked, policy)
            category = _resolve_category(policy, locked)
            queue = _resolve_queue(policy, locked)
            department = _resolve_department(locked, automation_actor)
            assignee = _resolve_assignee(policy)
            priority = _resolve_priority(locked, policy)

            ticket = Ticket.objects.create(
                title=_ticket_title(locked),
                description=_safe_summary(locked),
                category=category,
                priority=priority,
                status="open",
                requester=automation_actor,
                assignee=assignee,
                department=department,
                asset=locked.asset,
                queue=queue,
            )
            history = _write_automation_history(
                ticket,
                locked,
                "created_from_monitoring_alert",
                new={"status": "open", "priority": priority},
            )
            snapshot = _snapshot(locked, ticket, service, history.pk)

            MonitoringAlert.objects.filter(pk=locked.pk).update(
                ticket=ticket,
                policy=policy,
                auto_ticket_created=True,
                auto_resolved=False,
                automation_snapshot=snapshot,
                automation_error_code="",
                automation_error_summary="",
                automation_last_attempt_at=timezone.now(),
                service_catalogue_item=service,
                category=(policy.ticket_category or locked.category or "")[:100],
                queue=(policy.default_queue or locked.queue or "")[:50],
            )
            log_action(
                actor=automation_actor,
                action="create",
                instance=ticket,
                details={"source": "monitoring_alert", "alert_id": locked.pk},
            )
            _notify_after_commit(
                locked,
                ticket,
                "Monitoring alert ticket created",
                f"Ticket #{ticket.pk} was created for alert {locked.alert_number}.",
                "monitoring_ticket_created",
            )
            created = True
    except Exception as exc:
        _record_failure(alert, _code_for_exception(exc))
        return None, False

    _refresh(alert)
    return ticket, created


def sync_ticket_from_alert(alert, actor=None):
    """Synchronize allowed alert changes into an existing linked Ticket."""
    ticket = None
    changed = False
    try:
        with transaction.atomic():
            locked = MonitoringAlert.objects.select_for_update().get(pk=alert.pk)
            if not locked.ticket_id:
                return None, False
            ticket = Ticket.objects.select_for_update().get(pk=locked.ticket_id)

            policy = _eligible_policy(locked)
            if policy is None or not policy.auto_update:
                return ticket, False

            snapshot = locked.automation_snapshot or {}
            manual = _manual_fields(ticket, locked, snapshot)
            automation_actor = actor or _resolve_actor(locked, policy, require_staff=True)

            if _is_recurrence(locked, ticket, policy) and "manual_history" not in manual:
                from tickets import resolution_services

                resolution_services.reopen_ticket(
                    ticket,
                    {
                        "reason": _safe_text(
                            f"Monitoring recurrence for alert {locked.alert_number}", 200
                        ),
                        "expected_ticket_version": ticket.version,
                    },
                    automation_actor,
                )
                _write_monitoring_history(
                    locked,
                    MonitoringAlertHistory.EventType.REOPENED,
                    f"Ticket #{ticket.pk} reopened by monitoring recurrence",
                )
                ticket.refresh_from_db()
                snapshot["version"] = ticket.version
                snapshot["history_id"] = (
                    TicketHistory.objects.filter(ticket=ticket)
                    .order_by("-id")
                    .values_list("id", flat=True)
                    .first()
                )
                snapshot["auto_resolved"] = False
                changed = True
                MonitoringAlert.objects.filter(pk=locked.pk).update(
                    auto_resolved=False,
                    automation_snapshot=snapshot,
                    automation_error_code="",
                    automation_error_summary="",
                    automation_last_attempt_at=timezone.now(),
                )

            if locked.status in _NON_CREATION_STATUSES:
                if changed:
                    MonitoringAlert.objects.filter(pk=locked.pk).update(
                        auto_resolved=False,
                        automation_snapshot=snapshot,
                        automation_error_code="",
                        automation_error_summary="",
                        automation_last_attempt_at=timezone.now(),
                    )
                    _notify_after_commit(
                        locked,
                        ticket,
                        "Monitoring ticket reopened",
                        f"Ticket #{ticket.pk} was reopened for alert {locked.alert_number}.",
                        "monitoring_ticket_status_change",
                    )
            else:
                service = _resolve_service(locked, policy)
                category = _resolve_category(policy, locked)
                queue = _resolve_queue(policy, locked)
                assignee = _resolve_assignee(policy)
                desired_priority = _resolve_priority(locked, policy)
                updates = {}

                if "priority" not in manual:
                    current_rank = _TICKET_PRIORITY_RANK.get(ticket.priority, 1)
                    desired_rank = _TICKET_PRIORITY_RANK.get(desired_priority, 1)
                    if desired_rank > current_rank:
                        updates["priority"] = desired_priority
                if "category" not in manual and ticket.category_id != category.pk:
                    updates["category_id"] = category.pk
                if "queue" not in manual and ticket.queue_id != (queue.pk if queue else None):
                    updates["queue_id"] = queue.pk if queue else None
                if "assignee" not in manual and ticket.assignee_id != (assignee.pk if assignee else None):
                    updates["assignee_id"] = assignee.pk if assignee else None
                if "description" not in manual and locked.event_count > int(snapshot.get("event_count") or 0):
                    updated_description = _append_occurrence(ticket.description, locked)
                    if updated_description != ticket.description:
                        updates["description"] = updated_description

                if "service" not in manual and locked.service_catalogue_item_id != (
                    service.pk if service else None
                ):
                    MonitoringAlert.objects.filter(pk=locked.pk).update(
                        service_catalogue_item=service
                    )

                if updates:
                    updates["version"] = (ticket.version or 1) + 1
                    old_values = {
                        field: getattr(ticket, field) for field in updates if field != "version"
                    }
                    Ticket.objects.filter(pk=ticket.pk).update(**updates)
                    ticket.refresh_from_db()
                    history = _write_automation_history(
                        ticket, locked, "ticket_updated", old=old_values, new=updates
                    )
                    new_snapshot = _snapshot(locked, ticket, service, history.pk)
                    if snapshot.get("auto_resolved") is False:
                        new_snapshot["auto_resolved"] = False
                    MonitoringAlert.objects.filter(pk=locked.pk).update(
                        auto_resolved=False,
                        automation_snapshot=new_snapshot,
                        automation_error_code="",
                        automation_error_summary="",
                        automation_last_attempt_at=timezone.now(),
                    )
                    changed = True

            if changed:
                _notify_after_commit(
                    locked,
                    ticket,
                    "Monitoring ticket updated",
                    f"Ticket #{ticket.pk} was updated for alert {locked.alert_number}.",
                    "monitoring_ticket_update",
                )
    except Exception as exc:
        _record_failure(alert, _code_for_exception(exc))
        return ticket, False

    _refresh(alert)
    return ticket, changed


def resolve_ticket_for_recovered_alert(alert, actor=None):
    """Resolve an existing Ticket through the authoritative ticket service."""
    ticket = None
    resolved = False
    try:
        with transaction.atomic():
            locked = MonitoringAlert.objects.select_for_update().get(pk=alert.pk)
            if not locked.ticket_id or locked.status != "recovered":
                return None, False
            ticket = Ticket.objects.select_for_update().get(pk=locked.ticket_id)

            policy = _eligible_policy(locked, ignore_state=True)
            if policy is None or not policy.auto_resolve:
                return ticket, False
            if ticket.status in ("resolved", "closed", "archived", "cancelled", "merged"):
                return ticket, False

            snapshot = locked.automation_snapshot or {}
            if _manual_fields(ticket, locked, snapshot):
                return ticket, False

            automation_actor = actor or _resolve_actor(locked, policy, require_staff=True)
            code = (
                TicketResolutionCode.objects.filter(is_active=True, is_deleted=False)
                .order_by("pk")
                .first()
            )
            if code is None:
                raise AutomationError("NO_RESOLUTION_CODE")

            from tickets import resolution_services

            resolution_services.resolve_ticket(
                ticket,
                {
                    "resolution_code": code.pk,
                    "resolution_summary": _safe_text(
                        f"Monitoring alert {locked.alert_number} recovered", 500
                    ),
                    "expected_ticket_version": ticket.version,
                },
                automation_actor,
            )
            ticket.refresh_from_db()
            _write_monitoring_history(
                locked,
                MonitoringAlertHistory.EventType.RESOLVED,
                f"Ticket #{ticket.pk} resolved after monitoring recovery",
            )
            latest_history_id = (
                TicketHistory.objects.filter(ticket=ticket)
                .order_by("-id")
                .values_list("id", flat=True)
                .first()
            )
            new_snapshot = dict(snapshot)
            new_snapshot.update(
                version=ticket.version,
                history_id=latest_history_id,
                status="resolved",
                auto_resolved=True,
            )
            MonitoringAlert.objects.filter(pk=locked.pk).update(
                auto_resolved=True,
                resolution_reason=_safe_text(
                    "Automatically resolved after monitoring recovery", 500
                ),
                automation_snapshot=new_snapshot,
                automation_error_code="",
                automation_error_summary="",
                automation_last_attempt_at=timezone.now(),
            )
            _notify_after_commit(
                locked,
                ticket,
                "Monitoring ticket resolved",
                f"Ticket #{ticket.pk} was resolved after alert {locked.alert_number} recovered.",
                "monitoring_ticket_status_change",
            )
            resolved = True
    except Exception as exc:
        _record_failure(alert, _code_for_exception(exc))
        return ticket, False

    _refresh(alert)
    return ticket, resolved


def _bound_batch_size(value, default=_DEFAULT_BATCH_SIZE):
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = default
    return max(1, min(size, _MAX_BATCH_SIZE))


def _retry_exhausted(alert):
    policy = getattr(alert, "policy", None)
    maximum = getattr(policy, "maximum_retries", _DEFAULT_MAX_RETRIES)
    return int(alert.automation_retry_count or 0) >= int(maximum)


def _dispatch(alert, actor=None):
    if alert.status == "recovered":
        _ticket, changed = resolve_ticket_for_recovered_alert(alert, actor=actor)
        return "resolved" if changed else "skipped"
    if alert.ticket_id:
        _ticket, changed = sync_ticket_from_alert(alert, actor=actor)
        return "updated" if changed else "skipped"
    _ticket, created = ensure_ticket_for_alert(alert, actor=actor)
    return "created" if created else "skipped"


def process_alerts_for_ticket_automation(batch_size=_DEFAULT_BATCH_SIZE, actor=None):
    """Process a bounded, deterministic batch without blocking sleeps."""
    summary = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "resolved": 0,
        "skipped": 0,
        "failed": 0,
    }
    alerts = (
        MonitoringAlert.objects.filter(status__in=_FIRING_STATUSES | {"recovered"})
        .order_by("first_seen_at", "pk")[: _bound_batch_size(batch_size)]
    )
    for alert in alerts:
        try:
            summary["processed"] += 1
            if alert.automation_error_code and _retry_exhausted(alert):
                summary["skipped"] += 1
                continue
            action = _dispatch(alert, actor=actor)
            summary[action] = summary.get(action, 0) + 1
        except Exception:
            _record_failure(alert, "BATCH_ITEM_FAILED")
            summary["failed"] += 1
    return summary


def retry_failed_ticket_automation(alerts=None, actor=None, batch_size=None):
    """Retry only alerts with active, non-exhausted automation failures."""
    if isinstance(alerts, MonitoringAlert):
        candidates = [alerts]
    elif alerts is None:
        candidates = list(
            MonitoringAlert.objects.exclude(automation_error_code="").order_by("pk")
        )
    else:
        candidates = list(alerts)
    candidates = sorted(candidates, key=lambda alert: alert.pk or 0)

    limit = _bound_batch_size(batch_size or len(candidates) or 1)
    summary = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    for alert in candidates[:limit]:
        if not alert.automation_error_code or _retry_exhausted(alert):
            summary["skipped"] += 1
            continue
        summary["attempted"] += 1
        try:
            _dispatch(alert, actor=actor)
        except Exception:
            _record_failure(alert, "RETRY_FAILED")
        _refresh(alert)
        if alert.automation_error_code:
            summary["failed"] += 1
        else:
            summary["succeeded"] += 1
    return summary
