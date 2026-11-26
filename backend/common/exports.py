"""Shared export preparation + rendering layer: CSV, XLSX, PDF, DOCX.

Every dataset is rendered from plain field lists plus row dicts so the same
code path can serve the read-only list endpoints and the export endpoint.

All exports:
- respect the caller's permissions (enforced by the view, server-side),
- never embed secrets or password material,
- escape CSV values against spreadsheet formula injection,
- produce deterministic, readable documents with headers + repeating table
  headers where the format supports it.
"""
import csv
import io
from datetime import datetime

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from rest_framework.renderers import BaseRenderer

EXPORT_FORMATS = ("csv", "xlsx", "pdf", "docx")


class ExportCsvRenderer(BaseRenderer):
    media_type = "text/csv"
    format = "csv"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


class ExportXlsxRenderer(BaseRenderer):
    media_type = ("application/vnd.openxmlformats-officedocument."
                  "spreadsheetml.sheet")
    format = "xlsx"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


class ExportPdfRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


class ExportDocxRenderer(BaseRenderer):
    media_type = ("application/vnd.openxmlformats-officedocument."
                  "wordprocessingml.document")
    format = "docx"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


EXPORT_RENDERER_CLASSES = [
    ExportCsvRenderer, ExportXlsxRenderer, ExportPdfRenderer, ExportDocxRenderer,
]

DATASETS = {
    "employees": {
        "title": "Employees",
        "fields": [
            "id", "employee_id", "username", "email", "first_name",
            "last_name", "phone", "job_title", "department", "role",
            "is_active", "created_at", "updated_at",
        ],
        "permission": "it_staff",
    },
    "departments": {
        "title": "Departments",
        "fields": [
            "id", "name", "code", "description", "head", "head_email",
            "is_active", "member_count", "asset_count", "created_at",
            "updated_at",
        ],
        "permission": "it_staff",
    },
    "assets": {
        "title": "Assets",
        "fields": [
            "id", "asset_tag", "name", "serial_number", "status", "location",
            "category", "department", "purchase_date", "warranty_expiry",
            "purchase_cost", "created_at", "updated_at",
        ],
        "permission": "authenticated",
    },
    "assignments": {
        "title": "Asset Assignments",
        "fields": [
            "id", "asset_tag", "employee_id", "employee_email", "assigned_at",
            "returned_at", "note", "assigned_by_email",
        ],
        #: Assignment rows carry employee_email and assigned_by_email (PII of
        #: both employees and staff). Exporting them must require IT staff,
        #: matching the ``employees`` dataset which protects the same data;
        #: authenticated employees must not bulk-harvest contact details.
        "permission": "it_staff",
    },
    "tickets": {
        "title": "Tickets",
        "fields": [
            "id", "ticket_no", "title", "status", "priority", "category",
            "department", "requester", "assignee", "created_at", "updated_at",
        ],
        "permission": "authenticated",
    },
    "ticket_categories": {
        "title": "Ticket Categories",
        "fields": [
            "id", "name", "description", "is_active", "created_at", "updated_at",
        ],
        "permission": "authenticated",
    },
    "asset_categories": {
        "title": "Asset Categories",
        "fields": [
            "id", "name", "description", "is_active", "created_at", "updated_at",
        ],
        "permission": "authenticated",
    },
    "ticket_history": {
        "title": "Ticket History",
        "fields": [
            "id", "ticket_no", "action", "actor", "timestamp", "old_values",
            "new_values", "note",
        ],
        "permission": "it_staff",
    },
    "maintenance": {
        "title": "Asset Maintenance",
        "fields": [
            "id", "asset_tag", "asset_name", "title", "maintenance_type",
            "status", "scheduled_date", "start_date", "completion_date",
            "assigned_to", "vendor", "cost", "is_overdue", "created_at",
        ],
        "permission": "it_staff",
    },
    "disposals": {
        "title": "Asset Disposals",
        "fields": [
            "id", "asset_tag", "asset_name", "approval_status",
            "disposal_date", "disposal_reason", "disposal_method",
            "disposal_value", "responsible_person", "approver", "approved_at",
            "is_completed", "created_at",
        ],
        "permission": "it_staff",
    },
    "department_report": {
        "title": "Department Report",
        "fields": [
            "id", "name", "code", "employees_total", "employees_active",
            "assets_total", "assets_available", "assets_assigned",
            "assets_in_repair", "assets_retired", "assets_lost",
            "assets_disposed", "tickets_total", "tickets_open",
            "tickets_in_progress", "tickets_resolved", "tickets_closed",
            "tickets_reopened", "tickets_archived", "priority_low",
            "priority_medium", "priority_high", "priority_critical",
            "sla_overdue", "sla_breached", "sla_compliance_pct",
            "avg_resolution_hours",
        ],
        "permission": "it_staff",
    },
    "knowledge_base": {
        "title": "Knowledge Base",
        "fields": [
            "id", "title", "slug", "summary", "category", "tags", "status",
            "author", "created_at", "updated_at", "revision_number",
        ],
        "permission": "authenticated",
    },
}


