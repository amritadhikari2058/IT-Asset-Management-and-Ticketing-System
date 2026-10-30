p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\exports.py"
src = open(p, encoding="utf-8").read()

anchor = "def _cell(row, field):"
assert src.count(anchor) == 1, src.count(anchor)

builders = """def employee_rows():
    from accounts.models import Department, User

    departments = list(Department.objects.order_by("name"))
    dept_by_id = {d.id: d for d in departments}
    rows = []
    for u in User.objects.filter(is_deleted=False).order_by("employee_id"):
        dept = dept_by_id.get(u.home_department_id)
        rows.append({
            "id": u.pk,
            "employee_id": u.employee_id,
            "username": u.username,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "phone": u.phone,
            "job_title": u.job_title,
            "department": dept.name if dept else "",
            "role": u.role,
            "is_active": "true" if u.is_active else "false",
            "created_at": u.created_at.isoformat() if u.created_at else "",
            "updated_at": u.updated_at.isoformat() if u.updated_at else "",
        })
    return rows


def department_rows():
    from accounts.models import Department

    return [
        {
            "id": d.pk,
            "name": d.name,
            "code": d.code,
            "description": d.description or "",
            "head": d.head_id or "",
            "head_email": d.head.email if d.head else "",
            "is_active": "true" if d.is_active else "false",
            "member_count": d.members.count(),
            "asset_count": d.assets.count(),
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "updated_at": d.updated_at.isoformat() if d.updated_at else "",
        }
        for d in Department.objects.order_by("name")
    ]


def asset_rows():
    from assets.models import Asset

    return [
        {
            "id": a.pk,
            "asset_tag": a.asset_tag,
            "name": a.name,
            "serial_number": a.serial_number or "",
            "status": a.status,
            "location": a.location,
            "category": a.category.name if a.category_id else "",
            "department": a.department.name if a.department_id else "",
            "purchase_date": a.purchase_date.isoformat() if a.purchase_date else "",
            "warranty_expiry": a.warranty_expiry.isoformat() if a.warranty_expiry else "",
            "purchase_cost": str(a.purchase_cost) if a.purchase_cost is not None else "",
            "created_at": a.created_at.isoformat() if a.created_at else "",
            "updated_at": a.updated_at.isoformat() if a.updated_at else "",
        }
        for a in Asset.objects.order_by("asset_tag")
    ]


def assignment_rows():
    from assets.models import Assignment

    rows = []
    for a in Assignment.objects.select_related(
            "asset", "assigned_to", "assigned_by").order_by("id"):
        rows.append({
            "id": a.pk,
            "asset_tag": a.asset.asset_tag if a.asset_id else "",
            "employee_id": a.assigned_to.employee_id if a.assigned_to_id else "",
            "employee_email": a.assigned_to.email if a.assigned_to_id else "",
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else "",
            "returned_at": a.returned_at.isoformat() if a.returned_at else "",
            "note": a.note or "",
            "assigned_by_email": a.assigned_by.email if a.assigned_by_id else "",
        })
    return rows


def ticket_rows(user=None):
    from django.db.models import Q
    from tickets.models import Ticket

    qs = Ticket.objects.all()
    if user is not None and user.pk and getattr(user, "role", "") == "employee":
        qs = qs.filter(Q(requester=user) | Q(assignee=user))
    return [
        {
            "id": t.pk,
            "ticket_no": str(t.pk),
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "category": t.category.name if t.category_id else "",
            "department": t.department.name if t.department_id else "",
            "requester": t.requester_id or "",
            "assignee": t.assignee_id or "",
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "updated_at": t.updated_at.isoformat() if t.updated_at else "",
        }
        for t in qs.order_by("-created_at")
    ]


def category_rows(model):
    return [
        {
            "id": c.pk,
            "name": c.name,
            "description": c.description or "",
            "is_active": "true" if c.is_active else "false",
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "updated_at": c.updated_at.isoformat() if c.updated_at else "",
        }
        for c in model.objects.order_by("name")
    ]


def ticket_history_rows():
    from tickets.models import TicketHistory

    return [
        {
            "id": h.pk,
            "ticket_no": str(h.ticket_id),
            "action": h.action,
            "actor": h.actor_id or "",
            "timestamp": h.timestamp.isoformat() if h.timestamp else "",
            "old_values": str(h.old_values or {}),
            "new_values": str(h.new_values or {}),
            "note": h.note or "",
        }
        for h in TicketHistory.objects.select_related("actor").order_by(
            "ticket_id", "-timestamp", "-id")[:5000]
    ]


BUILDERS = {
    "employees": employee_rows,
    "departments": department_rows,
    "assets": asset_rows,
    "assignments": assignment_rows,
    "tickets": ticket_rows,
    "ticket_categories": lambda: category_rows(
        __import__("tickets.models", fromlist=["TicketCategory"]).TicketCategory),
    "asset_categories": lambda: category_rows(
        __import__("assets.models", fromlist=["AssetCategory"]).AssetCategory),
    "ticket_history": ticket_history_rows,
}


def build_rows(dataset, user=None):
    builder = BUILDERS.get(dataset)
    if not builder:
        return []
    return builder(user)


"""

src = src.replace(anchor, builders + anchor, 1)
open(p, "w", encoding="utf-8").write(src)
print("builders added")

