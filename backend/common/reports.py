"""Operational reporting aggregations (dashboard + department reports).

Everything here is read-only and ORM-driven. Average resolution times are
computed in Python so the same code works on SQLite (which cannot Avg a
date/time field stored as text) and PostgreSQL.
"""
from datetime import datetime, time

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date

OPEN_TICKET_STATUSES = ("open", "in_progress", "reopened")
CLOSED_TICKET_STATUSES = ("resolved", "closed", "archived")


def _status_counts(queryset, field, choices):
    """Zero-filled {choice: count} for a model field."""
    counts = {key: 0 for key, _label in choices}
    for row in queryset.values(field).annotate(_n=Count("id")):
        key = row.get(field)
        if key in counts:
            counts[key] = row["_n"]
    return counts


def _sla_metrics(tickets, now=None):
    """Return overdue/breached counts + compliance from an in-memory list.

    - overdue: still open (not resolved/closed/archived) and past due.
    - breached: resolved after its due date, or open and past due.
    - compliance: resolved-with-due-date tickets resolved on time, as a %.
    """
    now = now or timezone.now()
    overdue = 0
    breached = 0
    resolved_with_sla = 0
    resolved_on_time = 0
    for t in tickets:
        due = getattr(t, "sla_due_at", None)
        if not due:
            continue
        resolved_at = getattr(t, "resolved_at", None)
        status = getattr(t, "status", "")
        if status not in CLOSED_TICKET_STATUSES and now > due:
            overdue += 1
            breached += 1
        if resolved_at:
            resolved_with_sla += 1
            if resolved_at <= due:
                resolved_on_time += 1
            else:
                breached += 1
    compliance = (
        round((resolved_on_time / resolved_with_sla) * 100, 1)
        if resolved_with_sla else None
    )
    return {
        "overdue": overdue,
        "breached": breached,
        "resolved_with_sla": resolved_with_sla,
        "resolved_on_time": resolved_on_time,
        "compliance_pct": compliance,
    }


def _avg_resolution_hours(tickets):
    deltas = [
        (t.resolved_at - t.created_at).total_seconds() / 3600
        for t in tickets
        if getattr(t, "resolved_at", None) and getattr(t, "created_at", None)
    ]
    return round(sum(deltas) / len(deltas), 2) if deltas else None