def employee_rows(user=None, filters=None):
    from accounts.models import Department, User

    filters = filters or {}
    qs = User.objects.filter(is_deleted=False)
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(employee_id__icontains=q) | Q(email__icontains=q)
            | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    department = filters.get("department")
    if department:
        try:
            qs = qs.filter(home_department__id=int(department))
        except (TypeError, ValueError):
            qs = qs.filter(home_department__code__iexact=department)
    role = filters.get("role")
    if role:
        qs = qs.filter(role=role)
    is_active = filters.get("is_active")
    if is_active is not None:
        wanted = str(is_active).strip().lower() in ("true", "1", "yes")
        qs = qs.filter(is_active=wanted)
    qs = qs.select_related("home_department")
    for u in qs.order_by("employee_id").iterator(chunk_size=1000):
        dept = u.home_department if u.home_department_id else None
        yield {
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
            "created_at": u.date_joined.isoformat() if u.date_joined else "",
            "updated_at": u.last_login.isoformat() if u.last_login else "",
        }


def department_rows(user=None, filters=None):
    from accounts.models import Department

    filters = filters or {}
    qs = Department.objects.annotate(
        member_count=Count(
            "members",
            filter=Q(members__is_deleted=False, members__is_active=True),
            distinct=True,
        ),
        asset_count=Count(
            "assets",
            filter=Q(assets__is_deleted=False),
            distinct=True,
        ),
    ).select_related("head")
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    for d in qs.order_by("name").iterator(chunk_size=500):
        yield {
            "id": d.pk,
            "name": d.name,
            "code": d.code,
            "description": d.description or "",
            "head": d.head_id or "",
            "head_email": (d.head.email if d.head_id and not d.head.is_deleted else ""),
            "is_active": "true" if d.is_active else "false",
            "member_count": d.member_count,
            "asset_count": d.asset_count,
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "updated_at": d.updated_at.isoformat() if d.updated_at else "",
        }


def _scalar_filter(filters, key):
    """Return a single filter value, tolerating list-valued containers."""
    value = filters.get(key)
    if isinstance(value, (list, tuple)):
        return value[-1] if value else None
    return value


def _asset_date_filter(filters, key):
    raw = _scalar_filter(filters, key)
    if raw in (None, ""):
        return None
    parsed = parse_date(str(raw))
    if parsed is None:
        raise ValueError(f"{key} must be a valid ISO date (YYYY-MM-DD).")
    return parsed


