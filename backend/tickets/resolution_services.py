"""Waiting-for-requester, SLA pause, resolve, close and reopen workflow."""
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from common.audit import log_action
from common.notifications import (
    TICKET_STATUS_CATEGORY, TICKET_REPLY_CATEGORY, email_enabled_for,
)
from tickets.models import (
    Ticket, TicketHistory, TicketNote, TicketSlaPause, TicketResolutionCode,
    TicketSatisfactionSurvey,
)
from tickets.queue_services import _notify_user, _notify_watchers, _write_history


def _is_it_staff(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
             or getattr(user, "is_superuser", False))
    )


def _sla_pause_allowed(ticket):
    from tickets.models import TicketSLA
    try:
        TicketSLA.objects.get(priority=ticket.priority, is_active=True,
                              is_deleted=False)
    except TicketSLA.DoesNotExist:
        return False
    return True


def _active_pause(ticket):
    return TicketSlaPause.objects.filter(
        ticket=ticket, ended_at__isnull=True, is_deleted=False).first()


class ConflictError(Exception):
    pass


class PermissionDenied(Exception):
    pass


class ValidationError(Exception):
    pass

def request_information(ticket, validated_data, actor):
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can request information.")
    message = (validated_data.get("message") or "").strip()
    if not message:
        raise ValidationError("Message is required.")
    expected_version = validated_data.get("expected_ticket_version")

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if expected_version is not None and ticket.version != expected_version:
            raise ConflictError("Ticket was modified concurrently. Refresh and retry.")
        if ticket.status == "merged":
            raise ValidationError("Cannot request information on a merged ticket.")
        old_status = ticket.status
        old = {"status": ticket.status}
        ticket.status = "waiting_requester"
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["status", "version", "updated_at"])

        note = TicketNote.objects.create(
            ticket=ticket, author=actor, body=message, is_internal=False)

        pause = None
        if _sla_pause_allowed(ticket):
            pause = TicketSlaPause.objects.create(
                ticket=ticket, reason="waiting_requester",
                started_by=actor, pause_type="waiting_requester",
                started_at=timezone.now())

        _write_history(ticket, actor, "request_information",
                       old=old, new={"status": "waiting_requester"},
                       note=message)
        log_action(actor=actor, action="update", instance=ticket,
                   details={"from": old_status, "to": "waiting_requester"})

        _notify_user(ticket.requester, actor,
                     f"Ticket #{ticket.pk} needs your input",
                     f"{actor} requested more information on ticket #{ticket.pk}.", ticket)
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} waiting for requester",
                         f"Ticket #{ticket.pk} is waiting for the requester.", actor)

    return ticket, note, pause


def requester_replied(ticket, actor, note_body):
    if not _can_view_or_requester(ticket, actor):
        raise PermissionDenied("You cannot access this ticket.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status != "waiting_requester":
            return ticket
        old = {"status": ticket.status}
        ticket.status = "in_progress"
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["status", "version", "updated_at"])
        TicketNote.objects.create(
            ticket=ticket, author=actor, body=note_body, is_internal=False)
        pause = _active_pause(ticket)
        if pause:
            pause.ended_at = timezone.now()
            pause.ended_by = actor
            pause.save(update_fields=["ended_at", "ended_by", "updated_at"])
        _write_history(ticket, actor, "requester_replied",
                       old=old, new={"status": "in_progress"})
        log_action(actor=actor, action="update", instance=ticket,
                   details={"from": "waiting_requester", "to": "in_progress"})
        _notify_user(ticket.assignee, actor,
                     f"Ticket #{ticket.pk} requester replied",
                     f"The requester replied on ticket #{ticket.pk}.", ticket)
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} requester replied",
                         f"The requester replied on ticket #{ticket.pk}.", actor)
    return ticket


def _can_view_or_requester(ticket, user):
    from tickets.views import _ticket_visible_qs
    return _ticket_visible_qs(user).filter(pk=ticket.pk).exists() or ticket.requester_id == user.pk


def resolve_ticket(ticket, validated_data, actor):
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can resolve tickets.")
    if ticket.status == "merged":
        raise ValidationError("Cannot resolve a merged ticket.")
    if ticket.status == "cancelled":
        raise ValidationError("Cannot resolve a cancelled ticket.")

    resolution_code_id = validated_data.get("resolution_code")
    resolution_summary = (validated_data.get("resolution_summary") or "").strip()
    requester_visible_note = (validated_data.get("requester_visible_note") or "").strip()
    expected_version = validated_data.get("expected_ticket_version")
    kb_article_ids = validated_data.get("knowledge_base_article_ids") or []

    try:
        code = TicketResolutionCode.objects.get(
            pk=resolution_code_id, is_deleted=False, is_active=True)
    except TicketResolutionCode.DoesNotExist:
        raise ValidationError("Invalid or inactive resolution code.")

    if code.requires_summary and not resolution_summary:
        raise ValidationError("Resolution summary is required for this code.")

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if expected_version is not None and ticket.version != expected_version:
            raise ConflictError("Ticket was modified concurrently. Refresh and retry.")
        if ticket.status in ("resolved", "closed", "merged", "cancelled"):
            return ticket
        if not options_manager_override(actor, validated_data):
            open_children = ticket.child_tickets.filter(
                is_deleted=False, status__in={"open", "in_progress",
                                              "waiting_requester",
                                              "waiting_third_party"}).count()
            if open_children:
                raise ValidationError(
                    "Open child tickets block resolution. Manager override required.")
        old = {"status": ticket.status, "resolution_code": ticket.resolution_code_id,
               "resolved_at": str(ticket.resolved_at)}
        ticket.status = "resolved"
        ticket.resolution_code = code
        ticket.resolution_summary = resolution_summary
        ticket.resolved_by = actor
        ticket.resolved_at = timezone.now()
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["status", "resolution_code",
                                   "resolution_summary", "resolved_by",
                                   "resolved_at", "version", "updated_at"])

        pause = _active_pause(ticket)
        if pause:
            pause.ended_at = timezone.now()
            pause.ended_by = actor
            pause.save(update_fields=["ended_at", "ended_by", "updated_at"])

        if requester_visible_note:
            TicketNote.objects.create(
                ticket=ticket, author=actor, body=requester_visible_note,
                is_internal=False)

        _write_history(ticket, actor, "resolved",
                       old=old, new={"status": "resolved",
                                     "resolution_code": code.pk,
                                     "resolved_at": str(ticket.resolved_at)})
        log_action(actor=actor, action="resolve", instance=ticket,
                   details={"code": code.pk, "summary": resolution_summary[:200]})

        _notify_user(ticket.requester, actor,
                     f"Ticket #{ticket.pk} resolved",
                     f"Ticket #{ticket.pk} has been resolved: {code.name}.", ticket)
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} resolved",
                         f"Ticket #{ticket.pk} resolved with code '{code.name}'.", actor)

        _offer_satisfaction_survey(ticket, ticket.requester)

    return ticket


