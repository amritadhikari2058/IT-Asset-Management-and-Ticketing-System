from django.db import transaction
from .models import AutomationRule, RuleExecution

MAX_DEPTH = 3

def _match(rule, ticket, trigger):
    if not rule.is_enabled or rule.trigger != trigger:
        return False
    c = rule.conditions or {}
    if "category_id" in c and ticket.category_id != c["category_id"]:
        return False
    if "priority" in c and ticket.priority != c["priority"]:
        return False
    if "department_id" in c and ticket.department_id != c["department_id"]:
        return False
    if "status" in c and ticket.status != c["status"]:
        return False
    return True

def _execute_action(action, ticket, rule, depth):
    from tickets.models import Ticket
    t = action.get("type")
    if t == "assign":
        uid = action.get("user_id")
        ticket.assigned_to_id = uid
        ticket.save(update_fields=["assigned_to"])
    elif t == "priority":
        ticket.priority = action.get("value")
        ticket.save(update_fields=["priority"])
    elif t == "status":
        ticket.status = action.get("value")
        ticket.save(update_fields=["status"])
    elif t == "note":
        from tickets.models import TicketComment
        TicketComment.objects.create(ticket=ticket, author=rule.created_by, body=action.get("text",""), is_internal=True)
    elif t == "notify":
        pass
    else:
        raise ValueError(f"Unknown action {t}")

import threading

_local = threading.local()

def _depth():
    return getattr(_local, "depth", 0)

def run_rules(trigger, ticket, depth=0, visited=None):
    if visited is None:
        visited = set()
    if depth > MAX_DEPTH:
        return
    for rule in AutomationRule.objects.filter(is_enabled=True, trigger=trigger):
        key = (rule.id, ticket.id, trigger)
        if key in visited:
            continue
        if not _match(rule, ticket, trigger):
            continue
        visited.add(key)
        try:
            with transaction.atomic():
                for a in rule.actions or []:
                    _execute_action(a, ticket, rule, depth)
                RuleExecution.objects.create(rule=rule, ticket=ticket, success=True, detail="OK")
        except Exception as e:
            RuleExecution.objects.create(rule=rule, ticket=ticket, success=False, detail=str(e))
        # do not recursively re-run to prevent loops; legitimate future events call run_rules again