def asset_rows(user=None, filters=None):
    from assets.models import Asset

    filters = filters or {}
    qs = Asset.objects.all()
    # Row-level scope for employees mirrors the asset list API
    # (_asset_visible_qs): employees may only see assets assigned to them or
    # in their home department. IT staff see everything. This prevents the
    # export from bypassing list-level IDOR/scope restrictions so an
    # employee cannot enumerate every asset (incl. purchase cost) via export.
    if user is not None and getattr(user, "is_authenticated", False):
        role = getattr(user, "role", "")
        if (role not in ("system_admin", "it_manager", "it_support")
                and not getattr(user, "is_superuser", False)):
            filt = Q(assigned_to=user)
            if getattr(user, "home_department_id", None):
                filt |= Q(department_id=user.home_department_id)
            qs = qs.filter(filt)
    q = (_scalar_filter(filters, "q") or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(asset_tag__icontains=q)
            | Q(serial_number__icontains=q) | Q(location__icontains=q)
            | Q(department__name__icontains=q) | Q(department__code__icontains=q))
    status = _scalar_filter(filters, "status")
    if status:
        qs = qs.filter(status=status)
    category = _scalar_filter(filters, "category")
    if category:
        qs = qs.filter(category_id=category)
    department = _scalar_filter(filters, "department")
    if department:
        qs = qs.filter(department_id=department)
    from_date = _asset_date_filter(filters, "from_date")
    to_date = _asset_date_filter(filters, "to_date")
    if from_date:
        qs = qs.filter(purchase_date__gte=from_date)
    if to_date:
        qs = qs.filter(purchase_date__lte=to_date)
    for a in qs.select_related(
            "category", "department").order_by("asset_tag").iterator(
                chunk_size=1000):
        yield {
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


def assignment_rows(user=None, filters=None):
    from assets.models import Assignment

    filters = filters or {}
    qs = Assignment.objects.select_related(
        "asset", "assigned_to", "assigned_by").all()
    asset = filters.get("asset")
    if asset:
        qs = qs.filter(asset_id=asset)
    assigned_to = filters.get("assigned_to")
    if assigned_to:
        qs = qs.filter(assigned_to_id=assigned_to)
    for a in qs.order_by("id").iterator(chunk_size=1000):
        yield {
            "id": a.pk,
            "asset_tag": a.asset.asset_tag if a.asset_id else "",
            "employee_id": a.assigned_to.employee_id if a.assigned_to_id else "",
            "employee_email": a.assigned_to.email if a.assigned_to_id else "",
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else "",
            "returned_at": a.returned_at.isoformat() if a.returned_at else "",
            "note": a.note or "",
            "assigned_by_email": a.assigned_by.email if a.assigned_by_id else "",
        }


def ticket_rows(user=None, filters=None):
    from django.db.models import Q
    from tickets.models import Ticket

    filters = filters or {}
    qs = Ticket.objects.all()
    if user is not None and user.pk and getattr(user, "role", "") == "employee":
        qs = qs.filter(Q(requester=user) | Q(assignee=user))
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    status = filters.get("status")
    if status:
        qs = qs.filter(status=status)
    priority = filters.get("priority")
    if priority:
        qs = qs.filter(priority=priority)
    category = filters.get("category")
    if category:
        qs = qs.filter(category_id=category)
    department = filters.get("department")
    if department:
        qs = qs.filter(department_id=department)
    assignee = filters.get("assignee")
    if assignee:
        qs = qs.filter(assignee_id=assignee)
    for t in qs.select_related(
            "category", "department").order_by(
                "-created_at").iterator(chunk_size=1000):
        yield {
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


def category_rows(model, filters=None):
    filters = filters or {}
    qs = model.objects.all()
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    is_active = filters.get("is_active")
    if is_active is not None:
        wanted = str(is_active).strip().lower() in ("true", "1", "yes")
        qs = qs.filter(is_active=wanted)
    for c in qs.order_by("name").iterator(chunk_size=1000):
        yield {
            "id": c.pk,
            "name": c.name,
            "description": c.description or "",
            "is_active": "true" if c.is_active else "false",
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "updated_at": c.updated_at.isoformat() if c.updated_at else "",
        }


def ticket_history_rows(user=None, filters=None):
    from tickets.models import TicketHistory

    filters = filters or {}
    qs = TicketHistory.objects.select_related("actor").all()
    ticket = filters.get("ticket")
    if ticket:
        qs = qs.filter(ticket_id=ticket)
    action = filters.get("action")
    if action:
        qs = qs.filter(action=action)
    for h in qs.order_by(
            "ticket_id", "-timestamp", "-id")[:5000].iterator(
                chunk_size=1000):
        yield {
            "id": h.pk,
            "ticket_no": str(h.ticket_id),
            "action": h.action,
            "actor": h.actor_id or "",
            "timestamp": h.timestamp.isoformat() if h.timestamp else "",
            "old_values": str(h.old_values or {}),
            "new_values": str(h.new_values or {}),
            "note": h.note or "",
        }


def kb_rows(user=None, filters=None):
    """Published Knowledge Base article rows for export.

    Only published articles are exported, so employees (authenticated)
    never receive drafts, pending-review, approved-but-unpublished, or
    archived articles. Internal revision content, review comments, and
    staff-only metadata are deliberately excluded.
    """
    from assets.models import KnowledgeBaseArticle

    filters = filters or {}
    #: Query params arrive as single values, but ``dict(QueryDict)`` can
    #: yield lists; normalize scalars defensively.
    def _scalar(value):
        if isinstance(value, (list, tuple)):
            return value[0] if value else ""
        return value if value is not None else ""

    qs = (KnowledgeBaseArticle.objects
          .filter(status="published")
          .select_related("category", "author")
          .prefetch_related("tags"))
    q = _scalar(filters.get("q")).strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(summary__icontains=q)
            | Q(content__icontains=q)
            | Q(tags__name__icontains=q) | Q(tags__slug__icontains=q)
            | Q(category__name__icontains=q) | Q(category__code__icontains=q))
    category = _scalar(filters.get("category"))
    if category:
        qs = qs.filter(
            Q(category_id=category) if str(category).isdigit()
            else Q(category__code=category))
    tag = _scalar(filters.get("tag"))
    if tag:
        qs = qs.filter(tags__slug=tag)

    for a in qs.distinct().order_by(
            "-updated_at", "-id").iterator(chunk_size=500):
        yield {
            "id": a.pk,
            "title": a.title,
            "slug": a.slug,
            "summary": a.summary or "",
            "category": a.category.name if a.category_id else "",
            "tags": ", ".join(t.name for t in a.tags.all()),
            "status": a.status,
            "author": (a.author.get_full_name() or a.author.email)
            if a.author_id else "",
            "created_at": a.created_at.isoformat() if a.created_at else "",
            "updated_at": a.updated_at.isoformat() if a.updated_at else "",
            "revision_number": a.revision_number,
        }


BUILDERS = {
    "employees": employee_rows,
    "departments": department_rows,
    "assets": asset_rows,
    "assignments": assignment_rows,
    "tickets": ticket_rows,
    "ticket_categories": lambda filters=None: category_rows(
        __import__("tickets.models", fromlist=["TicketCategory"]).TicketCategory, filters),
    "asset_categories": lambda filters=None: category_rows(
        __import__("assets.models", fromlist=["AssetCategory"]).AssetCategory, filters),
    "ticket_history": ticket_history_rows,
    "knowledge_base": kb_rows,
    "maintenance": lambda user=None, filters=None: __import__(
        "common.reports", fromlist=["maintenance_rows"]).maintenance_rows(
            user, filters),
    "disposals": lambda user=None, filters=None: __import__(
        "common.reports", fromlist=["disposal_rows"]).disposal_rows(
            user, filters),
    "department_report": lambda user=None, filters=None: __import__(
        "common.reports", fromlist=["department_report_rows"]
    ).department_report_rows(user, filters),
}


def build_rows(dataset, user=None, filters=None):
    builder = BUILDERS.get(dataset)
    if not builder:
        return []
    return builder(user, filters or {})


def _cell(row, field):
    value = row.get(field)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fields_for(rows, fields=None):
    if fields is not None:
        return list(fields)
    keys = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
        if len(keys) >= 40:
            break
    return keys


def _escape(value):
    """Guard spreadsheet formula injection (CSV / XLSX / PDF / DOCX)."""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _csv_bytes(rows, fields):
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="utf-8", newline="")
    writer = csv.writer(stream)
    writer.writerow([_escape(f) for f in fields])
    for row in rows:
        writer.writerow([_escape(_cell(row, f)) for f in fields])
    stream.flush()
    return buf.getvalue()


