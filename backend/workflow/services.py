"""Automation rule engine (workflows app).

Runs enabled AutomationRules whose trigger matches a ticket event,
checks the rule's equality conditions against the ticket's current
state, executes the action list and records one RuleExecution row per
rule that reached its actions. Called inline from the ticket
create/update paths (see tickets.views) so executions share the
request's transaction; never recursed to prevent loops.
"""
import logging

from django.db import transaction
from django.utils import timezone

from common.models import Notification
from tickets.models import Ticket, TicketHistory, TicketNote
from .models import AutomationRule, RuleExecution

log = logging.getLogger(__name__)

#: Guards against mutually-triggering rule chains.
MAX_DEPTH = 3


def is_ticket_staff(user):
    """IT Manager / IT Support / System Admin check (shared)."""
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in
             ("system_admin", "it_manager", "it_support")
             or getattr(user, "is_superuser", False)))


def ticket_visible_qs(user):
    """Queryset of tickets the user may act on (mirrors ticket visibility:
    staff see all; employees see own + home-department tickets)."""
    qs = Ticket.objects.select_related(
        "category", "requester", "assignee", "department").all()
    if is_ticket_staff(user):
        return qs
    from django.db.models import Q
    filt = Q(requester=user)
    if getattr(user, "home_department_id", None):
        filt |= Q(department_id=user.home_department_id)
    return qs.filter(filt)


def _ticket_is_deletable(ticket):
    return ticket is not None and getattr(ticket, "pk", None) is not None


def _check_conditions(rule, ticket):
    """Return (matches, human-readable condition summary) for a rule."""
    conds = rule.conditions or {}
    if "category_id" in conds and ticket.category_id != conds["category_id"]:
        return False
    if "department_id" in conds and \
            ticket.department_id != conds["department_id"]:
        return False
    if "priority" in conds and ticket.priority != conds["priority"]:
        return False
    if "status" in conds and ticket.status != conds["status"]:
        return False
    if "assignee_id" in conds and \
            ticket.assignee_id != conds["assignee_id"]:
        return False
    return True


def _history_note(ticket, rule, note, old=None, new=None):
    TicketHistory.objects.create(
        ticket=ticket, actor=rule.created_by, action="automation",
        old_values=old or {}, new_values=new or {},
        note=f"Rule '{rule.name}': {note}"[:500])


def _exec_action(action, ticket, rule, results):
    """Run one action dict; append an outcome entry. Raises on failure."""
    t = action.get("type")
    if t == "assign":
        from accounts.models import User
        uid = action.get("user_id")
        user = User.objects.filter(pk=uid, is_active=True).first()
        if user is None:
            raise ValueError(f"user #{uid} not found or inactive")
        if ticket.assignee_id != user.pk:
            old = ticket.assignee_id
            ticket.assignee = user
            ticket.save(update_fields=["assignee", "updated_at"])
            _history_note(ticket, rule, f"set assignee {old} -> {user.pk}",
                          old={"assignee": old},
                          new={"assignee": user.pk})
            results.append(f"assignee {old} -> {user.pk}")
        else:
            results.append(f"assignee already #{uid}; no change")
    elif t == "priority":
        pri = action.get("value")
        if ticket.priority != pri:
            old = ticket.priority
            ticket.priority = pri
            ticket.save(update_fields=["priority", "updated_at"])
            _history_note(ticket, rule, f"set priority {old} -> {pri}",
                          old={"priority": old}, new={"priority": pri})
            results.append(f"priority {old} -> {pri}")
        else:
            results.append(f"priority already {pri}; no change")
    elif t == "status":
        val = action.get("value")
        if ticket.status == val:
            results.append(f"status already {val}; no change")
        elif not Ticket.can_transition(ticket.status, val):
            raise ValueError(
                f"invalid transition {ticket.status} -> {val}")
        else:
            old = ticket.status
            ticket.status = val
            if val == "resolved":
                ticket.resolved_at = timezone.now()
            elif val == "closed":
                ticket.closed_at = timezone.now()
            elif val in ("reopened", "in_progress", "open"):
                ticket.resolved_at = None
                ticket.closed_at = None
            ticket.save(update_fields=["status", "resolved_at",
                                       "closed_at", "updated_at"])
            _history_note(ticket, rule, f"set status {old} -> {val}",
                          old={"status": old}, new={"status": val})
            results.append(f"status {old} -> {val}")
    elif t == "note":
        text = action.get("text") or ""
        note = TicketNote.objects.create(
            ticket=ticket, author=rule.created_by, body=text,
            is_internal=True)
        results.append(f"note #{note.pk} created")
    elif t == "notify":
        uid = action.get("user_id")
        from accounts.models import User
        if uid not in (None, ""):
            recipient = User.objects.filter(pk=uid, is_active=True).first()
        else:
            recipient = ticket.assignee or ticket.requester
        if recipient is None or not getattr(recipient, "is_active", True):
            results.append("notify: no eligible user")
            return
        Notification.objects.create(
            recipient=recipient,
            title=f"Automation: ticket #{ticket.pk}",
            body=f"Rule '{rule.name}' processed this ticket.",
            entity_type="tickets.Ticket", object_id=str(ticket.pk))
        results.append(f"notified {recipient.pk}")
    else:
        raise ValueError(f"Unknown action {t}")


def run_rules(trigger, ticket, depth=0, visited=None):
    """Evaluate every enabled rule with this trigger against the ticket.

    Each rule whose conditions all match (empty conditions always match)
    has its actions executed inside two layers of protection: the caller
    usually runs inside the ticket request's transaction, and per rule
    execution has its own savepoint so one failing rule cannot poison
    the others. One RuleExecution row per rule that reached its actions.
    """
    if not _ticket_is_deletable(ticket):
        return 0
    if depth > MAX_DEPTH:
        return 0
    if visited is None:
        visited = set()
    created = 0
    rules = AutomationRule.objects.filter(
        is_enabled=True, trigger=trigger).order_by("id")
    for rule in rules:
        key = (rule.id, ticket.id, trigger)
        if key in visited:
            continue
        visited.add(key)
        if not _check_conditions(rule, ticket):
            continue
        results = []
        detail = ""
        try:
            with transaction.atomic():
                for act in rule.actions or []:
                    _exec_action(act, ticket, rule, results)
        except Exception as exc:  # noqa: BLE001 a rule failure is data
            log.exception("Action failed: rule=%s ticket=%s",
                          rule.pk, ticket.pk)
            with transaction.atomic():
                RuleExecution.objects.create(
                    rule=rule, ticket=ticket, success=False,
                    detail=f"{type(exc).__name__}: {exc}")
            created += 1
            # Refresh so a partial action application cannot leak.
            ticket.refresh_from_db()
            continue
        RuleExecution.objects.create(
            rule=rule, ticket=ticket, success=True,
            detail="; ".join(results) if results else "OK")
        created += 1
    return created
