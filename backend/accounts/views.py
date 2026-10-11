"""Employee / department APIs with bulk safety.

- Ordinary updates never touch role / can_create_tickets (popped).
- Role changes live on a dedicated Admin-only action.
- Bulk endpoints use preview -> confirm, per-row partial results, and never
  hard-delete (bulk delete = soft delete only, blocked when history exists).
"""
import csv
import io

from django.db import transaction
from django.db.models import Count
from openpyxl import load_workbook
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Department, User
from accounts.serializers import (
    BulkEmployeeRowSerializer, DepartmentSerializer, UserCreateSerializer,
    UserSerializer,
)
from common.audit import log_action
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin


def _is_privileged(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support") or user.is_superuser))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def current_user(request):
    """Own profile for permission-aware UI (role, ticket-creation right).

    GET is read-only. PATCH accepts ONLY `receive_ticket_emails` and
    applies it to the caller themselves — there is no path here (or
    anywhere: role/bulk/import flows use fixed field sets) to change
    another user's preference or to mass-assign protected fields.
    """
    user = request.user
    if request.method == "PATCH":
        if "receive_ticket_emails" not in request.data:
            return Response(
                {"detail": "Only 'receive_ticket_emails' can be changed "
                           "here."}, status=400)
        value = request.data.get("receive_ticket_emails")
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1"):
                value = True
            elif lowered in ("false", "0"):
                value = False
        if not isinstance(value, bool):
            return Response(
                {"receive_ticket_emails": "Must be true or false."},
                status=400)
        user.receive_ticket_emails = value
        user.save(update_fields=["receive_ticket_emails"])
        log_action(actor=user, action="update", instance=user,
                   details={"receive_ticket_emails": value})
    data = UserSerializer(user).data
    data["receive_ticket_emails"] = user.receive_ticket_emails
    return Response(data)


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.annotate(
        member_count=Count("members")).all()
    serializer_class = DepartmentSerializer

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
        # Block deleting a department still referenced (explain + safe path).
        refs = {
            "members": obj.members.count(),
            "tickets": obj.tickets.count(),
        }
        if any(refs.values()):
            return Response(
                {"detail": "Department still referenced.",
                 "references": refs,
                 "hint": "Reassign members/tickets or deactivate instead."},
                status=409,
            )
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response(
                {"detail": "Confirmation required.",
                 "hint": f"Send {{\"confirm\": \"{pk}\", \"reason\": \"...\"}}"},
                status=400)
        obj = Department.all_objects.get(pk=pk)
        refs = {"members": obj.members.count(),
                "tickets": obj.tickets.count()}
        if any(refs.values()):
            return Response({"detail": "Blocked: references exist.",
                             "references": refs}, status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="accounts.Department", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})


