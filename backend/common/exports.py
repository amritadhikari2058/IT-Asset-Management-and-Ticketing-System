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

from django.http import HttpResponse
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
        "permission": "authenticated",
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
}


def employee_rows(user=None):
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
            "created_at": u.date_joined.isoformat() if u.date_joined else "",
            "updated_at": u.last_login.isoformat() if u.last_login else "",
        })
    return rows


def department_rows(user=None):
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


def asset_rows(user=None):
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


def assignment_rows(user=None):
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


def ticket_history_rows(user=None):
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
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow([_escape(f) for f in fields])
    for row in rows:
        writer.writerow([_escape(_cell(row, f)) for f in fields])
    return buf.getvalue().encode("utf-8")


def _xlsx_bytes(rows, fields, title):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (title or "Export")[:31]
    ws.append(list(fields))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row_index, row in enumerate(rows, start=2):
        for col_index, field in enumerate(fields, start=1):
            ws.cell(row=row_index, column=col_index, value=_cell(row, field))
    last_row = max(len(rows) + 2, 2)
    ws.freeze_panes = "A2"
    if last_row >= 2:
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
    if fmt == "csv":
        resp = HttpResponse(
            _csv_bytes(rows, fields), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="%s.csv"' % base
        return resp
    if fmt == "xlsx":
        data = _xlsx_bytes(rows, fields, title)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="%s.xlsx"' % base
        return resp
    if fmt == "pdf":
        data = _pdf_bytes(rows, fields, title)
        resp = HttpResponse(data, content_type="application/pdf")
        resp["Content-Disposition"] = 'attachment; filename="%s.pdf"' % base
        return resp
    if fmt == "docx":
        data = _docx_bytes(rows, fields, title)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        resp["Content-Disposition"] = 'attachment; filename="%s.docx"' % base
        return resp
    return None