def _xlsx_bytes(rows, fields, title):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=(title or "Export")[:31])
    ws.freeze_panes = "A2"
    header = []
    for field in fields:
        cell = WriteOnlyCell(ws, value=field)
        cell.font = Font(bold=True)
        header.append(cell)
    ws.append(header)
    row_count = 0
    for row in rows:
        values = [_cell(row, field) for field in fields]
        ws.append([
            _escape(value) if isinstance(value, str) else value
            for value in values
        ])
        row_count += 1
    last_row = max(row_count + 2, 2)
    ws.auto_filter.ref = "A1:" + get_column_letter(len(fields)) + str(last_row)
    for col_index, field in enumerate(fields, start=1):
        ws.column_dimensions[get_column_letter(col_index)].width = max(
            12, len(str(field)) + 4)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _pdf_bytes(rows, fields, title):
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [[_escape(f) for f in fields]]
    for row in rows:
        data.append([_escape(_cell(row, f)) for f in fields])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story = [
        Paragraph(title, styles["Title"]),
        Spacer(1, 6),
        Paragraph("Generated " + datetime.now().isoformat(), styles["Normal"]),
        Spacer(1, 12),
        table,
    ]

    def _on_pages(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(doc.pagesize[0] - 40, 20, "Page %d" % doc.page)
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_pages, onLaterPages=_on_pages)
    return buf.getvalue()