def _parse_upload(file_obj):
    """Return list of dict rows from CSV or Excel."""
    name = (file_obj.name or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xltx")):
        wb = load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        header = [str(h or "").strip() for h in rows[0]]
        return [dict(zip(header, r)) for r in rows[1:] if any(r)]
    text = file_obj.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _employee_preview(rows):
    preview, errors = [], []
    seen = set()
    for i, raw in enumerate(rows, start=2):
        data = {k.strip(): (v.strip() if isinstance(v, str) else v)
                for k, v in raw.items() if k}
        ser = BulkEmployeeRowSerializer(data=data)
        if not ser.is_valid():
            errors.append({"row": i, "errors": ser.errors, "data": raw})
            continue
        eid = ser.validated_data["employee_id"]
        if eid in seen:
            errors.append({"row": i, "errors": {"employee_id": ["duplicate in file"]},
                           "data": raw})
            continue
        seen.add(eid)
        exists = User.objects.with_deleted().filter(employee_id=eid).first()
        preview.append({
            "row": i, "employee_id": eid,
            "exists": bool(exists),
            "is_deleted": bool(exists and exists.is_deleted),
            "would_create": not bool(exists),
            "data": ser.validated_data,
        })
    return preview, errors


def _flatten_message(value, limit=500):
    """Flatten serializer errors / reason strings to one short CSV-safe line.

    Only short server-generated text is ever returned; full row payloads,
    passwords, and secrets are never included (callers pass just the
    errors/reason, never the row data).
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


def _employee_report_rows(preview, ok, skipped, failed):
    """Build CSV rows from a bulk_import confirmation result.

    Keys for skipped/exception rows are recovered from the preview items
    (same execution, no re-query); validation failures read the key from
    the rejected row's employee_id field only — never the full payload.
    """
    row_of_key = {item["employee_id"]: item["row"] for item in preview}
    key_of_row = {item["row"]: item["employee_id"] for item in preview}
    rows = []
    for eid in ok:
        rows.append({"row": row_of_key.get(eid, ""), "key": eid,
                     "outcome": "successful", "message": "created"})
    for entry in skipped:
        entry = entry if isinstance(entry, dict) else {}
        num = entry.get("row", "")
        rows.append({"row": num, "key": key_of_row.get(num, ""),
                     "outcome": "skipped",
                     "message": _flatten_message(entry.get("reason", ""))})
    for entry in failed:
        if not isinstance(entry, dict):
            rows.append({"row": "", "key": "", "outcome": "failed",
                         "message": _flatten_message(entry)})
            continue
        num = entry.get("row", "")
        key = entry.get("employee_id", "") or ""
        if not key:
            data = entry.get("data")
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(k, str) and k.strip().lower() == \
                            "employee_id":
                        key = "" if v is None else str(v)
                        key = key.strip()
                        break
            if not key:
                key = key_of_row.get(num, "")
        rows.append({"row": num, "key": key, "outcome": "failed",
                     "message": _flatten_message(entry.get("errors", ""))})
    rows.sort(key=lambda d: (d["row"] if isinstance(d["row"], int)
                             else 10 ** 9))
    return rows


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        # NOTE: hard_delete + change_role carry their own
        # IsSystemAdmin action-level guard; never include them here.
        if self.action in ("create", "destroy",
                           "bulk_import", "bulk_update", "bulk_activate",
                           "bulk_delete"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        qs = User.objects.all()
        if not is_system_admin(self.request.user):
            qs = qs.filter(is_deleted=False)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(employee_id__icontains=q) | qs.filter(
                email__icontains=q)
        return qs

    def perform_create(self, serializer):
        # Only admins/managers reach here (permission above); IT Support may
        # create employees but never admins (downgrade silently + audit).
        role = serializer.validated_data.get("role", "employee")
        user = self.request.user
        if (getattr(user, "role", "") == "it_support" and
                role in ("system_admin", "it_manager")):
            serializer.validated_data["role"] = "employee"
        obj = serializer.save()
        log_action(actor=user, action="create", instance=obj,
                   details={"role": obj.role})
        from accounts.email_utils import send_verification_email
        try:
            send_verification_email(obj)
        except Exception:
            pass

    def perform_update(self, serializer):
        # Ordinary updates NEVER modify role / ticket-creation rights.
        serializer.validated_data.pop("role", None)
        serializer.validated_data.pop("can_create_tickets", None)
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        refs = {"tickets": obj.tickets_requested.count(),
                "assignments": obj.assignments_received.count()}
        if any(refs.values()):
            return Response(
                {"detail": "Employee has history. Prefer deactivation.",
                 "references": refs,
                 "hint": "Use bulk_deactivate instead of deletion."},
                status=409)
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[IsSystemAdmin])
    def change_role(self, request, pk=None):
        """Dedicated role/permission change (never part of bulk update)."""
        obj = self.get_object()
        role = request.data.get("role")
        if role not in dict(User.ROLE_CHOICES):
            return Response({"detail": "Invalid role."}, status=400)
        old = {"role": obj.role,
               "can_create_tickets": obj.can_create_tickets}
        obj.role = role
        if "can_create_tickets" in request.data:
            obj.can_create_tickets = bool(request.data["can_create_tickets"])
        obj.save(update_fields=["role", "can_create_tickets"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"old": old,
                            "new": {"role": role,
                                    "can_create_tickets": obj.can_create_tickets}})
        return Response(UserSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        if not _is_privileged(request.user):
            return Response({"detail": "Forbidden."}, status=403)
        obj = self.get_object()
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        log_action(actor=request.user, action="deactivate", instance=obj)
        return Response(UserSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        if not _is_privileged(request.user):
            return Response({"detail": "Forbidden."}, status=403)
        obj = self.get_object()
        obj.is_active = True
        obj.save(update_fields=["is_active"])
        log_action(actor=request.user, action="reactivate", instance=obj)
        return Response(UserSerializer(obj).data)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = User.objects.with_deleted().get(pk=pk)
        refs = {"tickets": obj.tickets_requested.count(),
                "assignments": obj.assignments_received.count(),
                "audit": obj.audit_actions.count()}
        if any(refs.values()):
            return Response({"detail": "Blocked: history exists.",
                             "references": refs,
                             "hint": "Prefer deactivation/soft deletion."},
                            status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="accounts.User", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})

    # ---- bulk endpoints: preview -> confirm, partial per-row results ----
    @action(detail=False, methods=["get", "post"])
    def bulk_import(self, request):
        if request.method == "GET":
            columns = ["employee_id", "email", "first_name",
                       "last_name", "phone", "job_title",
                       "home_department", "is_active"]
            if request.query_params.get("download") == "csv":
                # Downloadable CSV template: header row only, so importing
                # the file as-is creates nothing (no sample data to forget).
                # NOTE: the param is named "download", not "format": DRF
                # reserves ?format= for renderer selection and would 404.
                from django.http import HttpResponse
                resp = HttpResponse(content_type="text/csv")
                resp["Content-Disposition"] = (
                    'attachment; filename="employee_import_template.csv"')
                csv.writer(resp).writerow(columns)
                return resp
            return Response({
                "template_columns": columns,
                "matching_key": "employee_id",
            })
        upload = request.FILES.get("file")
        rows_data = request.data.get("rows")
        if upload:
            rows = _parse_upload(upload)
        elif rows_data:
            rows = rows_data if isinstance(rows_data, list) else []
        else:
            return Response({"detail": "Provide 'file' or 'rows'."},
                            status=400)
        preview, errors = _employee_preview(rows)
        if request.data.get("preview", True) in (True, "true", "1", 1):
            return Response({"preview": preview, "errors": errors,
                             "counts": {"ok": len(preview),
                                        "failed": len(errors)}})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required.",
                             "preview": preview, "errors": errors},
                            status=400)
        ok, failed, skipped = [], list(errors), []
        for item in preview:
            d = item["data"]
            try:
                with transaction.atomic():
                    dept = None
                    if d.get("home_department"):
                        dept = Department.objects.filter(
                            code=d["home_department"]).first() or \
                            Department.objects.filter(
                                name=d["home_department"]).first()
                    existing = User.objects.with_deleted().filter(
                        employee_id=item["employee_id"]).first()
                    if existing:
                        skipped.append({"row": item["row"], "reason":
                                                 "exists; use bulk_update"})
                        continue
                    user = User(
                        employee_id=item["employee_id"],
                        username=d.get("email") or item["employee_id"],
                        email=d.get("email") or f"{item['employee_id']}@local",
                        first_name=d.get("first_name", ""),
                        last_name=d.get("last_name", ""),
                        phone=d.get("phone", ""),
                        job_title=d.get("job_title", ""),
                        home_department=dept,
                        is_active=d.get("is_active", True),
                    )
                    user.set_unusable_password()
                    user.save()
                    log_action(actor=request.user, action="bulk_create",
                               instance=user)
                    ok.append(item["employee_id"])
            except Exception as exc:  # per-row partial failure
                failed.append({"row": item["row"], "errors": str(exc)})
        if request.query_params.get("download") == "csv":
            # Same executed import, CSV representation of the per-row
            # outcomes. JSON remains the default when absent.
            return _csv_report_response(
                "employee_import_report.csv",
                _employee_report_rows(preview, ok, skipped, failed))
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed,
                         "summary": {"ok": len(ok),
                                     "skipped": len(skipped),
                                     "failed": len(failed)}})

    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Bulk update keyed on employee_id. Never touches role/permissions."""
        rows = request.data.get("rows", [])
        preview = []
        for raw in rows:
            eid = raw.get("employee_id")
            exists = User.objects.with_deleted().filter(employee_id=eid).first()
            preview.append({"employee_id": eid, "exists": bool(exists),
                            "is_deleted": bool(exists and exists.is_deleted)})
        if request.data.get("preview", True) in (True, "true", "1", 1):
            return Response({"preview": preview,
                             "affected": len(preview)})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        allowed = {"email", "first_name", "last_name", "phone", "job_title",
                   "home_department", "is_active"}
        for raw in rows:
            try:
                with transaction.atomic():
                    obj = User.objects.filter(
                        employee_id=raw.get("employee_id")).first()
                    if not obj:
                        skipped.append({**raw, "reason": "not found"})
                        continue
                    changes = {k: v for k, v in raw.items() if k in allowed}
                    if "home_department" in changes:
                        code = changes.pop("home_department")
                        dept = Department.objects.filter(
                            code=code).first() if code else None
                        obj.home_department = dept
                    for k, v in changes.items():
                        setattr(obj, k, v)
                    obj.save()
                    log_action(actor=request.user, action="bulk_update",
                               instance=obj, details={"changes": changes})
                    ok.append(obj.employee_id)
            except Exception as exc:
                failed.append({"employee_id": raw.get("employee_id"),
                               "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed})

    @action(detail=False, methods=["post"])
    def bulk_activate(self, request):
        ids, activate = request.data.get("ids", []), request.data.get(
            "activate", True)
        if request.data.get("preview", True) in (True, "true", "1", 1):
            qs = User.objects.filter(id__in=ids)
            return Response({"preview": [u.employee_id for u in qs],
                             "affected": qs.count()})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed = [], []
        for pk in ids:
            try:
                with transaction.atomic():
                    obj = User.objects.get(pk=pk)
                    obj.is_active = bool(activate)
                    obj.save(update_fields=["is_active"])
                    log_action(
                        actor=request.user,
                        action="reactivate" if activate else "deactivate",
                        instance=obj)
                    ok.append(pk)
            except Exception as exc:
                failed.append({"id": pk, "errors": str(exc)})
        return Response({"successful": ok, "failed": failed})

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Bulk SOFT delete only. Blocked for users with history. Never hard."""
        ids = request.data.get("ids", [])
        objs = list(User.objects.filter(id__in=ids))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            blocked = [o.employee_id for o in objs
                       if o.tickets_requested.count() or
                       o.assignments_received.count()]
            return Response({"preview": [o.employee_id for o in objs],
                             "affected": len(objs), "blocked": blocked,
                             "note": "soft delete only; history rows block"})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, skipped, failed = [], [], []
        for obj in objs:
            try:
                with transaction.atomic():
                    if (obj.tickets_requested.count() or
                            obj.assignments_received.count()):
                        skipped.append({"id": obj.pk,
                                        "reason": "has history; deactivate"})
                        continue
                    obj.soft_delete(
                        by_user=request.user,
                        reason=request.data.get("reason", "bulk soft delete"))
                    log_action(actor=request.user, action="bulk_soft_delete",
                               instance=obj)
                    ok.append(obj.pk)
            except Exception as exc:
                failed.append({"id": obj.pk, "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed})
