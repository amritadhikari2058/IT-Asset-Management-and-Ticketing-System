"""Asset APIs: categories, assets, assignment, history, bulk.

- Ordinary asset updates pop 'assigned_to' (no silent overwrite).
- Assignment changes are explicit + write Assignment + AssetHistory rows.
- Bulk delete = soft delete only, blocked when history exists.
"""
import csv
import io
import logging
from zipfile import BadZipFile

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from openpyxl import load_workbook
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from common.permissions import IsActiveAuthenticated
from rest_framework.response import Response

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
    Disposal, Maintenance, Vendor,
)
from common.attachment_security import safe_original_filename
from assets import reports
from assets import reports
from assets.serializers import (
    AssetAssignSerializer, AssetAttachmentSerializer,
    AssetCategorySerializer, AssetHistorySerializer, AssetSerializer,
    AssignmentSerializer, DisposalSerializer, MaintenanceSerializer,
    KnowledgeBaseArticleSerializer,
    KnowledgeBaseArticleCreateUpdateSerializer,
    KnowledgeBaseArticleRevisionSerializer,
    KnowledgeBaseCategorySerializer,
    KnowledgeBaseCategoryCreateUpdateSerializer,
    KnowledgeBaseFeedbackSerializer,
    KnowledgeBaseRejectSerializer,
    KnowledgeBaseRestoreSerializer,
    KnowledgeBaseReviewDecisionSerializer,
    KnowledgeBaseSubmitReviewSerializer,
    KnowledgeBaseTagSerializer,
    KnowledgeBaseTagCreateUpdateSerializer,
    VendorSerializer,
)
from assets import kb_services
from assets.models import (KnowledgeBaseArticle, KnowledgeBaseArticleRevision,
                           KnowledgeBaseCategory, KnowledgeBaseTag,
                           KnowledgeBaseFeedback)
from common.audit import log_action
from common.models import Notification
from common.notifications import notify_user
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.serializers import validate_attachment_file

logger = logging.getLogger(__name__)