def _docx_bytes(rows, fields, title):
    from io import BytesIO
    from docx import Document
    from docx.shared import Pt

    buf = BytesIO()
    doc = Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph("Generated " + datetime.now().isoformat())
    doc.add_heading("Rows", level=1)
    table = doc.add_table(rows=1, cols=len(fields))
    table.style = "Table Grid"
    header = table.rows[0].cells
    for index, field in enumerate(fields):
        header[index].text = str(field)
        for paragraph in header[index].paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for column, field in enumerate(fields):
            value = _cell(row, field)
            cells[column].text = str(value)
            for paragraph in cells[column].paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(8)
    doc.save(buf)
    return buf.getvalue()


def render_response(dataset, rows, fmt, user, request):
    fields = DATASETS.get(dataset, {}).get("fields") or _fields_for(rows)
    title = DATASETS.get(dataset, {}).get("title") or dataset
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "%s_%s" % (dataset, stamp)

    row_count = 0

    def counted_rows():
        nonlocal row_count
        for row in rows:
            row_count += 1
            yield row

    if fmt == "csv":
        resp = HttpResponse(
            _csv_bytes(counted_rows(), fields), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="%s.csv"' % base
        resp.export_row_count = row_count
        return resp
    if fmt == "xlsx":
        data = _xlsx_bytes(counted_rows(), fields, title)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="%s.xlsx"' % base
        resp.export_row_count = row_count
        return resp
    if fmt == "pdf":
        data = _pdf_bytes(counted_rows(), fields, title)
        resp = HttpResponse(data, content_type="application/pdf")
        resp["Content-Disposition"] = 'attachment; filename="%s.pdf"' % base
        resp.export_row_count = row_count
        return resp
    if fmt == "docx":
        data = _docx_bytes(counted_rows(), fields, title)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        resp["Content-Disposition"] = 'attachment; filename="%s.docx"' % base
        resp.export_row_count = row_count
        return resp
    return None
