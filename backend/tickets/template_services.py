"""Canned responses and ticket templates."""
import re
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from common.audit import log_action
from tickets.models import (
    CannedResponse, TicketTemplate, Ticket, TicketNote, TicketHistory,
)

User = get_user_model()

# Strict allowlist of renderable variables. No attribute traversal, no calls.
_ALLOWED_VARIABLES = {
    "ticket_number", "requester_name", "requester_email", "assignee_name",
    "category_name", "priority", "status", "department_name", "current_date",
}
_VAR_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _is_it_staff(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
             or getattr(user, "is_superuser", False))
    )


def _can_manage_shared(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager")
             or getattr(user, "is_superuser", False))
    )


def _render_variables(text, context):
    """Safe plain-text substitution with a strict allowlist.

    Unknown variables render as empty. No eval/exec/template engine access.
    Output length is bounded.
    """
    def _replace(match):
        name = match.group(1)
        if name not in _ALLOWED_VARIABLES:
            return ""
        return str(context.get(name, "") or "")

    out = _VAR_RE.sub(_replace, text)
    return out[:4000]


def build_context(ticket, requester=None, assignee=None):
    requester = requester or ticket.requester
    assignee = assignee or ticket.assignee
    category = ticket.category
    department = ticket.department
    return {
        "ticket_number": str(ticket.pk),
        "requester_name": getattr(requester, "get_full_name", lambda: "")()
        or getattr(requester, "employee_id", "") or "",
        "requester_email": getattr(requester, "email", "") or "",
        "assignee_name": getattr(assignee, "get_full_name", lambda: "")()
        or getattr(assignee, "employee_id", "") or "",
        "category_name": getattr(category, "name", "") or "",
        "priority": ticket.get_priority_display() if hasattr(ticket, "get_priority_display") else ticket.priority,
        "status": ticket.get_status_display() if hasattr(ticket, "get_status_display") else ticket.status,
        "department_name": getattr(department, "name", "") or "",
        "current_date": timezone.now().strftime("%Y-%m-%d"),
    }

# ---------------------------------------------------------------------------
# Canned responses
# ---------------------------------------------------------------------------

def list_canned_responses(user):
    qs = CannedResponse.objects.filter(is_deleted=False, is_active=True)
    if not _is_it_staff(user):
        return qs.none()
    return qs


def create_canned_response(validated_data, actor):
    is_shared = validated_data.get("is_shared", False)
    if is_shared and not _can_manage_shared(actor):
        raise PermissionDenied("Only IT Manager / System Admin manage shared responses.")
    if not is_shared and not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can create canned responses.")
    validated_data["owner"] = actor
    validated_data["created_by"] = actor
    obj = CannedResponse.objects.create(**validated_data)
    log_action(actor=actor, action="create", instance=obj)
    return obj


def update_canned_response(obj, validated_data, actor):
    is_shared = validated_data.get("is_shared", obj.is_shared)
    if is_shared and not _can_manage_shared(actor):
        raise PermissionDenied("Only IT Manager / System Admin manage shared responses.")
    if obj.owner_id != actor.pk and not _can_manage_shared(actor):
        raise PermissionDenied("You do not own this response.")
    for field, value in validated_data.items():
        setattr(obj, field, value)
    obj.full_clean()
    obj.save()
    log_action(actor=actor, action="update", instance=obj)
    return obj


def delete_canned_response(obj, actor):
    if obj.owner_id != actor.pk and not _can_manage_shared(actor):
        raise PermissionDenied("You do not own this response.")
    obj.delete()  # soft delete
    log_action(actor=actor, action="delete", instance=obj)


