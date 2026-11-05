"""Ticket watcher / follower operations."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from common.audit import log_action
from common.permissions import is_system_admin
from tickets.models import Ticket, TicketWatcher

User = get_user_model()


def _is_it_staff(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
             or getattr(user, "is_superuser", False))
    )


def _can_view_ticket(user, ticket):
    """Object-level scope: staff see operational scope; employees see own +
    home-department tickets."""
    from tickets.views import _ticket_visible_qs
    return _ticket_visible_qs(user).filter(pk=ticket.pk).exists()


def list_watchers(ticket, user):
    if not _can_view_ticket(user, ticket):
        return TicketWatcher.objects.none()
    return TicketWatcher.objects.filter(
        ticket=ticket, is_deleted=False).select_related("user", "added_by")


def add_watcher(ticket, validated_data, actor):
    user = validated_data["user"]
    watch_type = validated_data.get("watch_type", "watcher")
    if not _can_view_ticket(actor, ticket):
        raise PermissionDenied("You cannot access this ticket.")
    if not _is_it_staff(actor):
        # Employee may only watch tickets they can already access, and only
        # themselves.
        if user.pk != actor.pk:
            raise PermissionDenied("Employees may only watch their own tickets.")
    if not _is_it_staff(user) and user.pk != actor.pk:
        raise PermissionDenied("Cannot add an arbitrary staff member as watcher.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        watcher, created = TicketWatcher.objects.update_or_create(
            ticket=ticket, user=user,
            defaults={"watch_type": watch_type, "added_by": actor,
                      "is_active": True, "muted_until": None},
        )
        if not created:
            watcher.is_active = True
            watcher.muted_until = None
            watcher.watch_type = watch_type
            watcher.added_by = actor
            watcher.save()
    log_action(actor=actor, action="update", instance=ticket,
               details={"watcher_added": user.pk, "watch_type": watch_type})
    return watcher


def remove_watcher(ticket, target_user, actor):
    if not _can_view_ticket(actor, ticket):
        raise PermissionDenied("You cannot access this ticket.")
    if not _is_it_staff(actor) and target_user.pk != actor.pk:
        raise PermissionDenied("Employees may only remove their own watch.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        try:
            watcher = TicketWatcher.objects.get(ticket=ticket, user=target_user,
                                                is_deleted=False)
        except TicketWatcher.DoesNotExist:
            raise PermissionDenied("User is not watching this ticket.")
        watcher.is_active = False
        watcher.save(update_fields=["is_active", "updated_at"])
    log_action(actor=actor, action="update", instance=ticket,
               details={"watcher_removed": target_user.pk})
    return watcher


def mute_watcher(ticket, user, until, actor):
    if not _can_view_ticket(actor, ticket):
        raise PermissionDenied("You cannot access this ticket.")
    if not _is_it_staff(actor) and user.pk != actor.pk:
        raise PermissionDenied("Employees may only mute their own watch.")
    try:
        watcher = TicketWatcher.objects.get(ticket=ticket, user=user,
                                            is_deleted=False)
    except TicketWatcher.DoesNotExist:
        raise PermissionDenied("User is not watching this ticket.")
    watcher.muted_until = until
    watcher.save(update_fields=["muted_until", "updated_at"])
    log_action(actor=actor, action="update", instance=ticket,
               details={"watcher_muted": user.pk, "until": str(until)})
    return watcher


def unmute_watcher(ticket, user, actor):
    if not _can_view_ticket(actor, ticket):
        raise PermissionDenied("You cannot access this ticket.")
    if not _is_it_staff(actor) and user.pk != actor.pk:
        raise PermissionDenied("Employees may only unmute their own watch.")
    try:
        watcher = TicketWatcher.objects.get(ticket=ticket, user=user,
                                            is_deleted=False)
    except TicketWatcher.DoesNotExist:
        raise PermissionDenied("User is not watching this ticket.")
    watcher.muted_until = None
    watcher.save(update_fields=["muted_until", "updated_at"])
    log_action(actor=actor, action="update", instance=ticket,
               details={"watcher_unmuted": user.pk})
    return watcher


class PermissionDenied(Exception):
    pass