def _coerce_date(value, end_of_day=False):
    """Accept a datetime or an ISO date string; end_of_day covers the date."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    parsed = parse_date(str(value)[:10])
    if parsed is None:
        return None
    return timezone.make_aware(
        datetime.combine(parsed, time.max if end_of_day else time.min))


def _apply_ticket_dates(qs, date_from=None, date_to=None):
    start = _coerce_date(date_from)
    end = _coerce_date(date_to, end_of_day=True)
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    return qs


def dashboard_data(date_from=None, date_to=None):
    """Aggregate metrics for the management dashboard."""
    from accounts.models import Department, User
    from assets.models import Asset, Disposal, Maintenance
    from tickets.models import Ticket

    now = timezone.now()
    employees = User.objects.all()
    assets = Asset.objects.all()
    tickets = _apply_ticket_dates(
        Ticket.objects.all(), date_from, date_to)

    ticket_status = _status_counts(tickets, "status", Ticket.STATUS_CHOICES)
    ticket_priority = _status_counts(
        tickets, "priority", Ticket.PRIORITY_CHOICES)
    asset_status = _status_counts(assets, "status", Asset.STATUS_CHOICES)

    open_tickets = tickets.filter(status__in=OPEN_TICKET_STATUSES)
    overdue_qs = open_tickets.filter(sla_due_at__lt=now)
    ticket_list = list(tickets.only(
        "status", "priority", "sla_due_at", "resolved_at", "created_at"))
    sla = _sla_metrics(ticket_list, now)

    open_maintenance = Maintenance.objects.select_related(
        "asset").filter(
        status__in=["scheduled", "in_progress", "overdue"])
    upcoming = open_maintenance.filter(
        scheduled_date__gte=now).order_by("scheduled_date", "id")[:8]
    overdue_maintenance = open_maintenance.filter(scheduled_date__lt=now)

    pending_disposals = Disposal.objects.filter(approval_status="pending")
    approved_disposals = Disposal.objects.filter(
        approval_status="approved", disposal_date__isnull=True)

    return {
        "employees": {
            "total": employees.count(),
            "active": employees.filter(is_active=True).count(),
            "inactive": employees.filter(is_active=False).count(),
            "departments": Department.objects.count(),
        },
        "assets": {
            "total": assets.count(),
            "by_status": asset_status,
            "under_maintenance": assets.filter(
                status="in_repair").count(),
            "with_open_maintenance": Asset.objects.filter(
                maintenance__status__in=[
                    "scheduled", "in_progress", "overdue"]).distinct().count(),
        },
        "tickets": {
            "total": tickets.count(),
            "open": open_tickets.count(),
            "overdue": overdue_qs.count(),
            "by_status": ticket_status,
            "by_priority": ticket_priority,
            "sla": sla,
            "avg_resolution_hours": _avg_resolution_hours(ticket_list),
        },
        "maintenance": {
            "open": open_maintenance.count(),
            "overdue": overdue_maintenance.count(),
            "upcoming": [
                {
                    "id": m.pk,
                    "asset_id": m.asset_id,
                    "asset_tag": m.asset.asset_tag,
                    "title": m.title,
                    "status": m.status,
                    "scheduled_date": m.scheduled_date.isoformat()
                    if m.scheduled_date else None,
                }
                for m in upcoming
            ],
        },
        "disposals": {
            "pending_approval": pending_disposals.count(),
            "approved_not_completed": approved_disposals.count(),
            "recent": [
                {
                    "id": d.pk,
                    "asset_id": d.asset_id,
                    "asset_tag": d.asset.asset_tag,
                    "approval_status": d.approval_status,
                    "created_at": d.created_at.isoformat()
                    if d.created_at else None,
                }
                for d in Disposal.objects.select_related("asset").order_by(
                    "-created_at")[:5]
            ],
        },
        "filters": {"date_from": date_from, "date_to": date_to},
        "generated_at": now.isoformat(),
    }


def department_report_data(date_from=None, date_to=None,
                           date_from_prev=None, date_to_prev=None):
    """Per-department employee, asset, ticket and SLA breakdown.

    If ``date_from_prev``/``date_to_prev`` are given, the same-width window
    shifted back is also computed and returned alongside the current period
    so the UI can show a side‑by‑side comparison.
    """
    from accounts.models import Department, User
    from assets.models import Asset
    from tickets.models import Ticket

    now = timezone.now()

    # ---- current period ----
    tickets = list(_apply_ticket_dates(
        Ticket.objects.all(), date_from, date_to).only(
            "id", "department_id", "status", "priority", "sla_due_at",
            "resolved_at", "created_at"))
    assets = list(Asset.objects.only("id", "department_id", "status"))

    # ---- previous period (same-width window shifted back) ----
    tickets_prev, assets_prev = [], []
    if date_from_prev is not None and date_to_prev is not None:
        tickets_prev = list(_apply_ticket_dates(
            Ticket.objects.all(), date_from_prev, date_to_prev).only(
                "id", "department_id", "status", "priority", "sla_due_at",
                "resolved_at", "created_at"))
        assets_prev = list(Asset.objects.only("id", "department_id", "status"))

    # ---- build per-department buckets for current period ----
    departments = list(Department.objects.order_by("name"))
    users = list(User.objects.only("id", "home_department_id", "is_active"))
    unassigned = {
        "id": None, "name": "Unassigned", "code": "",
        "employees": [], "assets": [], "tickets": [],
    }

    def _populate_bucket(bucket, src_assets, src_tickets):
        for u in users:
            bucket["employees"].append(u)
        for a in src_assets:
            bucket["assets"].append(a)
        for t in src_tickets:
            bucket["tickets"].append(t)

    buckets = {}
    for d in departments:
        buckets[d.pk] = {
            "id": d.pk, "name": d.name, "code": d.code,
            "employees": [], "assets": [], "tickets": [],
        }
    _populate_bucket(buckets, assets, tickets)

    # previous-period buckets for the same departments
    buckets_prev = {}
    if date_from_prev is not None and date_to_prev is not None:
        buckets_prev = {}
        for d in departments:
            buckets_prev[d.pk] = {
                "id": d.pk, "name": d.name, "code": d.code,
                "employees": [], "assets": [], "tickets": [],
            }
        _populate_bucket(buckets_prev, assets_prev, tickets_prev)

    # ---- compute per-department results (current period) ----
    results = []
    for d in departments:
        bucket = buckets[d.pk]
        dept_tickets = bucket["tickets"]
        status_counts = _status_counts(
            _AsQuerySet(dept_tickets), "status", Ticket.STATUS_CHOICES)
        priority_counts = _status_counts(
            _AsQuerySet(dept_tickets), "priority", Ticket.PRIORITY_CHOICES)
        asset_counts = _status_counts(
            _AsQuerySet(bucket["assets"]), "status", Asset.STATUS_CHOICES)
        sla = _sla_metrics(dept_tickets, now)
        results.append({
            "id": bucket["id"],
            "name": bucket["name"],
            "code": bucket["code"],
            "employees_total": len(bucket["employees"]),
            "employees_active": sum(
                1 for u in bucket["employees"] if u.is_active),
            "assets_total": len(bucket["assets"]),
            "assets_by_status": asset_counts,
            "tickets_total": len(dept_tickets),
            "tickets_open": sum(
                1 for t in dept_tickets
                if t.status in OPEN_TICKET_STATUSES),
            "tickets_by_status": status_counts,
            "tickets_by_priority": priority_counts,
            "sla_overdue": sla["overdue"],
            "sla_breached": sla["breached"],
            "sla_compliance_pct": sla["compliance_pct"],
            "avg_resolution_hours": _avg_resolution_hours(dept_tickets),
        })

    # ---- previous-period results (if applicable) ----
    results_prev = []
    if date_from_prev is not None and date_to_prev is not None:
        for d in departments:
            bucket = buckets_prev[d.pk]
            dept_tickets = bucket["tickets"]
            status_counts = _status_counts(
                _AsQuerySet(dept_tickets), "status", Ticket.STATUS_CHOICES)
            priority_counts = _status_counts(
                _AsQuerySet(dept_tickets), "priority", Ticket.PRIORITY_CHOICES)
            asset_counts = _status_counts(
                _AsQuerySet(bucket["assets"]), "status", Asset.STATUS_CHOICES)
            sla = _sla_metrics(dept_tickets, now)
            results_prev.append({
                "id": bucket["id"],
                "name": bucket["name"],
                "code": bucket["code"],
                "employees_total": len(bucket["employees"]),
                "employees_active": sum(
                    1 for u in bucket["employees"] if u.is_active),
                "assets_total": len(bucket["assets"]),
                "assets_by_status": asset_counts,
                "tickets_total": len(dept_tickets),
                "tickets_open": sum(
                    1 for t in dept_tickets
                    if t.status in OPEN_TICKET_STATUSES),
                "tickets_by_status": status_counts,
                "tickets_by_priority": priority_counts,
                "sla_overdue": sla["overdue"],
                "sla_breached": sla["breached"],
                "sla_compliance_pct": sla["compliance_pct"],
                "avg_resolution_hours": _avg_resolution_hours(dept_tickets),
            })

    return {
        "results": results,
        "results_prev": results_prev,
        "filters": {
            "date_from": date_from, "date_to": date_to,
            "date_from_prev": date_from_prev, "date_to_prev": date_to_prev,
        },
        "generated_at": now.isoformat(),
    }


class _AsQuerySet:
    """Minimal adapter so _status_counts can consume an in-memory list.

    The list is small (per department) and already filtered; this keeps one
    counting implementation for both ORM querysets and Python lists.
    """

    def __init__(self, rows):
        self.rows = rows

    def values(self, field):
        return _Values(self.rows, field)


class _Values:
    def __init__(self, rows, field):
        self.rows = rows
        self.field = field

    def annotate(self, **_kwargs):
        counts = {}
        for row in self.rows:
            key = getattr(row, self.field, None)
            if key is None:
                continue
            counts[key] = counts.get(key, 0) + 1
        return [{self.field: k, "_n": v} for k, v in counts.items()]


def maintenance_rows(user=None, filters=None):
    from assets.models import Maintenance

    filters = filters or {}
    qs = Maintenance.objects.select_related(
        "asset", "assigned_to", "created_by").all()
    status = filters.get("status")
    if status:
        qs = qs.filter(status=status)
    maintenance_type = filters.get("maintenance_type")
    if maintenance_type:
        qs = qs.filter(maintenance_type=maintenance_type)
    asset = filters.get("asset")
    if asset:
        qs = qs.filter(asset_id=asset)
    assigned_to = filters.get("assigned_to")
    if assigned_to:
        qs = qs.filter(assigned_to_id=assigned_to)
    if filters.get("open") in ("true", "1", True):
        qs = qs.filter(status__in=["scheduled", "in_progress", "overdue"])
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q) | Q(vendor__icontains=q))
    rows = []
    for m in qs.order_by("-scheduled_date", "-id"):
        rows.append({
            "id": m.pk,
            "asset_tag": m.asset.asset_tag if m.asset_id else "",
            "asset_name": m.asset.name if m.asset_id else "",
            "title": m.title,
            "maintenance_type": m.maintenance_type,
            "status": m.status,
            "scheduled_date": m.scheduled_date.isoformat()
            if m.scheduled_date else "",
            "start_date": m.start_date.isoformat() if m.start_date else "",
            "completion_date": m.completion_date.isoformat()
            if m.completion_date else "",
            "assigned_to": m.assigned_to.email if m.assigned_to_id else "",
            "vendor": m.vendor or "",
            "cost": str(m.cost) if m.cost is not None else "",
            "is_overdue": "true" if m.is_overdue else "false",
            "created_at": m.created_at.isoformat() if m.created_at else "",
        })
    return rows


def disposal_rows(user=None, filters=None):
    from assets.models import Disposal

    filters = filters or {}
    qs = Disposal.objects.select_related(
        "asset", "responsible_person", "approver", "created_by").all()
    approval_status = filters.get("approval_status")
    if approval_status:
        qs = qs.filter(approval_status=approval_status)
    disposal_method = filters.get("disposal_method")
    if disposal_method:
        qs = qs.filter(disposal_method=disposal_method)
    asset = filters.get("asset")
    if asset:
        qs = qs.filter(asset_id=asset)
    completed = filters.get("completed")
    if completed in ("true", "1", True):
        qs = qs.filter(disposal_date__isnull=False)
    elif completed in ("false", "0", False):
        qs = qs.filter(disposal_date__isnull=True)
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(disposal_reason__icontains=q))
    rows = []
    for d in qs.order_by("-created_at", "-id"):
        rows.append({
            "id": d.pk,
            "asset_tag": d.asset.asset_tag if d.asset_id else "",
            "asset_name": d.asset.name if d.asset_id else "",
            "approval_status": d.approval_status,
            "disposal_date": d.disposal_date.isoformat()
            if d.disposal_date else "",
            "disposal_reason": d.disposal_reason or "",
            "disposal_method": d.disposal_method,
            "disposal_value": str(d.disposal_value)
            if d.disposal_value is not None else "",
            "responsible_person": d.responsible_person.email
            if d.responsible_person_id else "",
            "approver": d.approver.email if d.approver_id else "",
            "approved_at": d.approved_at.isoformat()
            if d.approved_at else "",
            "is_completed": "true" if d.is_completed else "false",
            "created_at": d.created_at.isoformat() if d.created_at else "",
        })
    return rows


def department_report_rows(user=None, filters=None):
    filters = filters or {}
    data = department_report_data(
        filters.get("date_from"), filters.get("date_to"))
    rows = []
    for r in data["results"]:
        assets = r["assets_by_status"]
        tickets = r["tickets_by_status"]
        priorities = r["tickets_by_priority"]
        rows.append({
            "id": r["id"] if r["id"] is not None else "",
            "name": r["name"],
            "code": r["code"],
            "employees_total": r["employees_total"],
            "employees_active": r["employees_active"],
            "assets_total": r["assets_total"],
            "assets_available": assets.get("available", 0),
            "assets_assigned": assets.get("assigned", 0),
            "assets_in_repair": assets.get("in_repair", 0),
            "assets_retired": assets.get("retired", 0),
            "assets_lost": assets.get("lost", 0),
            "assets_disposed": assets.get("disposed", 0),
            "tickets_total": r["tickets_total"],
            "tickets_open": r["tickets_open"],
            "tickets_in_progress": tickets.get("in_progress", 0),
            "tickets_resolved": tickets.get("resolved", 0),
            "tickets_closed": tickets.get("closed", 0),
            "tickets_reopened": tickets.get("reopened", 0),
            "tickets_archived": tickets.get("archived", 0),
            "priority_low": priorities.get("low", 0),
            "priority_medium": priorities.get("medium", 0),
            "priority_high": priorities.get("high", 0),
            "priority_critical": priorities.get("critical", 0),
            "sla_overdue": r["sla_overdue"],
            "sla_breached": r["sla_breached"],
            "sla_compliance_pct": r["sla_compliance_pct"]
            if r["sla_compliance_pct"] is not None else "",
            "avg_resolution_hours": r["avg_resolution_hours"]
            if r["avg_resolution_hours"] is not None else "",
        })
    return rows
