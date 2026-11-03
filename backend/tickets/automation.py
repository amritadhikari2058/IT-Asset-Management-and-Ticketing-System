"""Ticket automation rule engine (workflows, Phase 19).

Runs active AutomationRules whose trigger matches a ticket event,
evaluates conditions against the current ticket state, executes actions
and records one WorkflowExecution row per rule that reached its action
list. Called inline (never via signals) from ticket create/update paths
and the SLA breach task, so executions share the request's transaction.
"""
import logging

from tickets.models import (
    AutomationRule, Ticket, TicketHistory, TicketNote, WorkflowExecution,
)

log = logging.getLogger(__name__)


def _ticket_value(ticket, field):
    if field == "status":
        return ticket.status
    if field == "priority":
        return ticket.priority
    if field == "title":
        return ticket.title
    return getattr(ticket, f"{field}_id", None)


def _condition_match(cond, ticket):
    """Return (matches: bool, human description) for one condition."""
    field = cond.get("field")
    operator = cond.get("operator")
    target = cond.get("value")
    actual = _ticket_value(ticket, field)
    ok = False
    if operator == "equals":
        ok = actual == target
    elif operator == "not_equals":
        ok = actual != target
    elif operator == "in":
        targets = target if isinstance(target, (list, tuple)) else [target]
        ok = actual in targets
    elif operator == "contains":
        ok = (str(target or "").lower()
              in str(actual or "").lower())
    else:
        ok = False
    return ok, f"{field} {operator} {target!r}"


def _history_note(ticket, rule, note):
    TicketHistory.objects.create(
        ticket=ticket, actor=rule.created_by, action="automation",
        old_values={}, new_values={
            "rule": rule.name, "rule_id": rule.pk},
        note=note[:500])


def _exec_add_note(ticket, rule, params, results):
    note = TicketNote.objects.create(
        ticket=ticket,
        author=rule.created_by,
        body=params.get("body", ""),
        is_internal=bool(params.get("is_internal", True)))
    results.append({"type": "add_note",
                    "result": f"note #{note.pk} created"})


def _exec_set_priority(ticket, rule, params, results):
    pri = params.get("priority")
    if ticket.priority == pri:
        results.append({"type": "set_priority",
                        "result": f"already {pri}; no change"})
        return
    old = ticket.priority
    ticket.priority = pri
    ticket.save(update_fields=["priority", "updated_at"])
    _history_note(ticket, rule, f"Rule '{rule.name}' set priority "
                                f"{old} -> {pri}.")
    results.append({"type": "set_priority",
                    "result": f"{old} -> {pri}"})


def _exec_assign(ticket, rule, params, results):
    from accounts.models import User
    uid = params.get("user_id")
    user = User.objects.filter(pk=uid, is_active=True).first()
    if user is None:
        raise ValueError(f"user #{uid} not found or inactive")
    if ticket.assignee_id == user.pk:
        results.append({"type": "assign",
                        "result": f"already assigned to #{uid}"})
        return
    old = ticket.assignee_id
    ticket.assignee = user
    ticket.save(update_fields=["assignee", "updated_at"])
    _history_note(ticket, rule, f"Rule '{rule.name}' set assignee "
                                f"{old} -> {user.pk}.")
    results.append({"type": "assign", "result": f"{old} -> {user.pk}"})


def _exec_notify(ticket, rule, params, results):
    from common.models import Notification
    to = params.get("to", "assignee")
    recipient = ticket.assignee if to == "assignee" else ticket.requester
    if recipient is None or \
            not getattr(recipient, "is_active", True) or \
            getattr(recipient, "is_deleted", False):
        results.append({"type": "notify", "result": "no eligible user"})
        return
    Notification.objects.create(
        recipient=recipient,
        title=f"Automation: ticket #{ticket.pk}",
        body=params.get("message", ""),
        entity_type="tickets.Ticket",
        object_id=str(ticket.pk))
    results.append({"type": "notify", "result": f"notified {to}"})


_ACTION_HANDLERS = {
    "add_note": _exec_add_note,
    "set_priority": _exec_set_priority,
    "assign": _exec_assign,
    "notify": _exec_notify,
}


def run_rules_for_ticket(ticket, trigger):
    """Evaluate + execute every active rule with this trigger.

    Only rule evaluations whose conditions all match run their actions
    and produce a WorkflowExecution row. Individual action failures mark
    the execution 'failure' but never abort the remaining actions.
    Returns the number of executions created.
    """
    if ticket is None or ticket.pk is None:
        return 0
    created = 0
    rules = AutomationRule.objects.filter(trigger=trigger, is_active=True)
    for rule in rules:
        matched = []
        all_ok = True
        for cond in rule.conditions or []:
            ok, desc = _condition_match(cond, ticket)
            entry = dict(cond)
            if ok:
                matched.append(entry)
            if not ok:
                all_ok = False
                break
        if not all_ok:
            continue
        results = []
        error = ""
        for act in rule.actions or []:
            handler = _ACTION_HANDLERS.get(act.get("type"))
            if handler is None:
                results.append({"type": act.get("type"),
                                "result": "unsupported action type (skipped)"})
                continue
            try:
                ticket.refresh_from_db()
                handler(ticket, rule, act.get("params") or {}, results)
            except Exception as exc:  # never abort other actions
                log.exception(
                    "Automation action failed: rule=%s ticket=%s",
                    rule.pk, ticket.pk)
                results.append({
                    "type": act.get("type"),
                    "result": f"failed: {type(exc).__name__}"})
                error = error or f"{type(exc).__name__}: {exc}"
        WorkflowExecution.objects.create(
            rule=rule, ticket=ticket, trigger=trigger,
            status="failure" if error else "success",
            matched_conditions=matched,
            results=results, error=error)
        created += 1
    return created