def options_manager_override(actor, validated_data):
    return bool(_is_it_staff(actor) and validated_data.get("manager_override"))


def close_ticket(ticket, actor, reason=""):
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can close tickets.")
    if ticket.status != "resolved":
        raise ValidationError("Only resolved tickets can be closed.")
    if ticket.status in ("merged", "cancelled"):
        raise ValidationError("Cannot close a merged or cancelled ticket.")
    if not options_manager_override(actor, {}):
        open_children = ticket.child_tickets.filter(
            is_deleted=False, status__in={"open", "in_progress",
                                          "waiting_requester",
                                          "waiting_third_party"}).count()
        if open_children:
            raise ValidationError(
                "Open child tickets block closure. Manager override required.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status != "resolved":
            raise ValidationError("Ticket is no longer resolved.")
        old = {"status": ticket.status, "closed_at": str(ticket.closed_at)}
        ticket.status = "closed"
        ticket.closed_at = timezone.now()
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["status", "closed_at", "version", "updated_at"])
        _write_history(ticket, actor, "closed",
                       old=old, new={"status": "closed",
                                     "closed_at": str(ticket.closed_at)},
                       note=reason)
        log_action(actor=actor, action="close", instance=ticket,
                   details={"reason": reason[:200]})
        _notify_user(ticket.requester, actor,
                     f"Ticket #{ticket.pk} closed",
                     f"Ticket #{ticket.pk} has been closed.", ticket)
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} closed",
                         f"Ticket #{ticket.pk} has been closed.", actor)
    return ticket


def reopen_ticket(ticket, validated_data, actor):
    reason = (validated_data.get("reason") or "").strip()
    if not reason:
        raise ValidationError("Reason is required to reopen.")
    expected_version = validated_data.get("expected_ticket_version")
    is_requester = getattr(actor, "pk", None) == ticket.requester_id
    if not _is_it_staff(actor) and not is_requester:
        raise PermissionDenied("Only the requester or IT staff can reopen.")
    if ticket.status in ("merged", "cancelled"):
        raise ValidationError("Cannot reopen a merged or cancelled ticket.")

    window_days = int(getattr(settings, "TICKET_REOPEN_WINDOW_DAYS", 14) or 14)
    now = timezone.now()
    within_window = bool(ticket.closed_at and
                         (now - ticket.closed_at) <= timedelta(days=window_days))
    if not _is_it_staff(actor) and not within_window:
        raise ValidationError("Reopen window has expired for this ticket.")
    if not _is_it_staff(actor) and ticket.resolution_code and \
            ticket.resolution_code.code == "duplicate":
        raise ValidationError("Duplicate-resolution tickets cannot be reopened.")

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if expected_version is not None and ticket.version != expected_version:
            raise ConflictError("Ticket was modified concurrently. Refresh and retry.")
        old = {"status": ticket.status, "reopen_count": ticket.reopen_count,
               "resolved_at": str(ticket.resolved_at)}
        ticket.status = "in_progress"
        ticket.reopen_count = (ticket.reopen_count or 0) + 1
        ticket.reopened_at = now
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.resolution_code = None
        ticket.resolution_summary = ""
        ticket.resolved_by = None
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["status", "reopen_count", "reopened_at",
                                   "resolved_at", "closed_at", "resolution_code",
                                   "resolution_summary", "resolved_by",
                                   "version", "updated_at"])
        _write_history(ticket, actor, "reopened",
                       old=old, new={"status": "in_progress",
                                     "reopen_count": ticket.reopen_count},
                       note=reason)
        log_action(actor=actor, action="reopen", instance=ticket,
                   details={"reason": reason[:200]})
        _notify_user(ticket.assignee, actor,
                     f"Ticket #{ticket.pk} reopened",
                     f"Ticket #{ticket.pk} was reopened: {reason}", ticket)
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} reopened",
                         f"Ticket #{ticket.pk} was reopened.", actor)
    return ticket


def _offer_satisfaction_survey(ticket, requester):
    from django.utils import timezone as _tz
    expiry_days = int(getattr(settings, "TICKET_SURVEY_EXPIRY_DAYS", 30) or 30)
    TicketSatisfactionSurvey.objects.update_or_create(
        ticket=ticket, requester=requester,
        defaults={"status": "pending",
                  "expires_at": _tz.now() + timedelta(days=expiry_days),
                  "submitted_at": None, "rating": None,
                  "resolution_helpful": None, "response_time_satisfied": None,
                  "communication_satisfied": None, "comments": ""})