def _can_manage(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support") or user.is_superuser))


def _history(asset, actor, action, old=None, new=None, note=""):
    AssetHistory.objects.create(asset=asset, actor=actor, action=action,
                                old_values=old or {}, new_values=new or {},
                                note=note)


def _validation_error_payload(exc):
    """Flatten a Django ValidationError into a DRF-friendly payload."""
    if hasattr(exc, "error_dict") and exc.error_dict:
        return exc.error_dict
    errors = getattr(exc, "error_list", None) or [str(exc)]
    return {"non_field_errors": [str(e) for e in errors]}


def _notify_assignee(recipient, actor, title, body, asset):
    """Create an in-app notification for an asset assignment event.

    Same conventions as ticket notifications: never notify the actor
    about their own action, never notify inactive/deleted users or empty
    recipients. In-app only — asset events never send email. Created
    inline so the row shares the mutation's fate on rollback.
    Deduplicated via notify_user(): equivalent active notifications are
    not created twice.
    """
    notify_user(
        recipient, "asset_assigned", title, body or "",
        entity_type="assets.Asset", object_id=str(asset.pk),
        actor=actor, post_commit=False,
    )


def _as_key(value):
    """Normalize a business key to a stripped string (never None)."""
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _validate_assignments(raw_rows):
    """Read-only per-row validation for bulk assignment. Never writes.

    Stricter than the single-assign endpoint on purpose: unknown assets or
    employees, ineligible employees, disallowed statuses, and conflicting
    active assignments are reported per row instead of silently applied.
    Rows already assigned go to ``skipped`` (return first); invalid rows
    go to ``failed``. Returns verdict dicts with ``valid`` + ``message``.
    """
    from accounts.models import User

    items = raw_rows if isinstance(raw_rows, list) else []
    seen_tags = set()
    results = []
    for pos, raw in enumerate(items, start=1):
        entry = raw if isinstance(raw, dict) else {}
        tag = _as_key(entry.get("asset_tag"))
        eid = _as_key(entry.get("employee_id"))
        base = {"row": pos, "asset_tag": tag, "employee_id": eid}
        if not tag:
            results.append({**base, "valid": False,
                            "message": "asset_tag required"})
            continue
        if not eid:
            results.append({**base, "valid": False,
                            "message": "employee_id required"})
            continue
        if tag in seen_tags:
            results.append({
                **base, "valid": False,
                "message": f"duplicate asset_tag {tag} in request"})
            continue
        seen_tags.add(tag)
        asset = Asset.objects.select_related("assigned_to").filter(
            asset_tag=tag).first()
        if asset is None:
            if Asset.all_objects.filter(asset_tag=tag).exists():
                msg = f"asset {tag} is deleted; restore it first"
            else:
                msg = f"asset {tag} not found"
            results.append({**base, "valid": False, "message": msg})
            continue
        user = User.objects.filter(employee_id=eid).first()
        if user is None:
            if User.objects.with_deleted().filter(
                    employee_id=eid).exists():
                msg = f"employee {eid} is deleted"
            else:
                msg = f"employee {eid} not found"
            results.append({**base, "valid": False, "message": msg})
            continue
        if not user.is_active:
            results.append({**base, "valid": False,
                            "message": f"employee {eid} is inactive"})
            continue
        if asset.assigned_to_id is not None:
            current = (asset.assigned_to.employee_id
                       if asset.assigned_to else "?")
            results.append({
                **base, "valid": False, "conflict": True,
                "message": f"already assigned to {current}; "
                           "return it first",
                "asset_id": asset.pk, "user_id": user.pk})
            continue
        if asset.status != "available":
            results.append({
                **base, "valid": False,
                "message": f"asset status is '{asset.status}'; only "
                           "'available' assets can be assigned"})
            continue
        note = entry.get("note", "")
        results.append({**base, "valid": True, "message": "",
                        "asset_id": asset.pk, "user_id": user.pk,
                        "note": note if isinstance(note, str) else ""})
    return results


def _public_assignment_row(verdict):
    return {k: verdict.get(k, "") for k in
            ("row", "asset_tag", "employee_id", "valid", "message")}


def _flatten_message(value, limit=500):
    """Flatten error details to one short CSV-safe line.

    Only short server-generated text is ever returned; full row payloads
    are never included (callers pass just the errors/reason, never rows).
    """
    if isinstance(value, dict):
        parts = []
        for field, errs in value.items():
            if isinstance(errs, (list, tuple)):
                errs = "; ".join(str(e) for e in errs)
            parts.append(f"{field}: {errs}")
        text = "; ".join(parts)
    elif value is None:
        text = ""
    else:
        text = str(value)
    return " ".join(text.split())[:limit]


def _csv_report_response(filename, rows):
    """Downloadable per-row outcome report: row,key,outcome,message."""
    from django.http import HttpResponse
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(resp)
    writer.writerow(["row", "key", "outcome", "message"])
    for r in rows:
        writer.writerow([r.get("row", ""), r.get("key", ""),
                         r.get("outcome", ""), r.get("message", "")])
    return resp


def _asset_report_rows(ok, skipped, failed):
    """Build CSV rows from per-row confirmation results."""
    rows = [
        {"row": item["row"], "key": item["asset_tag"],
         "outcome": "successful", "message": "created"}
        for item in ok
    ]
    for entry in skipped:
        entry = entry if isinstance(entry, dict) else {}
        rows.append({"row": entry.get("row", ""),
                     "key": entry.get("asset_tag", ""),
                     "outcome": "skipped",
                     "message": _flatten_message(entry.get("reason", ""))})
    for entry in failed:
        if not isinstance(entry, dict):
            rows.append({"row": "", "key": "", "outcome": "failed",
                         "message": _flatten_message(entry)})
            continue
        key = entry.get("asset_tag", "") or ""
        if not key:
            data = entry.get("row")
            if isinstance(data, dict):
                key = str(data.get("asset_tag", "")).strip()
        rows.append({"row": entry.get("row", "") if not isinstance(
                        entry.get("row"), dict) else "", "key": key,
                     "outcome": "failed",
                     "message": _flatten_message(entry.get("errors", ""))})
    rows.sort(key=lambda d: (d["row"] if isinstance(d["row"], int)
                             else 10 ** 9))
    return rows


ASSET_IMPORT_FIELDS = {
    "asset_tag", "name", "category", "serial_number", "status",
    "department", "location", "description", "purchase_date",
    "warranty_expiry", "purchase_cost",
}


def _asset_import_batch_lookup(row_batch):
    from accounts.models import Department

    asset_tags, serials, category_names = set(), set(), set()
    department_refs, department_ids = set(), set()
    for _, row in row_batch:
        if not isinstance(row, dict):
            continue
        tag = str(row.get("asset_tag", "")).strip()
        serial = str(row.get("serial_number") or "").strip()
        category = str(row.get("category") or "").strip()
        if tag:
            asset_tags.add(tag)
        if serial:
            serials.add(serial)
        if category:
            category_names.add(category)
        department = row.get("department")
        if department not in (None, ""):
            department_refs.add(str(department))
            try:
                department_ids.add(int(department))
            except (TypeError, ValueError):
                pass

    existing_tags, existing_serials = set(), set()
    if asset_tags or serials:
        query = Q()
        if asset_tags:
            query |= Q(asset_tag__in=asset_tags)
        if serials:
            query |= Q(serial_number__in=serials)
        for tag, serial in Asset.all_objects.filter(query).values_list(
                "asset_tag", "serial_number"):
            if tag in asset_tags:
                existing_tags.add(tag)
            if serial in serials:
                existing_serials.add(serial)

    categories = {}
    if category_names:
        categories = {
            category.name: category
            for category in AssetCategory.objects.filter(
                name__in=category_names)
        }

    departments_by_code, departments_by_name, departments_by_id = {}, {}, {}
    department_query = Q()
    if department_refs:
        department_query |= Q(code__in=department_refs)
        department_query |= Q(name__in=department_refs)
    if department_ids:
        department_query |= Q(pk__in=department_ids)
    if department_refs or department_ids:
        for department in Department.objects.filter(department_query):
            departments_by_code[department.code] = department
            departments_by_name[department.name] = department
            departments_by_id[department.pk] = department

    return (existing_tags, existing_serials, categories,
            departments_by_code, departments_by_name, departments_by_id)


def _iter_asset_import_rows(rows):
    from common.import_stream import batches

    for row_batch in batches(enumerate(rows, start=2)):
        lookups = _asset_import_batch_lookup(row_batch)
        for row_number, row in row_batch:
            yield row_number, row, lookups



def _positive_pk_param(raw):
    """Parse a query-string id into a positive int, or None when malformed.

    List filters must never pass an arbitrary string to ``filter()`` (that
    raises ValueError and yields a 500). Callers treat None as "no rows".
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _asset_visible_qs(user):
    """Assets visible to the user (private files are exactly as visible as
    their asset — never more).

    IT staff / admins see the operational scope. Employees see only assets
    assigned to them or in their home department — mirroring ticket
    visibility — so they cannot enumerate or download other employees'
    assets and attachments (IDOR protection).
    """
    if not (user and getattr(user, "is_authenticated", False)
            and getattr(user, "is_active", True)):
        return Asset.objects.none()
    role = getattr(user, "role", "")
    if role not in ("system_admin", "it_manager", "it_support",
                    "employee") and not getattr(user, "is_superuser", False):
        return Asset.objects.none()
    qs = Asset.objects.select_related(
        "category", "assigned_to", "department").all()
    if is_system_admin(user) or role in ("it_manager", "it_support"):
        return qs
    filt = Q(assigned_to=user)
    if getattr(user, "home_department_id", None):
        filt |= Q(department_id=user.home_department_id)
    return qs.filter(filt)


#: Sortable list fields (strict allowlist — anything else falls back to
#: tag order). Every branch ends in a unique key so pages are stable.
_ASSET_ORDER_FIELDS = {"asset_tag", "name", "status"}


def _apply_asset_ordering(qs, raw):
    field = (raw or "").lstrip("-")
    if field not in _ASSET_ORDER_FIELDS:
        return qs.order_by("asset_tag", "id")
    desc = raw.startswith("-")
    head = f"-{field}" if desc else field
    tie = "-id" if desc else "id"
    return qs.order_by(head, tie)



def _history_maintenance(maintenance, actor, action, old=None, new=None,
                         note=""):
    AssetHistory.objects.create(
        asset=maintenance.asset, actor=actor, action=action,
        old_values=old or {}, new_values=new or {}, note=note)


def _notify_maintenance(maintenance, actor, old=None):
    """In-app notification for maintenance events.

    Notifies the assigned technician (and the actor is never notified of
    their own action). Completion also notifies the asset's current holder.
    Deduplicated via notify_user(): equivalent active notifications are
    not created twice.
    """
    from django.utils import timezone

    recipient = maintenance.assigned_to
    if (recipient is None or getattr(recipient, "pk", None) is None
            or not getattr(recipient, "is_active", True)
            or getattr(recipient, "is_deleted", False)):
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    status = maintenance.status
    title = f"Maintenance: {maintenance.title}"
    if status == "in_progress":
        body = f"{maintenance.asset.asset_tag} maintenance started."
    elif status == "completed":
        body = f"{maintenance.asset.asset_tag} maintenance completed."
    elif status == "overdue":
        body = f"{maintenance.asset.asset_tag} maintenance is overdue."
    else:
        body = f"{maintenance.asset.asset_tag} maintenance scheduled for " \
               f"{maintenance.scheduled_date:%Y-%m-%d}."
    notify_user(
        recipient, "maintenance_event", title, body,
        entity_type="assets.Maintenance", object_id=str(maintenance.pk),
        actor=actor, post_commit=False,
    )
    # Also notify the current asset holder when maintenance completes.
    if (status == "completed" and maintenance.asset.assigned_to_id
            and maintenance.asset.assigned_to_id != recipient.pk):
        holder = maintenance.asset.assigned_to
        notify_user(
            holder, "maintenance_event",
            f"Asset under maintenance: {maintenance.asset.asset_tag}",
            f"Your assigned asset is undergoing maintenance: "
            f"{maintenance.title}.",
            entity_type="assets.Asset", object_id=str(maintenance.asset.pk),
            actor=actor, post_commit=False,
        )



def _history_disposal(disposal, actor, action, old=None, new=None, note=""):
    AssetHistory.objects.create(
        asset=disposal.asset, actor=actor, action=action,
        old_values=old or {}, new_values=new or {}, note=note)


def _notify_disposal(disposal, actor, old=None):
    """In-app notification for disposal events."""
    recipient = disposal.responsible_person
    if (recipient is None or getattr(recipient, "pk", None) is None
            or not getattr(recipient, "is_active", True)
            or getattr(recipient, "is_deleted", False)):
        recipient = disposal.created_by
    if (recipient is None or getattr(recipient, "pk", None) is None
            or not getattr(recipient, "is_active", True)
            or getattr(recipient, "is_deleted", False)):
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    status = disposal.approval_status
    title = f"Disposal: {disposal.asset.asset_tag}"
    if status == "approved":
        body = f"Disposal of {disposal.asset.asset_tag} approved."
    elif status == "rejected":
        body = f"Disposal of {disposal.asset.asset_tag} rejected."
    elif disposal.is_completed:
        body = f"Disposal of {disposal.asset.asset_tag} completed."
    else:
        body = f"Disposal of {disposal.asset.asset_tag} pending approval."
    notify_user(
        recipient, "disposal_event", title, body,
        entity_type="assets.Disposal", object_id=str(disposal.pk),
        actor=actor, post_commit=False,
    )


def _record_disposal_decision(disposal, actor, old_status):
    """Apply an approval decision and write the decision trail.

    Shared by the ``approve``/``reject`` actions and the generic update path
    so both produce the same approver metadata, asset history, audit entry and
    notification. Returns True when the status actually changed.
    """
    if disposal.approval_status == old_status:
        return False
    from django.utils import timezone
    status_now = disposal.approval_status
    if status_now == "approved":
        disposal.approver = actor
        disposal.approved_at = timezone.now()
        history_action, audit_action = "approved", "approve"
    elif status_now == "rejected":
        disposal.approver = actor
        disposal.approved_at = None
        history_action, audit_action = "rejected", "reject"
    else:
        # Reverting to pending withdraws the decision: no approver remains.
        disposal.approver = None
        disposal.approved_at = None
        history_action, audit_action = "pending", "reset_to_pending"
    disposal.save(update_fields=["approval_status", "approver",
                                 "approved_at", "updated_at"])
    _history_disposal(disposal, actor, history_action,
                      new={"approval_status": status_now})
    log_action(actor=actor, action=audit_action, instance=disposal,
               details={"asset": disposal.asset.asset_tag})
    _notify_disposal(disposal, actor)
    return True


def _complete_disposal(disposal, actor):
        """Mark an approved disposal complete and dispose the asset.

        Clears the holder, closes any open assignment, sets asset status to
        disposed, and records history + audit. Idempotent.
        """
        from django.db import transaction
        from django.utils import timezone
        if disposal.is_completed:
            return disposal
        asset = disposal.asset
        with transaction.atomic():
            # Serialize concurrent mutation of this asset (row lock on
            # PostgreSQL) so a concurrent assign()/return_asset() cannot
            # interleave between closing the open assignment and flipping
            # status to disposed.
            asset = Asset.objects.select_for_update().get(pk=asset.pk)
            # Resolve any open assignment before disposing.
            for open_a in asset.assignments.filter(
                    returned_at__isnull=True):
                open_a.returned_at = timezone.now()
                open_a.save(update_fields=["returned_at"])
            old = {"status": asset.status, "assigned_to": asset.assigned_to_id}
            asset.assigned_to = None
            asset.status = "disposed"
            asset.save(update_fields=["assigned_to", "status", "updated_at"])
            _history_disposal(disposal, actor, "completed",
                              old={"asset_status": old["status"],
                                   "asset_holder": old["assigned_to"]},
                              new={"asset_status": "disposed",
                                   "asset_holder": None})
            log_action(actor=actor, action="disposal",
                       instance=asset,
                       details={"disposal_id": disposal.pk,
                                "method": disposal.disposal_method,
                                "value": str(disposal.disposal_value)
                                if disposal.disposal_value is not None
                                else None})
            disposal.disposal_date = timezone.now()
            disposal.save(update_fields=["disposal_date", "updated_at"])
            _history_disposal(disposal, actor, "disposal_date_set",
                              new={"disposal_date": str(disposal.disposal_date)})
            _notify_disposal(disposal, actor)
        return disposal