def apply_canned_response(ticket, validated_data, actor):
    """Apply a canned response as a ticket note (existing note logic reused)."""
    response_id = validated_data["canned_response_id"]
    visibility = validated_data.get("visibility", "internal_note")
    additional_text = validated_data.get("additional_text", "") or ""
    expected_version = validated_data.get("expected_ticket_version")

    try:
        response = CannedResponse.objects.get(pk=response_id, is_deleted=False)
    except CannedResponse.DoesNotExist:
        raise PermissionDenied("Canned response not found or inactive.")

    if response.is_shared:
        if not _is_it_staff(actor):
            raise PermissionDenied("Shared responses are IT-staff only.")
    else:
        if response.owner_id != actor.pk and not _can_manage_shared(actor):
            raise PermissionDenied("You do not own this canned response.")
    if not response.is_active:
        raise PermissionDenied("This canned response is inactive.")

    if visibility == "public_reply" and response.visibility not in ("public_reply", "both"):
        raise ValidationError("This response cannot be used as a public reply.")
    if visibility == "internal_note" and response.visibility not in ("internal_note", "both"):
        raise ValidationError("This response is not permitted as an internal note.")

    if expected_version is not None and ticket.version != expected_version:
        raise ConflictError("Ticket was modified concurrently. Refresh and retry.")

    context = build_context(ticket)
    body = _render_variables(response.body, context)
    if additional_text:
        body = (body + "\n\n" + additional_text)[:4000]

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if expected_version is not None and ticket.version != expected_version:
            raise ConflictError("Ticket was modified concurrently. Refresh and retry.")
        is_internal = visibility != "public_reply"
        note = TicketNote.objects.create(
            ticket=ticket, author=actor, body=body, is_internal=is_internal)
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["version", "updated_at"])
        _write_history(ticket, actor, "canned_response_applied",
                       new={"canned_response": response.pk, "visibility": visibility})
        response.usage_count = (response.usage_count or 0) + 1
        response.last_used_at = timezone.now()
        response.save(update_fields=["usage_count", "last_used_at", "updated_at"])
        log_action(actor=actor, action="note", instance=ticket,
                   details={"canned_response": response.pk})
    return note


class ConflictError(Exception):
    pass


class PermissionDenied(Exception):
    pass


def _write_history(ticket, actor, action, old=None, new=None, note=""):
    TicketHistory.objects.create(ticket=ticket, actor=actor, action=action,
                                 old_values=old or {}, new_values=new or {},
                                 note=note or "")


# ---------------------------------------------------------------------------
# Ticket templates
# ---------------------------------------------------------------------------

def list_templates(user):
    qs = TicketTemplate.objects.filter(is_deleted=False, is_active=True)
    if not _is_it_staff(user):
        return qs.none()
    return qs


def create_template(validated_data, actor):
    is_shared = validated_data.get("is_shared", False)
    if is_shared and not _can_manage_shared(actor):
        raise PermissionDenied("Only IT Manager / System Admin manage shared templates.")
    if not is_shared and not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can create templates.")
    validated_data["owner"] = actor
    validated_data["created_by"] = actor
    obj = TicketTemplate.objects.create(**validated_data)
    log_action(actor=actor, action="create", instance=obj)
    return obj


def update_template(obj, validated_data, actor):
    is_shared = validated_data.get("is_shared", obj.is_shared)
    if is_shared and not _can_manage_shared(actor):
        raise PermissionDenied("Only IT Manager / System Admin manage shared templates.")
    if obj.owner_id != actor.pk and not _can_manage_shared(actor):
        raise PermissionDenied("You do not own this template.")
    for field, value in validated_data.items():
        if field in ("owner", "created_by"):
            continue
        setattr(obj, field, value)
    obj.full_clean()
    obj.save()
    log_action(actor=actor, action="update", instance=obj)
    return obj


def delete_template(obj, actor):
    if obj.owner_id != actor.pk and not _can_manage_shared(actor):
        raise PermissionDenied("You do not own this template.")
    obj.delete()  # soft delete
    log_action(actor=actor, action="delete", instance=obj)


def apply_template_to_ticket_data(template, actor, overrides):
    """Build ticket creation field defaults from a template, server-side.

    Protected values (assignee, status, queue, category) may be prefilled but
    are re-validated by the caller serializer; the client cannot force
    staff-only values.
    """
    data = {
        "title": template.title_template,
        "description": template.description_template,
        "category": template.category_id,
        "queue": template.queue_id,
        "priority": template.priority or "",
        "status": template.default_status or "open",
    }
    if template.default_assignee_id and _is_it_staff(actor):
        data["assignee"] = template.default_assignee_id
    context = {
        "ticket_number": "", "requester_name": "", "requester_email": "",
        "assignee_name": "", "category_name": getattr(template.category, "name", "") or "",
        "priority": template.priority or "", "status": template.default_status or "open",
        "department_name": "", "current_date": timezone.now().strftime("%Y-%m-%d"),
    }
    data["title"] = _render_variables(data["title"], context)
    data["description"] = _render_variables(data["description"], context)
    return data

