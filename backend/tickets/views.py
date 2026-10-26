"""Ticket APIs: categories, tickets, notes, history, bulk, reports.

Visibility:
- System Admin / IT Manager / IT Support: operational scope (all active).
- Employee: own tickets + tickets for home department. Internal notes and
  privileged history hidden (separate permission-checked endpoints).
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.audit import log_action
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.models import (
    Ticket, TicketAttachment, TicketCategory, TicketHistory, TicketNote,
)
from tickets.serializers import (
    TicketAttachmentSerializer, TicketCategorySerializer,
    TicketHistorySerializer, TicketNoteSerializer, TicketSerializer,
)


def _can_manage_categories(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support") or user.is_superuser))


def _ticket_visible_qs(user):
    qs = Ticket.objects.select_related(
        "category", "requester", "assignee", "department").all()
    if is_system_admin(user) or getattr(user, "role", "") in ("it_manager",
                                                              "it_support"):
        return qs
    # Employee: own + home-department tickets.
    filt = Q(requester=user)
    if getattr(user, "home_department_id", None):
        filt |= Q(department_id=user.home_department_id)
    return qs.filter(filt)


#: Fields only IT staff may change (PERMISSIONS.md). Employees editing
#: tickets may resubmit current values but any *change* is rejected.
STAFF_ONLY_TICKET_FIELDS = ("assignee", "status", "priority", "category",
                            "resolution_notes")


#: Sortable list fields (strict allowlist — anything else falls back to
#: the default newest-first order). Priority sorts by severity, not
#: alphabetically. Every branch ends in a unique key so pages are stable.
_TICKET_ORDER_FIELDS = {"created_at", "priority", "status"}


def _apply_ticket_ordering(qs, raw):
    field = (raw or "").lstrip("-")
    if field not in _TICKET_ORDER_FIELDS:
        return qs.order_by("-created_at", "-id")
    desc = raw.startswith("-")
    if field == "priority":
        from django.db.models import Case, IntegerField, When
        qs = qs.annotate(_severity=Case(
            When(priority="low", then=0),
            When(priority="medium", then=1),
            When(priority="high", then=2),
            When(priority="critical", then=3),
            default=4, output_field=IntegerField()))
        key = "_severity"
    else:
        key = field
    head = f"-{key}" if desc else key
    tie = "-id" if desc else "id"
    return qs.order_by(head, tie)


def _is_ticket_staff(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support")
        or getattr(user, "is_superuser", False)))


def _reject_staff_only_changes(old, validated_data):
    """Raise 403 if validated data changes a staff-only field.

    `old` holds current DB values (FKs as ids). Unchanged resubmitted
    values (e.g. the edit form always posts priority/category) pass.
    """
    for field in STAFF_ONLY_TICKET_FIELDS:
        if field not in validated_data:
            continue
        new = validated_data[field]
        if field in ("assignee", "category"):
            new_id = new.pk if new is not None else None
            changed = new_id != old[field]
        else:
            changed = new != old[field]
        if changed:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Only IT staff can change assignee, status, priority, "
                "category, or resolution notes.")


def _write_history(ticket, actor, action, old=None, new=None, note=""):
    TicketHistory.objects.create(ticket=ticket, actor=actor, action=action,
                                 old_values=old or {}, new_values=new or {},
                                 note=note)


def _notify_user(recipient, actor, title, body, ticket):
    """Create an in-app notification for a ticket event.

    Rules (mirror the email pattern, never noisier):
    - Never notify the actor about their own action.
    - Never notify inactive/deleted users or empty recipients.
    - Bodies carry only requester-visible summary text; internal-note
      content must never be passed in (callers decide who may see what).
    - Created inline with history/audit (the established pattern), so the
      notification shares the row's fate in tests and in rolled-back
      requests; no background worker is used.
    """
    from common.models import Notification

    if recipient is None or getattr(recipient, "pk", None) is None:
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    return Notification.objects.create(
        recipient=recipient, title=title[:255], body=body or "",
        entity_type="tickets.Ticket", object_id=str(ticket.pk))


def _wants_ticket_email(person):
    """Ticket-event email opt-out check for one recipient object.

    Missing flag defaults to True so a lookup can never silently break
    ticket flows. Verification / password-reset mail never consults this.
    """
    return bool(getattr(person, "receive_ticket_emails", True))


class TicketCategoryViewSet(viewsets.ModelViewSet):
    queryset = TicketCategory.objects.annotate(
        ticket_count=Count("tickets")).all()
    serializer_class = TicketCategorySerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def perform_create(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="create", instance=obj)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        count = obj.tickets.count()
        if count:
            return Response(
                {"detail": f"Category still used by {count} ticket(s).",
                 "hint": "Reassign tickets or deactivate the category."},
                status=409)
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = TicketCategory.all_objects.get(pk=pk)
        if obj.tickets.count():
            return Response({"detail": "Blocked: tickets reference it."},
                            status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="tickets.TicketCategory",
                object_id=str(obj.pk), object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})


def _flatten_ticket_message(value, limit=500):
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


def _ticket_csv_report_response(filename, rows):
    from django.http import HttpResponse
    import csv
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(resp)
    writer.writerow(["row", "key", "outcome", "message"])
    for r in rows:
        writer.writerow([r.get("row", ""), r.get("key", ""),
                         r.get("outcome", ""), r.get("message", "")])
    return resp


def _ticket_report_rows(source_rows, ok, failed):
    first_row = {}
    for i, r in enumerate(source_rows, start=1):
        t = str(r.get("title", "")).strip() if isinstance(r, dict) else ""
        if t and t not in first_row:
            first_row[t] = i
    rows = []
    for entry in ok:
        entry = entry if isinstance(entry, dict) else {}
        key = entry.get("id", "")
        title = entry.get("title", "")
        rows.append({"row": entry.get("row", ""),
                     "key": key if key != "" else title,
                     "outcome": "successful",
                     "message": "created"})
    for entry in failed:
        if not isinstance(entry, dict):
            rows.append({"row": "", "key": "", "outcome": "failed",
                         "message": _flatten_ticket_message(entry)})
            continue
        title = ""
        if isinstance(entry.get("row"), int):
            pass
        data = entry.get("data")
        if isinstance(data, dict):
            title = str(data.get("title", "")).strip()
        if not title and isinstance(entry.get("errors"), dict):
            pass
        key = entry.get("asset_tag", "") or title
        rows.append({"row": entry.get("row", ""),
                     "key": key,
                     "outcome": "failed",
                     "message": _flatten_ticket_message(entry.get("errors", ""))})
    rows.sort(key=lambda d: (d["row"] if isinstance(d["row"], int)
                             else 10 ** 9))
    return rows


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer

    def get_permissions(self):
        # Bulk ticket mutation is staff-only work (every whitelisted
        # bulk field is staff-only). Single updates stay open so
        # employees can edit their own tickets, but staff-only *fields*
        # are guarded per-change in perform_update. Deletion (single +
        # bulk) is staff-only: employees cannot soft-delete tickets.
        if self.action in ("bulk_update", "destroy", "bulk_delete"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        qs = _ticket_visible_qs(self.request.user)
        p = self.request.query_params
        if p.get("q"):
            qs = qs.filter(title__icontains=p["q"]) | qs.filter(
                description__icontains=p["q"])
        if p.get("category"):
            qs = qs.filter(category_id=p["category"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("priority"):
            qs = qs.filter(priority=p["priority"])
        if p.get("department"):
            qs = qs.filter(department_id=p["department"])
        if p.get("assignee"):
            qs = qs.filter(assignee_id=p["assignee"])
        return _apply_ticket_ordering(qs, p.get("ordering"))

    def perform_create(self, serializer):
        user = self.request.user
        if not getattr(user, "can_create_tickets", True) and not is_system_admin(
                user) and getattr(user, "role", "") not in ("it_manager",
                                                            "it_support"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Ticket creation disabled for this user.")
        # Employees cannot choose an assignee at creation (staff-only, like
        # updates). Omitted/null stays valid. Checked before any save or
        # side effect.
        if (not _is_ticket_staff(user)
                and serializer.validated_data.get("assignee") is not None):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only IT staff can assign tickets.")
        dept = serializer.validated_data.get("department")
        if dept is None and getattr(user, "home_department_id", None):
            serializer.validated_data["department_id"] = user.home_department_id
        # Cross-department filing requires a reason (your guardrail).
        target = serializer.validated_data.get("department") or getattr(
            user, "home_department", None)
        if (target and getattr(user, "home_department_id", None)
                and target.pk != user.home_department_id
                and not serializer.validated_data.get("on_behalf_reason")):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"on_behalf_reason":
                                   "Required when filing for another department."})
        obj = None
        with transaction.atomic():
            obj = serializer.save(requester=user)
            _write_history(obj, user, "created", new={"status": "open"})
            log_action(actor=user, action="create", instance=obj)
            # In-app: the assignee learns they own it (the requester is the
            # actor, so they are never notified of their own action).
            _notify_user(obj.assignee, user,
                         f"Ticket #{obj.pk} assigned to you",
                         f"{obj.title}\nPriority: {obj.priority}", obj)
        # Email AFTER the transaction commits: failures stay swallowed (they
        # must never undo the creation) and no mail can go out for a
        # creation that later rolls back. Deliberately not on_commit():
        # callbacks never run under TestCase, breaking email tests.
        from accounts.email_utils import (
            send_ticket_notification, ticket_links,
        )
        try:
            fe, _ = ticket_links(obj.pk)
            if _wants_ticket_email(user):
                send_ticket_notification(
                    user.email, f"Ticket #{obj.pk} created: {obj.title}",
                    f"Your ticket was created.\nStatus: {obj.status}\n"
                    f"View: {fe}")
            if (obj.assignee and obj.assignee.email
                    and _wants_ticket_email(obj.assignee)):
                send_ticket_notification(
                    obj.assignee.email,
                    f"Ticket #{obj.pk} assigned to you",
                    f"{obj.title}\nPriority: {obj.priority}\nView: {fe}")
        except Exception:
            pass

    def perform_update(self, serializer):
        obj = self.get_object()
        old = {"status": obj.status, "priority": obj.priority,
               "category": obj.category_id, "assignee": obj.assignee_id,
               "resolution_notes": obj.resolution_notes}
        if not _is_ticket_staff(self.request.user):
            _reject_staff_only_changes(old, serializer.validated_data)
        new_status = serializer.validated_data.get("status")
        if new_status and not Ticket.can_transition(obj.status, new_status):
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"status": f"Invalid transition {obj.status} -> {new_status}."})
        # Stamp/clear the resolution timestamps on REAL transitions so the
        # single-ticket path matches bulk_update (which already stamps):
        # -> resolved sets resolved_at, -> closed sets closed_at, and a
        # reopen clears both. Same-status resubmits never touch them.
        status_changed = bool(new_status and new_status != old["status"])
        if status_changed:
            if new_status == "resolved":
                serializer.validated_data["resolved_at"] = timezone.now()
            elif new_status == "closed":
                serializer.validated_data["closed_at"] = timezone.now()
            elif new_status in ("reopened", "in_progress", "open"):
                serializer.validated_data["resolved_at"] = None
                serializer.validated_data["closed_at"] = None
        updated = None
        with transaction.atomic():
            updated = serializer.save()
            changes = {k: (old.get(k), getattr(updated, k if k != "category"
                                               else "category_id"))
                       for k in old}
            _write_history(updated, self.request.user, "updated",
                           old=old, new={k: str(v) for k, v in
                                         serializer.validated_data.items()})
            # In-app: the new assignee learns they own it (only on change).
            if (updated.assignee_id is not None
                    and updated.assignee_id != old["assignee"]):
                _notify_user(updated.assignee, self.request.user,
                             f"Ticket #{updated.pk} assigned to you",
                             f"{updated.title}\nPriority: {updated.priority}",
                             updated)
            status_changed = bool(new_status
                                  and new_status != old["status"])
            if status_changed:
                _write_history(updated, self.request.user, "status_change",
                               old={"status": old["status"]},
                               new={"status": new_status})
                log_action(actor=self.request.user, action="status_change",
                           instance=updated,
                           details={"from": old["status"], "to": new_status})
                # In-app: the requester learns the status (unless they made it).
                _notify_user(updated.requester, self.request.user,
                             f"Ticket #{updated.pk} status: {new_status}",
                             f"{updated.title}\nChanged {old['status']} -> "
                             f"{new_status}", updated)
            log_action(actor=self.request.user, action="update",
                       instance=updated, details={"changes": str(changes)})
        # Email AFTER the transaction commits: failures stay swallowed (they
        # must never undo the update) and no mail can go out for a change
        # that later rolls back. Deliberately not on_commit(): callbacks
        # never run under TestCase, which would silently break email tests.
        if new_status and new_status != old["status"]:
            from accounts.email_utils import (
                send_ticket_notification, ticket_links,
            )
            try:
                fe, _ = ticket_links(updated.pk)
                if (updated.requester and updated.requester.email
                        and _wants_ticket_email(updated.requester)):
                    send_ticket_notification(
                        updated.requester.email,
                        f"Ticket #{updated.pk} status: {new_status}",
                        f"{updated.title}\nChanged {old['status']} -> "
                        f"{new_status}\nView: {fe}")
            except Exception:
                pass

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Prefer archival for history rows; soft delete still allowed.
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        _write_history(obj, request.user, "soft_deleted",
                       note=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = Ticket.all_objects.get(pk=pk)
        refs = {"history": obj.history.count(), "notes": obj.notes.count(),
                "attachments": obj.attachments.count()}
        if any(refs.values()):
            return Response({"detail": "Blocked: history exists.",
                             "references": refs,
                             "hint": "Prefer archival/soft deletion."},
                            status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="tickets.Ticket", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "get":
            notes = ticket.notes.all()
            # Employees see only requester-visible updates on their tickets.
            if getattr(request.user, "role", "") == "employee":
                notes = notes.filter(is_internal=False)
            return Response(TicketNoteSerializer(notes, many=True).data)
        body = request.data.get("body", "").strip()
        if not body:
            return Response({"detail": "Body required."}, status=400)
        is_internal = bool(request.data.get("is_internal", True))
        if getattr(request.user, "role", "") == "employee" and is_internal:
            return Response({"detail": "Employees cannot add internal notes."},
                            status=403)
        note = TicketNote.objects.create(ticket=ticket, author=request.user,
                                         body=body, is_internal=is_internal)
        _write_history(ticket, request.user, "note_added",
                       new={"internal": is_internal}, note=body[:200])
        log_action(actor=request.user, action="note", instance=ticket)
        # In-app: requester-visible notes notify the requester and the
        # assignee (distinct, excluding the author). Internal notes notify
        # nobody: their content must never reach employees.
        if not is_internal:
            excerpt = body[:200]
            _notify_user(ticket.requester, request.user,
                         f"Ticket #{ticket.pk} update: {ticket.title}",
                         excerpt, ticket)
            if (ticket.assignee_id is not None
                    and (ticket.requester_id is None
                         or ticket.assignee_id != ticket.requester_id)):
                _notify_user(ticket.assignee, request.user,
                             f"Ticket #{ticket.pk} update: {ticket.title}",
                             excerpt, ticket)
        return Response(TicketNoteSerializer(note).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get", "post"])
    def bulk_create(self, request):
        if request.method == "GET":
            columns = ["title", "description", "category", "priority",
                       "department", "on_behalf_reason", "asset_tag",
                       "assignee_employee_id"]
            if request.query_params.get("download") == "csv":
                from django.http import HttpResponse
                import csv
                resp = HttpResponse(content_type="text/csv")
                resp["Content-Disposition"] = (
                    'attachment; filename="ticket_import_template.csv"')
                csv.writer(resp).writerow(columns)
                return resp
            return Response({"template_columns": columns,
                             "matching_key": "title"})
        """Create many tickets at once.

        Body: {"tickets": [{title, description, category, priority?,
        department?, on_behalf_reason?, asset?, assignee?}],
        "preview": true, "confirm": true}
        Same rules as single creation, applied per row: the requester is
        always the caller (payload requester keys are ignored), employees
        cannot set an assignee, assignees must be eligible, home-department
        defaulting and cross-department justification apply. Preview
        validates without writing; confirm executes each valid row in its
        own transaction (save + history + audit + notification), with
        emails sent afterwards so failures stay swallowed and can never
        undo or precede a commit. Partial success with per-row results.
        """
        user = self.request.user
        if not getattr(user, "can_create_tickets", True) and not is_system_admin(
                user) and getattr(user, "role", "") not in ("it_manager",
                                                            "it_support"):
            return Response(
                {"detail": "Ticket creation disabled for this user."},
                status=403)
        upload = request.FILES.get("file")
        if upload is not None:
            try:
                import csv
                import io
                from openpyxl import load_workbook
                name = (upload.name or "").lower()
                if name.endswith((".xlsx", ".xlsm")):
                    wb = load_workbook(upload, read_only=True, data_only=True)
                    ws = wb.active
                    if ws is None:
                        raise ValueError("workbook has no worksheets")
                    rows_raw = list(ws.iter_rows(values_only=True))
                    if not rows_raw:
                        raise ValueError("spreadsheet is empty; header row missing")
                    header = [str(h or "").strip() for h in rows_raw[0]]
                    rows = [dict(zip(header, r)) for r in rows_raw[1:]
                            if any(r)]
                    row_offset = 2
                else:
                    text = upload.read().decode("utf-8-sig")
                    reader = csv.DictReader(io.StringIO(text))
                    if not reader.fieldnames:
                        raise ValueError("CSV is empty; header row missing")
                    rows = list(reader)
                    row_offset = 2
                allowed = {"title", "description", "category", "priority",
                           "department", "on_behalf_reason", "asset_tag",
                           "assignee_employee_id",
                           # aliases normalized by _norm()
                           "department_code", "department_name", "asset",
                           "asset_id", "on_behalf", "assignee", "employee_id"}
                unknown = set()
                for r in rows:
                    if isinstance(r, dict):
                        for k in r:
                            if isinstance(k, str) and k not in allowed:
                                unknown.add(k)
                if unknown:
                    raise ValidationError({"file": "unknown columns: "
                                           + ", ".join(sorted(unknown))})
            except ValidationError:
                raise
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Could not parse bulk ticket upload %r", getattr(upload, "name", ""))
                raise ValidationError({"file": "Could not read the uploaded file. "
                                             "Expected a UTF-8 CSV or valid XLSX "
                                             "workbook with a header row."})
        else:
            rows_in = request.data.get("tickets", request.data.get("rows", []))
            rows = rows_in if isinstance(rows_in, list) else []
            row_offset = 1
        from accounts.models import User
        from assets.models import Asset
        from tickets.models import TicketCategory

        def _norm(raw):
            data = raw if isinstance(raw, dict) else {}
            out = {}
            title = data.get("title")
            if title is not None:
                out["title"] = str(title).strip()
            desc = data.get("description")
            if desc is not None:
                out["description"] = str(desc).strip()
            priority = data.get("priority")
            if priority not in (None, ""):
                out["priority"] = str(priority).strip().lower()
            cat = data.get("category")
            if cat not in (None, ""):
                if isinstance(cat, bool):
                    pass
                else:
                    try:
                        out["category"] = int(cat)
                    except (TypeError, ValueError):
                        tc = TicketCategory.objects.filter(
                            name=str(cat).strip()).first()
                        if tc is not None:
                            out["category"] = tc.pk
                        else:
                            out["category"] = str(cat).strip()
            dept = (data.get("department")
                    or data.get("department_code")
                    or data.get("department_name"))
            if dept not in (None, ""):
                from accounts.models import Department
                if isinstance(dept, int) or (
                        isinstance(dept, str) and dept.strip().isdigit()):
                    out["department"] = int(dept)
                else:
                    d = Department.objects.filter(
                        code=str(dept).strip()).first() or Department.objects.filter(
                        name=str(dept).strip()).first()
                    if d is not None:
                        out["department"] = d.pk
                    else:
                        out["department"] = str(dept).strip()
            reason = (data.get("on_behalf_reason")
                      or data.get("on_behalf"))
            if reason not in (None, ""):
                out["on_behalf_reason"] = str(reason).strip()
            asset = (data.get("asset") or data.get("asset_tag")
                     or data.get("asset_id"))
            if asset not in (None, ""):
                if isinstance(asset, int) or (
                        isinstance(asset, str) and asset.strip().isdigit()):
                    out["asset"] = int(asset)
                else:
                    a = Asset.objects.filter(
                        asset_tag=str(asset).strip()).first()
                    if a is not None:
                        out["asset"] = a.pk
                    else:
                        out["asset"] = str(asset).strip()
            assignee = (data.get("assignee")
                        or data.get("assignee_employee_id")
                        or data.get("employee_id"))
            if assignee not in (None, ""):
                if isinstance(assignee, int) or (
                        isinstance(assignee, str)
                        and assignee.strip().isdigit()):
                    out["assignee"] = int(assignee)
                else:
                    u = User.objects.filter(
                        employee_id=str(assignee).strip()).first()
                    if u is not None:
                        out["assignee"] = u.pk
                    else:
                        out["assignee"] = str(assignee).strip()
            return out

        rows = [_norm(r) for r in rows]
        if not rows:
            return Response({"detail": "Provide 'tickets' or a non-empty "
                                       "uploaded file."}, status=400)

        def _row_errors(data):
            """Dry-run validation mirroring perform_create guards."""
            ser = TicketSerializer(data=data)
            if not ser.is_valid():
                return ser.errors
            vd = ser.validated_data
            if (not _is_ticket_staff(user)
                    and vd.get("assignee") is not None):
                return {"assignee": "Only IT staff can assign tickets."}
            target = vd.get("department") or getattr(
                user, "home_department", None)
            if (target and getattr(user, "home_department_id", None)
                    and target.pk != user.home_department_id
                    and not vd.get("on_behalf_reason")):
                return {"on_behalf_reason":
                        "Required when filing for another department."}
            return None

        if request.data.get("preview", True) in (True, "true", "1", 1):
            preview, invalid = [], []
            for i, raw in enumerate(rows, start=row_offset):
                data = raw if isinstance(raw, dict) else {}
                errors = _row_errors(data)
                entry = {"row": i, "valid": errors is None,
                         "title": data.get("title", ""),
                         "errors": errors or {}}
                preview.append(entry)
                if errors:
                    invalid.append(entry)
            return Response({
                "preview": preview,
                "affected": len(preview) - len(invalid),
                "invalid": invalid,
                "note": "No tickets created. Re-run with confirm:true "
                        "to execute."})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        from accounts.email_utils import (
            send_ticket_notification, ticket_links,
        )
        ok, failed, skipped = [], [], []
        for i, raw in enumerate(rows, start=row_offset):
            data = raw if isinstance(raw, dict) else {}
            errors = _row_errors(data)
            if errors:
                failed.append({"row": i, "errors": errors})
                continue
            try:
                with transaction.atomic():
                    ser = TicketSerializer(data=data)
                    ser.is_valid(raise_exception=True)
                    vd = ser.validated_data
                    if vd.get("department") is None and getattr(
                            user, "home_department_id", None):
                        vd["department_id"] = user.home_department_id
                    obj = ser.save(requester=user)
                    _write_history(obj, user, "created",
                                   new={"status": "open"})
                    log_action(actor=user, action="create", instance=obj)
                    _notify_user(
                        obj.assignee, user,
                        f"Ticket #{obj.pk} assigned to you",
                        f"{obj.title}\nPriority: {obj.priority}", obj)
                try:
                    fe, _ = ticket_links(obj.pk)
                    if _wants_ticket_email(user):
                        send_ticket_notification(
                            user.email,
                            f"Ticket #{obj.pk} created: {obj.title}",
                            f"Your ticket was created.\nStatus: {obj.status}\n"
                            f"View: {fe}")
                    if (obj.assignee and obj.assignee.email
                            and _wants_ticket_email(obj.assignee)):
                        send_ticket_notification(
                            obj.assignee.email,
                            f"Ticket #{obj.pk} assigned to you",
                            f"{obj.title}\nPriority: {obj.priority}\n"
                            f"View: {fe}")
                except Exception:
                    pass
                ok.append({"row": i, "id": obj.pk, "title": obj.title})
            except Exception as exc:
                failed.append({"row": i, "errors": str(exc)})
        if request.query_params.get("download") == "csv":
            return _ticket_csv_report_response(
                "ticket_import_report.csv",
                _ticket_report_rows(rows, ok, failed))
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed,
                         "summary": {"ok": len(ok),
                                     "skipped": len(skipped),
                                     "failed": len(failed)}})

    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Explicit bulk ops: assign / priority / category / status.

        Body: {"ids": [...], "changes": {...}, "preview": true, "confirm": true}
        Each ticket validated individually; partial per-row results.
        """
        ids = request.data.get("ids", [])
        changes = request.data.get("changes", {})
        allowed = {"assignee", "priority", "category", "status"}
        unknown = set(changes) - allowed
        if unknown:
            return Response({"detail": f"Only {sorted(allowed)} allowed.",
                             "unknown": sorted(unknown)}, status=400)
        tickets = list(_ticket_visible_qs(request.user).filter(id__in=ids))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            invalid = []
            for t in tickets:
                if "status" in changes and not Ticket.can_transition(
                        t.status, changes["status"]):
                    invalid.append({"id": t.pk, "from": t.status,
                                    "to": changes["status"]})
            return Response({"preview": [{"id": t.pk, "title": t.title,
                                           "status": t.status} for t in tickets],
                             "affected": len(tickets),
                             "invalid_transitions": invalid,
                             "changes": changes})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        for t in tickets:
            try:
                with transaction.atomic():
                    old = {"status": t.status, "priority": t.priority,
                           "category": t.category_id, "assignee": t.assignee_id}
                    if "status" in changes and not Ticket.can_transition(
                            t.status, changes["status"]):
                        skipped.append({"id": t.pk,
                                        "reason": f"invalid {t.status}->{changes['status']}"})
                        continue
                    for field, val in changes.items():
                        if field == "category":
                            from tickets.models import TicketCategory as TC
                            cat = TC.objects.filter(pk=val).first()
                            if not cat or not cat.is_active:
                                raise ValueError("invalid/inactive category")
                            t.category = cat
                        elif field == "assignee":
                            from accounts.models import User
                            if not val:
                                t.assignee = None
                            else:
                                target = User.objects.filter(
                                    pk=val).first()
                                if target is None:
                                    raise ValueError(
                                        f"unknown assignee {val}")
                                if not target.is_active:
                                    raise ValueError(
                                        "assignee "
                                        f"{target.employee_id} is inactive")
                                t.assignee = target
                        else:
                            setattr(t, field, val)
                    # Same timestamp rule as the single-ticket path:
                    # -> resolved stamps resolved_at, -> closed stamps
                    # closed_at, reopen clears both; no-ops never touch
                    # them (mirrors perform_update).
                    target_status = changes.get("status")
                    if target_status and target_status != old["status"]:
                        if target_status == "resolved":
                            t.resolved_at = timezone.now()
                        elif target_status == "closed":
                            t.closed_at = timezone.now()
                        elif target_status in ("reopened", "in_progress",
                                               "open"):
                            t.resolved_at = None
                            t.closed_at = None
                    t.save()
                    _write_history(t, request.user, "bulk_change",
                                   old=old, new=dict(changes))
                    log_action(actor=request.user, action="bulk_update",
                               instance=t, details={"changes": changes})
                    # In-app: same recipients as single-ticket changes.
                    if ("assignee" in changes and t.assignee_id is not None
                            and t.assignee_id != old["assignee"]):
                        _notify_user(
                            t.assignee, request.user,
                            f"Ticket #{t.pk} assigned to you",
                            f"{t.title}\nPriority: {t.priority}", t)
                    if ("status" in changes
                            and changes["status"] != old["status"]):
                        _notify_user(
                            t.requester, request.user,
                            f"Ticket #{t.pk} status: {changes['status']}",
                            f"{t.title}\nChanged {old['status']} -> "
                            f"{changes['status']}", t)
                    ok.append(t.pk)
            except Exception as exc:
                failed.append({"id": t.pk, "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed,
                         "summary": {"ok": len(ok),
                                     "skipped": len(skipped),
                                     "failed": len(failed)}})

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Bulk SOFT delete only. Never hard-deletes (spec)."""
        ids = request.data.get("ids", [])
        tickets = list(_ticket_visible_qs(request.user).filter(id__in=ids))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            return Response({"preview": [{"id": t.pk, "title": t.title}
                                          for t in tickets],
                             "affected": len(tickets),
                             "note": "soft delete only; history preserved"})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed = [], []
        for t in tickets:
            try:
                with transaction.atomic():
                    t.soft_delete(
                        by_user=request.user,
                        reason=request.data.get("reason", "bulk soft delete"))
                    _write_history(t, request.user, "soft_deleted",
                                   note="bulk")
                    log_action(actor=request.user, action="bulk_soft_delete",
                               instance=t)
                    ok.append(t.pk)
            except Exception as exc:
                failed.append({"id": t.pk, "errors": str(exc)})
        return Response({"successful": ok, "failed": failed})


class TicketHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TicketHistory.objects.select_related("ticket", "actor").all()
    serializer_class = TicketHistorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        user = self.request.user
        if is_system_admin(user) or getattr(user, "role", "") == "it_manager":
            return qs
        if getattr(user, "role", "") == "it_support":
            if not user.has_perm("tickets.view_ticket_history"):
                return qs.none()
            return qs
        return qs.none()


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    queryset = TicketAttachment.objects.all()
    serializer_class = TicketAttachmentSerializer

    def get_queryset(self):
        # Only attachments on visible tickets (private files, no public URLs).
        visible_ids = _ticket_visible_qs(self.request.user).values("pk")
        return TicketAttachment.objects.filter(ticket_id__in=visible_ids)

    def perform_create(self, serializer):
        ticket = serializer.validated_data.get("ticket")
        if ticket and ticket.pk:
            visible = _ticket_visible_qs(self.request.user).filter(
                pk=ticket.pk).exists()
            if not visible:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Cannot attach to this ticket.")
        obj = serializer.save(
            uploaded_by=self.request.user,
            original_filename=getattr(
                serializer.validated_data.get("file"), "name", "")[:255])
        log_action(actor=self.request.user, action="create", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Soft delete keeps the physical file (record retained).
        obj.soft_delete(by_user=request.user, reason="attachment removed")
        log_action(actor=request.user, action="soft_delete", instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Permission-checked download. Never expose storage URLs directly."""
        import mimetypes
        import os

        from django.http import FileResponse
        obj = self.get_object()  # scoped to visible tickets above
        if obj.is_deleted:
            return Response({"detail": "Attachment is deleted."}, status=404)
        try:
            handle = obj.file.open("rb")
        except FileNotFoundError:
            return Response({"detail": "File missing from storage."},
                            status=410)
        name = obj.original_filename or os.path.basename(obj.file.name)
        resp = FileResponse(
            handle,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream")
        resp["Content-Disposition"] = f'attachment; filename="{name}"'
        return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def category_report(request):
    """Tickets-by-category aggregation (ORM, permission-aware, date filter).

    Returns per-category: total, open/unresolved, resolved/closed,
    high_count, critical_count, and urgent (= high + critical, kept for
    backward compatibility). Optional ?date_from & ?date_to filter
    created_at. Categories with zero matching tickets are omitted, as
    before.
    """
    from django.db.models import Count, Q
    from tickets.models import TicketCategory

    if getattr(request.user, "role", "") == "employee" and not (
            is_system_admin(request.user)):
        base = _ticket_visible_qs(request.user)
    else:
        base = Ticket.objects.all()
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        base = base.filter(created_at__gte=date_from)
    if date_to:
        base = base.filter(created_at__lte=date_to)
    open_statuses = ["open", "in_progress", "reopened"]
    closed_statuses = ["resolved", "closed"]
    rows = (TicketCategory.objects.filter(
        id__in=base.values("category_id")).annotate(
        total=Count("tickets", filter=Q(tickets__in=base)),
        open_count=Count("tickets", filter=Q(tickets__in=base,
                                             tickets__status__in=open_statuses)),
        closed_count=Count("tickets", filter=Q(
            tickets__in=base, tickets__status__in=closed_statuses)),
        high_count=Count("tickets", filter=Q(tickets__in=base,
                                             tickets__priority="high")),
        critical_count=Count("tickets", filter=Q(
            tickets__in=base, tickets__priority="critical")),
        urgent=Count("tickets", filter=Q(tickets__in=base,
                                         tickets__priority__in=["high",
                                                               "critical"])),
    ).values("id", "name", "total", "open_count", "closed_count",
             "high_count", "critical_count", "urgent"))
    return Response({"results": list(rows),
                     "filters": {"date_from": date_from, "date_to": date_to}})
