"""Operations dashboard, queue metrics, and agent workload metrics.

All figures calculated from real ticket data via database aggregation.
No fabricated trends.
"""
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q
from django.utils import timezone
from datetime import timedelta

from tickets.models import Ticket, TicketQueue, TicketSatisfactionSurvey
from tickets.queue_services import _is_it_staff

User = get_user_model()

OPEN_STATUSES = {"open", "in_progress", "waiting_requester", "waiting_third_party"}
TERMINAL_STATUSES = {"resolved", "closed", "archived", "cancelled", "merged"}


def _base_ticket_qs(user):
    from tickets.views import _ticket_visible_qs
    return _ticket_visible_qs(user).filter(is_deleted=False)


def _is_it_staff_local(user):
    return _is_it_staff(user)


class PermissionDenied(Exception):
    pass


class ValidationError(Exception):
    pass

def operations_dashboard(filters, user):
    if not _is_it_staff(user):
        raise PermissionDenied("Metrics are IT-staff only.")
    qs = _base_ticket_qs(user)
    qs = _apply_filters(qs, filters)
    now = timezone.now()
    total = qs.count()
    unassigned = qs.filter(assignee_id__isnull=True).count()
    assigned = qs.filter(assignee_id__isnull=False).count()
    in_progress = qs.filter(status="in_progress").count()
    waiting_req = qs.filter(status="waiting_requester").count()
    waiting_third = qs.filter(status="waiting_third_party").count()
    overdue = qs.filter(status__in=OPEN_STATUSES,
                        sla_due_at__lt=now).count()
    breached = qs.filter(sla_breached=True).count()
    urgent = qs.filter(priority="critical", status__in=OPEN_STATUSES).count()
    oldest = qs.order_by("created_at").first()
    oldest_age = (now - oldest.created_at).days if oldest else None
    resolved_period = qs.filter(
        status="resolved", resolved_at__isnull=False).count()
    reopened_period = qs.filter(status="reopened").count()
    return {
        "total_active": total,
        "unassigned": unassigned,
        "assigned": assigned,
        "in_progress": in_progress,
        "waiting_requester": waiting_req,
        "waiting_third_party": waiting_third,
        "overdue": overdue,
        "sla_breached": breached,
        "urgent": urgent,
        "oldest_ticket_age_days": oldest_age,
        "resolved_in_period": resolved_period,
        "reopened_in_period": reopened_period,
    }


def queue_metrics(queue_id, filters, user):
    if not _is_it_staff(user):
        raise PermissionDenied("Queue metrics are IT-staff only.")
    try:
        queue = TicketQueue.objects.get(pk=queue_id, is_deleted=False)
    except TicketQueue.DoesNotExist:
        raise ValidationError("Queue not found.")
    qs = Ticket.objects.filter(queue=queue, is_deleted=False)
    qs = _apply_filters(qs, filters)
    now = timezone.now()
    members = queue.memberships.filter(is_active=True, is_deleted=False)
    member_workload = []
    for m in members.select_related("user"):
        member_workload.append({
            "user": m.user.pk,
            "user_name": getattr(m.user, "employee_id", str(m.user.pk)),
            "role": m.role,
            "assigned_active": Ticket.objects.filter(
                queue=queue, assignee=m.user, is_deleted=False,
                status__in=OPEN_STATUSES).count(),
        })
    return {
        "queue": queue.pk,
        "queue_name": queue.name,
        "total_active": qs.count(),
        "unassigned": qs.filter(assignee_id__isnull=True).count(),
        "assigned": qs.filter(assignee_id__isnull=False).count(),
        "in_progress": qs.filter(status="in_progress").count(),
        "waiting_requester": qs.filter(status="waiting_requester").count(),
        "waiting_third_party": qs.filter(status="waiting_third_party").count(),
        "overdue": qs.filter(status__in=OPEN_STATUSES,
                             sla_due_at__lt=now).count(),
        "sla_breached": qs.filter(sla_breached=True).count(),
        "urgent": qs.filter(priority="critical", status__in=OPEN_STATUSES).count(),
        "oldest_ticket_age_days": _oldest_age(qs, now),
        "members": members.count(),
        "workload_by_member": member_workload,
    }


def agent_workload(filters, user):
    if not _is_it_staff(user):
        raise PermissionDenied("Workload metrics are IT-staff only.")
    qs = Ticket.objects.filter(is_deleted=False)
    qs = _apply_filters(qs, filters)
    now = timezone.now()
    assignee_ids = qs.exclude(assignee_id__isnull=True).values_list(
        "assignee_id", flat=True).distinct()
    rows = []
    for uid in assignee_ids:
        u = User.objects.filter(pk=uid).first()
        if not u:
            continue
        rows.append({
            "user": uid,
            "user_name": getattr(u, "employee_id", str(uid)),
            "role": getattr(u, "role", ""),
            "assigned_active": Ticket.objects.filter(
                assignee=u, is_deleted=False, status__in=OPEN_STATUSES).count(),
            "urgent": Ticket.objects.filter(
                assignee=u, is_deleted=False, priority="critical",
                status__in=OPEN_STATUSES).count(),
            "sla_breached": Ticket.objects.filter(
                assignee=u, is_deleted=False, sla_breached=True).count(),
            "waiting_requester": Ticket.objects.filter(
                assignee=u, is_deleted=False, status="waiting_requester").count(),
        })
    rows.sort(key=lambda r: r["assigned_active"], reverse=True)
    return {
        "total_assigned_active": qs.filter(
            assignee_id__isnull=False, status__in=OPEN_STATUSES).count(),
        "by_agent": rows,
    }


def _apply_filters(qs, filters):
    if not filters:
        return qs
    if filters.get("date_from"):
        qs = qs.filter(created_at__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(created_at__lte=filters["date_to"])
    if filters.get("department"):
        qs = qs.filter(department_id=filters["department"])
    if filters.get("queue"):
        qs = qs.filter(queue_id=filters["queue"])
    if filters.get("assignee"):
        qs = qs.filter(assignee_id=filters["assignee"])
    if filters.get("category"):
        qs = qs.filter(category_id=filters["category"])
    if filters.get("priority"):
        qs = qs.filter(priority=filters["priority"])
    return qs


def _oldest_age(qs, now):
    oldest = qs.order_by("created_at").first()
    return (now - oldest.created_at).days if oldest else None

