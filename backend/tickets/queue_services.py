"""Queue, membership, and assignment operations for tickets.

All mutations are transactional and use ``select_for_update`` with stable lock
ordering so concurrent agents cannot double-claim or double-assign.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from common.audit import log_action
from common.models import Notification
from common.permissions import is_system_admin
from tickets.models import (
    Ticket, TicketQueue, TicketQueueMembership, TicketWatcher,
)

User = get_user_model()

OPEN_STATUSES = {"open", "in_progress", "waiting_requester", "waiting_third_party"}


def _staff_qs():
    return User.objects.filter(is_active=True, is_deleted=False)


def _is_it_staff(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
             or getattr(user, "is_superuser", False))
    )


def _can_manage_queues(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager")
             or getattr(user, "is_superuser", False))
    )


def _queue_manager_or_admin(user, queue):
    """True if user is system_admin/it_manager, or the explicit queue manager."""
    if _can_manage_queues(user):
        return True
    return bool(queue.manager_id == user.pk)


def _eligible_members(queue):
    """Active, non-observer, claim-eligible memberships on an active queue."""
    return (
        TicketQueueMembership.objects.filter(
            queue=queue, is_active=True, is_deleted=False,
            can_claim=True,
        )
        .exclude(role="observer")
        .select_related("user")
    )

# ---------------------------------------------------------------------------
# Queue administration
# ---------------------------------------------------------------------------

def list_queues(user):
    """Queues visible to the user (IT staff: usable queues; employees: none)."""
    qs = TicketQueue.objects.filter(is_deleted=False)
    if not _is_it_staff(user):
        return qs.none()
    qs = qs.filter(is_active=True)
    return qs


def create_queue(validated_data, actor):
    if not _can_manage_queues(actor):
        raise PermissionDenied("Only IT Manager / System Admin can create queues.")
    queue = TicketQueue.objects.create(**validated_data, created_by=actor)
    log_action(actor=actor, action="create", instance=queue)
    return queue


def update_queue(queue, validated_data, actor):
    if not _can_manage_queues(actor):
        raise PermissionDenied("Only IT Manager / System Admin can update queues.")
    for field, value in validated_data.items():
        setattr(queue, field, value)
    queue.full_clean()
    queue.save()
    log_action(actor=actor, action="update", instance=queue)
    return queue


def deactivate_queue(queue, actor):
    if not _can_manage_queues(actor):
        raise PermissionDenied("Only IT Manager / System Admin can deactivate queues.")
    queue.is_active = False
    queue.save(update_fields=["is_active", "updated_at"])
    log_action(actor=actor, action="deactivate", instance=queue,
               reason="Queue deactivated")


def delete_queue(queue, actor):
    if not _can_manage_queues(actor):
        raise PermissionDenied("Only IT Manager / System Admin can delete queues.")
    if queue.tickets.filter(is_deleted=False).exists():
        raise ValidationError(
            "Queue deletion blocked: active tickets reference this queue. "
            "Deactivate instead.")
    queue.delete()  # soft delete via SoftDeleteModel
    log_action(actor=actor, action="delete", instance=queue)


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

def list_memberships(queue, user):
    if not _is_it_staff(user):
        return TicketQueueMembership.objects.none()
    return TicketQueueMembership.objects.filter(
        queue=queue, is_deleted=False).select_related("user")


def add_membership(queue, validated_data, actor):
    if not _queue_manager_or_admin(actor, queue):
        raise PermissionDenied(
            "Only queue manager, IT Manager, or System Admin adds members.")
    user = validated_data["user"]
    if not _staff_qs().filter(pk=user.pk).exists():
        raise ValidationError("Only active IT staff can be queue members.")
    if TicketQueueMembership.objects.filter(
            queue=queue, user=user, is_active=True, is_deleted=False).exists():
        raise ValidationError("User already has an active membership on this queue.")
    role = validated_data.get("role", "agent")
    if role == "observer" and (validated_data.get("can_claim")
                               or validated_data.get("can_assign_others")):
        raise ValidationError("Observer cannot claim or assign others.")
    membership = TicketQueueMembership.objects.create(
        queue=queue, user=user, role=role, created_by=actor, **{
            k: validated_data[k] for k in ("can_claim", "can_assign_others",
                                           "can_view_all") if k in validated_data
        })
    log_action(actor=actor, action="update", instance=queue,
               details={"membership": membership.pk, "user": user.pk, "role": role})
    return membership


def update_membership(membership, validated_data, actor):
    if not _queue_manager_or_admin(actor, membership.queue):
        raise PermissionDenied(
            "Only queue manager, IT Manager, or System Admin updates memberships.")
    role = validated_data.get("role", membership.role)
    if role == "observer" and (validated_data.get("can_claim", membership.can_claim)
                               or validated_data.get(
                                   "can_assign_others", membership.can_assign_others)):
        raise ValidationError("Observer cannot claim or assign others.")
    for field, value in validated_data.items():
        setattr(membership, field, value)
    membership.full_clean()
    membership.save()
    log_action(actor=actor, action="update", instance=membership.queue,
               details={"membership": membership.pk})
    return membership


def remove_membership(membership, actor):
    if not _queue_manager_or_admin(actor, membership.queue):
        raise PermissionDenied(
            "Only queue manager, IT Manager, or System Admin removes members.")
    queue = membership.queue
    membership.is_active = False
    membership.save(update_fields=["is_active", "updated_at"])
    log_action(actor=actor, action="update", instance=queue,
               details={"membership_removed": membership.pk,
                        "user": membership.user_id})


# ---------------------------------------------------------------------------
# Claim / unclaim / reassign / move-queue / auto-assign
# ---------------------------------------------------------------------------

def claim_ticket(ticket, actor):
    """Claim an unassigned ticket for the actor."""
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can claim tickets.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.assignee_id is not None:
            raise ValidationError("Ticket is already assigned.")
        if not ticket.queue_id:
            raise ValidationError("Ticket is not routed to a queue.")
        queue = ticket.queue
        if not queue.is_active:
            raise ValidationError("Cannot claim on an inactive queue.")
        membership = (
            TicketQueueMembership.objects.filter(
                queue=queue, user=actor, is_active=True, is_deleted=False,
                can_claim=True,
            ).select_for_update().first()
        )
        if not membership:
            raise PermissionDenied(
                "You are not an active claim-eligible member of this queue.")
        if not queue.allow_self_claim:
            raise ValidationError("This queue does not permit self-claim.")
        old = {"assignee": ticket.assignee_id, "status": ticket.status}
        ticket.assignee = actor
        if ticket.status == "open":
            ticket.status = "in_progress"
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=[
            "assignee", "status", "version", "updated_at"])
        TicketWatcher.objects.get_or_create(
            ticket=ticket, user=actor, defaults={
                "watch_type": "watcher", "added_by": actor,
                "is_active": True})
        _write_history(ticket, actor, "claimed",
                       old=old, new={"assignee": actor.pk, "status": ticket.status})
        log_action(actor=actor, action="assignment", instance=ticket,
                   details={"from": old["assignee"], "to": actor.pk})
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} claimed",
                         f"{actor} claimed ticket #{ticket.pk}: {ticket.title}")
    return ticket


def unclaim_ticket(ticket, actor, reason):
    """Release an assigned ticket back to its queue."""
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can unclaim tickets.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.assignee_id != actor.pk and not _can_manage_queues(actor):
            raise PermissionDenied("Only the assignee or a manager can unclaim.")
        if ticket.assignee_id is None:
            raise ValidationError("Ticket is not assigned.")
        old = {"assignee": ticket.assignee_id, "status": ticket.status}
        ticket.assignee = None
        if ticket.status in ("in_progress",):
            ticket.status = "open"
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["assignee", "status", "version", "updated_at"])
        _write_history(ticket, actor, "unclaimed",
                       old=old, new={"assignee": None, "status": ticket.status},
                       note=reason)
        log_action(actor=actor, action="assignment", instance=ticket,
                   details={"from": old["assignee"], "to": None, "reason": reason})
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} unclaimed",
                         f"{actor} unclaimed ticket #{ticket.pk}: {ticket.title}")
    return ticket


def reassign_ticket(ticket, target_user, actor, reason):
    """Reassign a ticket to another IT staff member."""
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can reassign tickets.")
    if not _staff_qs().filter(pk=target_user.pk).exists():
        raise ValidationError("Target must be an active IT staff member.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.assignee_id == target_user.pk:
            raise ValidationError("Ticket is already assigned to this user.")
        old_assignee = ticket.assignee
        old = {"assignee": ticket.assignee_id, "status": ticket.status}
        ticket.assignee = target_user
        if ticket.status == "open":
            ticket.status = "in_progress"
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["assignee", "status", "version", "updated_at"])
        _write_history(ticket, actor, "reassigned",
                       old=old, new={"assignee": target_user.pk, "status": ticket.status},
                       note=reason)
        log_action(actor=actor, action="assignment", instance=ticket,
                   details={"from": old["assignee"], "to": target_user.pk,
                            "reason": reason})
        _notify_user(old_assignee, actor, f"Ticket #{ticket.pk} reassigned",
                     f"Ticket #{ticket.pk} '{ticket.title}' was reassigned away from you.", ticket)
        _notify_user(target_user, actor, f"Ticket #{ticket.pk} assigned to you",
                     f"{actor} assigned ticket #{ticket.pk}: {ticket.title}", ticket)
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} reassigned",
                         f"Ticket #{ticket.pk} reassigned to {target_user}.", actor)
    return ticket


def move_queue(ticket, target_queue, actor, reason):
    """Move a ticket between queues (requires reason)."""
    if not _is_it_staff(actor):
        raise PermissionDenied("Only IT staff can move tickets between queues.")
    if not target_queue.is_active:
        raise ValidationError("Cannot move a ticket to an inactive queue.")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        old_queue = ticket.queue
        old = {"queue": old_queue_id(old_queue), "status": ticket.status}
        ticket.queue = target_queue
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["queue", "version", "updated_at"])
        _write_history(ticket, actor, "queue_move",
                       old=old, new={"queue": target_queue.pk, "status": ticket.status},
                       note=reason)
        log_action(actor=actor, action="update", instance=ticket,
                   details={"from_queue": old_queue_id(old_queue),
                            "to_queue": target_queue.pk, "reason": reason})
        _notify_watchers(ticket, actor, f"Ticket #{ticket.pk} moved queue",
                         f"Ticket #{ticket.pk} moved to queue '{target_queue.name}'.", actor)
    return ticket


def auto_assign_queue(queue, actor):
    """Auto-assign unassigned tickets in a queue using its strategy."""
    if not _queue_manager_or_admin(actor, queue):
        raise PermissionDenied(
            "Only queue manager, IT Manager, or System Admin can auto-assign.")
    strategy = queue.assignment_strategy
    if strategy not in ("manual", "least_open_tickets", "round_robin"):
        raise ValidationError(
            f"Assignment strategy '{strategy}' is not supported for auto-assign.")
    members = list(_eligible_members(queue))
    if not members:
        raise ValidationError("No eligible claim-eligible members on this queue.")
    tickets = (
        Ticket.objects.filter(queue=queue, assignee_id__isnull=True,
                              is_deleted=False, status__in=OPEN_STATUSES)
        .select_for_update()
        .order_by("pk")
    )
    assigned = []
    for ticket in tickets:
        member = _select_member(queue, strategy, members, ticket)
        if not member:
            break
        ticket.assignee = member.user
        if ticket.status == "open":
            ticket.status = "in_progress"
        ticket.version = (ticket.version or 1) + 1
        ticket.save(update_fields=["assignee", "status", "version", "updated_at"])
        TicketWatcher.objects.get_or_create(
            ticket=ticket, user=member.user, defaults={
                "watch_type": "watcher", "added_by": actor,
                "is_active": True})
        _write_history(ticket, actor, "auto_assigned",
                       new={"assignee": member.user.pk, "status": ticket.status})
        log_action(actor=actor, action="assignment", instance=ticket,
                   details={"strategy": strategy, "to": member.user.pk})
        assigned.append(ticket.pk)
    return assigned


def _select_member(queue, strategy, members, ticket):
    if strategy == "least_open_tickets":
        return _least_open_member(members)
    if strategy == "round_robin":
        return _round_robin_member(queue, members)
    return members[0]


def _least_open_member(members):
    user_ids = [m.user_id for m in members]
    open_counts = (
        Ticket.objects.filter(assignee_id__in=user_ids, is_deleted=False,
                              status__in=OPEN_STATUSES)
        .values("assignee_id").annotate(c=Count("id"))
    )
    counts = {row["assignee_id"]: row["c"] for row in open_counts}
    best = None
    best_count = None
    for m in members:
        c = counts.get(m.user_id, 0)
        if best is None or c < best_count or (c == best_count and m.user_id < best.user_id):
            best = m
            best_count = c
    return best


def _round_robin_member(queue, members):
    """Deterministic round-robin: pick member after the last assigned agent."""
    last = (
        Ticket.objects.filter(queue=queue, assignee_id__isnull=False,
                              is_deleted=False)
        .order_by("-updated_at").first()
    )
    last_id = last.assignee_id if last else None
    ordered = sorted(members, key=lambda m: m.user_id)
    if last_id:
        for i, m in enumerate(ordered):
            if m.user_id == last_id:
                return ordered[(i + 1) % len(ordered)]
    return ordered[0]


def old_queue_id(queue):
    return queue.pk if queue else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_history(ticket, actor, action, old=None, new=None, note=""):
    from tickets.models import TicketHistory
    TicketHistory.objects.create(ticket=ticket, actor=actor, action=action,
                                 old_values=old or {}, new_values=new or {},
                                 note=note or "")


def _notify_user(recipient, actor, title, body, ticket):
    from common.notifications import notify_user as _central_notify_user

    return _central_notify_user(
        recipient,
        category="ticket_event",
        title=title,
        message=body,
        entity_type="tickets.Ticket",
        object_id=str(getattr(ticket, "pk", "") or ""),
        actor=actor,
        dedupe=True,
        post_commit=True,
    )


def _notify_watchers(ticket, actor, title, body, exclude=None):
    from common.notifications import notify_user as _central_notify_user

    exclude_pk = getattr(exclude, "pk", None) if exclude else None
    for w in ticket.watchers.filter(is_active=True, is_deleted=False):
        if w.user_id == getattr(actor, "pk", None) or w.user_id == exclude_pk:
            continue
        if w.is_muted():
            continue
        _central_notify_user(
            w.user,
            category="ticket_event",
            title=title,
            message=body,
            entity_type="tickets.Ticket",
            object_id=str(getattr(ticket, "pk", "") or ""),
            actor=actor,
            dedupe=True,
            post_commit=True,
        )


class PermissionDenied(Exception):
    pass

