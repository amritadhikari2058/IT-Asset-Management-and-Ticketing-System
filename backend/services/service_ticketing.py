"""Idempotent, transactional Service Request -> Ticket creation service.

This module is the single place that converts a Service Request into a linked
Ticket. It is used by:

- Service Request creation (when the catalogue item creates a Ticket and does
  not require approval).
- Service Request approval (when the catalogue item creates a Ticket and
  requires approval).
- The manual ``create-ticket`` recovery action.

Nothing else creates Tickets from Service Requests, which keeps the
fulfilment_ticket contract (exactly one Ticket per Request) easy to reason
about.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from rest_framework.exceptions import ValidationError

from services.models import ServiceRequest, ServiceRequestHistory
from tickets.models import Ticket, TicketCategory, TicketHistory, TicketSLA
from common.audit import log_action
from common.models import Notification
from common.notifications import notify_user
from common.notifications import email_enabled_for


# Service Request priority -> Ticket priority. Service Request knows
# "urgent" while Ticket knows "critical"; anything unknown degrades safely to
# "medium".
PRIORITY_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "urgent": "critical",
}

DEFAULT_PRIORITY = "medium"

# Ticket status a Request moves to once its Ticket exists. If the Request is
# already assigned to operational staff it is "in_progress", otherwise it is
# "approved" (the Ticket is the thing to work on next).
def _target_request_status(service_request):
    if service_request.assigned_to_id:
        return "in_progress"
    return "approved"


def _resolve_ticket_category(item):
    """Return the TicketCategory a creates_ticket catalogue item should use.

    Raises ValidationError (readable, no partial state) when the item is
    configured to create Tickets but has no usable category.
    """
    if not item.creates_ticket:
        return None
    category = getattr(item, "ticket_category", None)
    if category is None:
        raise ValidationError(
            {"ticket_category": (
                "Catalogue item '%s' is configured to create Tickets but has "
                "no Ticket category assigned. An IT Manager or System Admin "
                "must select one before requests can be created." % item.name)
            })
    if not category.is_active:
        raise ValidationError(
            {"ticket_category": (
                "Ticket category '%s' is deactivated and cannot be used for "
                "new Tickets." % category.name)
            })
    return category


def _resolve_assignee(service_request):
    """Return the assigned user if they are active IT staff, else None."""
    user = getattr(service_request, "assigned_to", None)
    if user is None or not getattr(user, "pk", None):
        return None
    if not getattr(user, "is_active", True):
        return None
    if getattr(user, "role", "") not in ("system_admin", "it_manager",
                                         "it_support") and not getattr(
                                             user, "is_superuser", False):
        return None
    return user


def _sla_due_at(priority):
    """Compute the SLA due datetime for a Ticket priority, or None."""
    try:
        sla = TicketSLA.objects.get(priority=priority, is_active=True,
                                    is_deleted=False)
    except (TicketSLA.DoesNotExist, TicketSLA.MultipleObjectsReturned):
        return None
    hours = sla.target_resolution_hours or 24
    return timezone.now() + timezone.timedelta(hours=hours)


def _build_description(service_request, item):
    """Build a safe, plain-text Ticket description from Service Request data.

    Never includes internal comments, hidden approval notes, attachment
    content, tokens, raw JSON, HTML from the form schema, or staff-only data.
    Untrusted values are HTML-escaped so they render as inert text.
    """
    lines = [
        "Created automatically from Service Request %s." % service_request.request_number,
        "Service Request: %s" % service_request.request_number,
        "Catalogue item: %s" % escape(item.name),
        "",
    ]
    if service_request.description:
        lines.append("Description:")
        lines.append(escape(service_request.description))
        lines.append("")
    answers = service_request.answers or {}
    if isinstance(answers, dict) and answers:
        lines.append("Answers:")
        for key, value in answers.items():
            rendered = value
            if isinstance(value, (list, tuple)):
                rendered = ", ".join(str(v) for v in value)
            elif isinstance(value, dict):
                rendered = "; ".join("%s=%s" % (k, v) for k, v in value.items())
            lines.append("  %s: %s" % (escape(str(key)), escape(str(rendered))))
        lines.append("")
    lines.append("Reference: Service Request %s" % service_request.request_number)
    return "\n".join(lines)


def _notify_requester(actor, service_request, ticket):
    """In-app + email acknowledgement to the requester (master switch only)."""
    requester = service_request.requester
    if not requester or not getattr(requester, "pk", None):
        return
    title = "Ticket created for your Service Request"
    body = (
        "Ticket #%d has been created for your Service Request %s "
        "(%s)." % (ticket.pk, service_request.request_number,
                   item_name(service_request.catalogue_item))
    )
    _create_notification(actor, requester, title, body, ticket)
    if email_enabled_for(requester, category=None):
        from accounts.email_utils import send_ticket_notification
        send_ticket_notification(
            requester.email, title, body, ticket_id=ticket.pk,
            user=requester, category=None)


def _notify_assignee(actor, service_request, ticket, assignee):
    """In-app + email assignment notice to the assigned support user."""
    if not assignee or not getattr(assignee, "pk", None):
        return
    title = "Ticket assigned from your Service Request"
    body = (
        "Ticket #%d created from Service Request %s has been assigned to you."
        % (ticket.pk, service_request.request_number)
    )
    _create_notification(actor, assignee, title, body, ticket)
    if email_enabled_for(assignee, category="ticket_assignment"):
        from accounts.email_utils import send_ticket_notification
        send_ticket_notification(
            assignee.email, title, body, ticket_id=ticket.pk,
            user=assignee, category="ticket_assignment")


def _create_notification(actor, recipient, title, body, ticket):
    """Mirror tickets.views._notify_user: in-app notification, never noisier.

    Never notify the actor about their own action, never inactive/deleted or
    empty recipients. Body carries requester-visible summary text only.
    Deduplicated via notify_user().
    """
    if recipient is None or getattr(recipient, "pk", None) is None:
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    notify_user(
        recipient, "service_ticket_created", title, body or "",
        entity_type="tickets.Ticket", object_id=str(ticket.pk),
        actor=actor, post_commit=False,
    )


def item_name(item):
    return getattr(item, "name", "") or ""


def ensure_ticket_for_service_request(service_request, actor,
                                      idempotency_key=None):
    """Create (or return the existing) linked Ticket for a Service Request.

    Idempotency: the Service Request row is locked with ``select_for_update``
    so concurrent approval/submit/retry calls serialize on the same Request.
    If ``fulfilment_ticket`` is already set, that Ticket is returned with
    ``created=False`` and no new history/notification/audit is written.

    Returns ``(ticket, created)``.
    """
    actor = actor if getattr(actor, "pk", None) else None

    with transaction.atomic():
        # Lock the Request row so concurrent calls on the same Request
        # serialize and cannot produce two Tickets.
        sr = (ServiceRequest.objects
              .select_for_update()
              .get(pk=service_request.pk))

        item = sr.catalogue_item
        if not getattr(item, "creates_ticket", False):
            return None, False

        # Already linked -> idempotent return, no duplicate work.
        if sr.fulfilment_ticket_id:
            try:
                existing = Ticket.objects.get(pk=sr.fulfilment_ticket_id)
            except Ticket.DoesNotExist:
                existing = None
            if existing is not None:
                return existing, False
            # Stale link (Ticket was deleted): clear and fall through.
            sr.fulfilment_ticket = None
            sr.save(update_fields=["fulfilment_ticket"])

        # Approval requirements must be satisfied.
        if getattr(item, "requires_approval", False):
            if sr.status != "approved":
                raise ValidationError(
                    {"detail": "Service Request %s is not approved (status: "
                               "%s)." % (sr.request_number, sr.status)})

        if sr.status in ("cancelled", "rejected", "fulfilled"):
            raise ValidationError(
                {"detail": "Service Request %s is in a terminal state (%s)."
                               % (sr.request_number, sr.status)})

        # Validate requester / department.
        requester = sr.requester
        if not requester or not getattr(requester, "pk", None):
            raise ValidationError(
                {"detail": "Service Request has no valid requester."})
        department = sr.department or getattr(requester, "home_department",
                                              None)

        # Resolve category (validates presence/active when creates_ticket).
        category = _resolve_ticket_category(item)

        # Map priority safely.
        ticket_priority = PRIORITY_MAP.get(
            getattr(sr, "priority", DEFAULT_PRIORITY), DEFAULT_PRIORITY)

        # Build safe description (no internal/hidden/attachment data).
        description = _build_description(sr, item)

        # Title: bounded to Ticket.title.max_length (255).
        title = "[%s] %s" % (sr.request_number, item_name(item))
        title = title[:255]

        assignee = _resolve_assignee(sr)
        sla_due = _sla_due_at(ticket_priority)

        ticket = Ticket.objects.create(
            title=title,
            description=description,
            category=category,
            priority=ticket_priority,
            status="open",
            requester=requester,
            assignee=assignee,
            department=department,
            sla_due_at=sla_due,
        )

        # Link the Ticket to the Request (one link per Request).
        sr.fulfilment_ticket = ticket
        sr.status = _target_request_status(sr)
        sr.save(update_fields=["fulfilment_ticket", "status", "updated_at"])

        # Histories (transactional, immutable, actor captured).
        ServiceRequestHistory.objects.create(
            request=sr, actor=actor,
            event="ticket_created",
            detail="Ticket #%d created for this service request."
            % ticket.pk)
        TicketHistory.objects.create(
            ticket=ticket, actor=actor, action="created_from_service_request",
            note="Created automatically from Service Request %s."
            % sr.request_number)

        # Audit (safe representation only: IDs + action, no PII/answers).
        log_action(
            actor=actor, action="create", instance=ticket,
            reason="Automatic Ticket creation from Service Request %s"
            % sr.request_number,
            details={
                "service_request_id": str(sr.pk),
                "service_request_number": sr.request_number,
                "catalogue_item_id": str(item.pk),
            })

        # Notifications: in-app now, email after commit so a rolled-back
        # transaction never sends mail for a non-existent Ticket.
        transaction.on_commit(lambda: _notify_requester(
            actor, sr, ticket))
        transaction.on_commit(lambda: _notify_assignee(
            actor, sr, ticket, assignee))

        return ticket, True
