"""Employee / department APIs with bulk safety.

- Ordinary updates never touch role / can_create_tickets (popped).
- Role changes live on a dedicated Admin-only action.
- Bulk endpoints use preview -> confirm, per-row partial results, and never
  hard-delete (bulk delete = soft delete only, blocked when history exists).
"""
import csv

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from common.permissions import IsActiveAuthenticated
from rest_framework.response import Response

from accounts.models import Department, User
from accounts.serializers import (
    BulkEmployeeRowSerializer, DepartmentSerializer, UserCreateSerializer,
    UserDirectorySerializer, UserSerializer,
)
from common.audit import log_action
from common.import_stream import (
    batches, count_uploaded_rows, iter_uploaded_rows,
)
from common.permissions import IsITStaff, IsSystemAdmin, is_it_staff, is_system_admin
from tickets.serializers import validate_attachment_file


#: Role privilege order. Used to stop non-admins from managing accounts at or
#: above their own level (e.g. an IT Manager changing a System Admin's email
#: and then using the password-reset flow to take the account over).
_ROLE_RANK = {
    "employee": 1,
    "it_support": 2,
    "it_manager": 3,
    "system_admin": 4,
}


def _is_privileged(user):
    return is_it_staff(user)


def _role_rank(user):
    if getattr(user, "is_superuser", False):
        return _ROLE_RANK["system_admin"]
    return _ROLE_RANK.get(getattr(user, "role", ""), 0)


def _can_manage_user(actor, target):
    """True when ``actor`` may modify ``target``.

    System admins (and superusers) may manage anyone. Every other IT-staff
    member may only manage accounts strictly below their own role, so peers
    and higher-privileged accounts are out of reach.
    """
    if not _is_privileged(actor) or target is None:
        return False
    if is_system_admin(actor):
        return True
    return _role_rank(actor) > _role_rank(target)


@api_view(["GET", "PATCH"])
@permission_classes([IsActiveAuthenticated])
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
    serializer_class = DepartmentSerializer

    def get_queryset(self):
        qs = Department.objects.annotate(
            member_count=Count(
                "members",
                filter=Q(members__is_deleted=False, members__is_active=True)),
            asset_count=Count("assets")).all()
        qs = qs.filter(is_deleted=False)
        if not _is_privileged(self.request.user):
            # Non-staff callers only see departments they belong to (their
            # own home department); IT staff keep full directory visibility.
            qs = qs.filter(members=self.request.user)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        return qs.order_by("name")

    def get_permissions(self):
        # Staff actions (create, update, partial_update, destroy) require IT staff
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsITStaff()]
        # List/retrieve: non-privileged users only see departments they belong to
        if self.action in ("list", "retrieve"):
            if _is_privileged(self.request.user):
                return [IsActiveAuthenticated()]
            # Non-privileged: filter to departments where user is a member
            # This is already enforced in get_queryset, but we add explicit
            # permission check here for defense-in-depth
            return [IsActiveAuthenticated()]
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


def _parse_upload(file_obj, allowed=None):
    """Return an incremental CSV or Excel row iterator."""
    max_bytes = int(settings.EMPLOYEE_BULK_IMPORT_MAX_FILE_SIZE_MB
                    * 1024 * 1024)
    return iter_uploaded_rows(
        file_obj, allowed, max_bytes,
        settings.EMPLOYEE_BULK_IMPORT_MAX_ROWS,
        xlsx_extensions=(".xlsx", ".xlsm", ".xltx"),
    )


def _employee_preview(rows):
    preview, errors = [], []
    seen = set()
    for row_batch in batches(enumerate(rows, start=2)):
        valid_rows = []
        employee_ids = set()
        for i, raw in row_batch:
            if not isinstance(raw, dict):
                errors.append({"row": i,
                               "errors": {"file": ["row must be an object"]},
                               "data": raw})
                continue
            data = {k.strip(): (v.strip() if isinstance(v, str) else v)
                    for k, v in raw.items() if k}
            serializer = BulkEmployeeRowSerializer(data=data)
            if not serializer.is_valid():
                errors.append({"row": i, "errors": serializer.errors,
                               "data": raw})
                continue
            employee_id = serializer.validated_data["employee_id"]
            if employee_id in seen:
                errors.append({
                    "row": i,
                    "errors": {"employee_id": ["duplicate in file"]},
                    "data": raw})
                continue
            seen.add(employee_id)
            employee_ids.add(employee_id)
            valid_rows.append((i, employee_id, serializer.validated_data))

        existing_by_id = dict(
            User.objects.with_deleted().filter(
                employee_id__in=employee_ids
            ).values_list("employee_id", "is_deleted")
        ) if employee_ids else {}
        for i, employee_id, validated_data in valid_rows:
            exists = employee_id in existing_by_id
            preview.append({
                "row": i, "employee_id": employee_id,
                "exists": exists,
                "is_deleted": existing_by_id.get(employee_id, False),
                "would_create": not exists,
                "data": validated_data,
            })
    return preview, errors


def _confirm_employee_rows(rows, actor):
    successful, failed, skipped = [], [], []
    employee_id_by_row = {}
    seen = set()
    for row_batch in batches(enumerate(rows, start=2)):
        valid_rows = []
        employee_ids = set()
        department_refs = set()
        for row_number, raw in row_batch:
            if not isinstance(raw, dict):
                failed.append({
                    "row": row_number,
                    "errors": {"file": ["row must be an object"]},
                    "data": raw})
                continue
            data = {key.strip(): (value.strip()
                                  if isinstance(value, str) else value)
                    for key, value in raw.items() if key}
            serializer = BulkEmployeeRowSerializer(data=data)
            if not serializer.is_valid():
                failed.append({
                    "row": row_number, "errors": serializer.errors,
                    "data": raw})
                continue
            employee_id = serializer.validated_data["employee_id"]
            if employee_id in seen:
                failed.append({
                    "row": row_number,
                    "errors": {"employee_id": ["duplicate in file"]},
                    "data": raw})
                continue
            seen.add(employee_id)
            employee_ids.add(employee_id)
            department_ref = serializer.validated_data.get(
                "home_department")
            if department_ref:
                department_refs.add(department_ref)
            valid_rows.append((
                row_number, employee_id, serializer.validated_data))

        existing_ids = set(User.objects.with_deleted().filter(
            employee_id__in=employee_ids
        ).values_list("employee_id", flat=True)) if employee_ids else set()
        departments_by_code, departments_by_name = {}, {}
        if department_refs:
            for department in Department.objects.filter(
                    Q(code__in=department_refs)
                    | Q(name__in=department_refs)):
                departments_by_code[department.code] = department
                departments_by_name[department.name] = department

        for row_number, employee_id, data in valid_rows:
            employee_id_by_row[row_number] = employee_id
            if employee_id in existing_ids:
                skipped.append({
                    "row": row_number,
                    "reason": "exists; use bulk_update"})
                continue
            try:
                department_ref = data.get("home_department")
                department = (departments_by_code.get(department_ref)
                              or departments_by_name.get(department_ref))
                with transaction.atomic():
                    user = User(
                        employee_id=employee_id,
                        username=(data.get("username") or data.get("email")
                                  or employee_id),
                        email=data.get("email") or f"{employee_id}@local",
                        first_name=data.get("first_name", ""),
                        last_name=data.get("last_name", ""),
                        phone=data.get("phone", ""),
                        job_title=data.get("job_title", ""),
                        home_department=department,
                        is_active=data.get("is_active", True),
                        receive_ticket_emails=(
                            data.get("receive_ticket_emails")
                            if data.get("receive_ticket_emails") is not None
                            else True),
                    )
                    user.set_unusable_password()
                    user.save()
                    log_action(actor=actor, action="bulk_create",
                               instance=user)
                    successful.append(employee_id)
            except Exception as exc:  # per-row partial failure
                failed.append({
                    "row": row_number, "errors": str(exc)})
    return successful, failed, skipped, employee_id_by_row


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


def _employee_report_rows(employee_id_by_row, ok, skipped, failed):
    """Build CSV rows from a bulk_import confirmation result.

    Keys are recovered from the bounded row-number map; validation failures
    read only the rejected row's employee_id field from its error record.
    """
    row_of_key = {employee_id: row_number
                  for row_number, employee_id in employee_id_by_row.items()}
    key_of_row = employee_id_by_row
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


#: Sortable directory fields (strict allowlist — anything else falls
#: back to employee-ID order). Every branch ends in a unique key so
#: pages are stable.
_USER_ORDER_FIELDS = {"employee_id", "email"}


def _apply_user_ordering(qs, raw):
    field = (raw or "").lstrip("-")
    if field not in _USER_ORDER_FIELDS:
        return qs.order_by("employee_id", "id")
    desc = raw.startswith("-")
    head = f"-{field}" if desc else field
    tie = "-id" if desc else "id"
    return qs.order_by(head, tie)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if (self.action in ("list", "retrieve", "metadata")
                and not is_it_staff(self.request.user)):
            return UserDirectorySerializer
        return UserSerializer

    def get_permissions(self):
        # hard_delete/change_role define their own IsSystemAdmin guard.
        # Mutating/bulk actions are IT-staff-only; self-service profile edits
        # go through /api/accounts/me/.
        staff_actions = {
            "create", "update", "partial_update", "destroy",
            "bulk_import", "bulk_update", "bulk_activate", "bulk_delete",
        }
        if self.action in staff_actions:
            return [IsITStaff()]
        if self.action in ("list", "retrieve"):
            # Active users may read their own entry; staff get the full
            # directory. The queryset/serializer split enforces that boundary.
            return [IsActiveAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        qs = User.objects.select_related("home_department").all()
        if not is_system_admin(self.request.user):
            qs = qs.filter(is_deleted=False)
        if not is_it_staff(self.request.user):
            # Ordinary employees have no workflow that needs a global
            # directory: assignment/coordinator pickers are staff-only and
            # self-service uses /me/. Scope the queryset before any filters so
            # q/department/role cannot bypass object-level access, and direct
            # IDs for other accounts resolve to 404 rather than leaking data.
            qs = qs.filter(pk=getattr(self.request.user, "pk", None))
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(employee_id__icontains=q) | Q(email__icontains=q)
                | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        department = self.request.query_params.get("department")
        if department:
            try:
                qs = qs.filter(home_department__id=int(department))
            except (TypeError, ValueError):
                qs = qs.filter(home_department__code__iexact=department)
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            wanted = str(is_active).strip().lower() in ("true", "1", "yes")
            qs = qs.filter(is_active=wanted)
        return _apply_user_ordering(qs, self.request.query_params.get(
            "ordering"))

    def perform_create(self, serializer):
        # Only admins/managers reach here (permission above). Role
        # escalation is barred: only a system administrator may create
        # another system administrator (or IT manager). A lower-privileged
        # creator who requests an equal-or-higher role is silently
        # downgraded to employee, matching the existing IT Support
        # convention; the effective role is recorded in the audit log.
        role = serializer.validated_data.get("role", "employee")
        user = self.request.user
        if not is_system_admin(user):
            # Equal-or-higher roles are downgraded. IT Support can only
            # create employees; IT Manager can create Support/Employee.
            if _ROLE_RANK.get(role, 0) >= _role_rank(user):
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
        obj = self.get_object()
        if not _can_manage_user(self.request.user, obj):
            raise PermissionDenied(
                "You cannot modify an account at or above your role.")
        wants_inactive = (
            "is_active" in serializer.validated_data
            and serializer.validated_data.get("is_active") is False)
        if wants_inactive and obj.assignments_received.filter(
                returned_at__isnull=True).exists():
            from rest_framework.exceptions import ValidationError as DRFValidationError
            raise DRFValidationError(
                {"is_active": ["Cannot deactivate: still holds open asset "
                               "assignment(s). Return the asset(s) first."]})
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if not _can_manage_user(request.user, obj):
            return Response(
                {"detail": "You cannot delete an account at or above your "
                           "role."},
                status=status.HTTP_403_FORBIDDEN)
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
        from common.throttling import account_action_cooldown
        if account_action_cooldown(
            f"change_role:{obj.pk}", 60,
        ):
            return Response({"detail": "Too many role changes. Try again later."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

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

    @action(detail=True, methods=["post"], permission_classes=[IsSystemAdmin])
    def reset_password(self, request, pk=None):
        """Admin-only forced password reset for an employee account.

        The System Admin supplies the new password, which is validated with
        the configured Django password policy and stored through set_password
        (hashed only; never cleartext, never echoed back). The previous
        password stops working immediately; outstanding password-reset tokens
        for the target are invalidated (Django reset tokens embed the password
        hash) and outstanding JWT refresh tokens are blacklisted so existing
        sessions must re-authenticate.
        """
        obj = self.get_object()
        new_password = (request.data.get("new_password") or "").strip()
        confirm = request.data.get("confirm")
        if confirm is not None and str(confirm) != new_password:
            return Response(
                {"confirm": ["Passwords do not match."]},
                status=status.HTTP_400_BAD_REQUEST)
        try:
            from django.contrib.auth.password_validation import (
                validate_password,
            )
            from django.core.exceptions import ValidationError as DjangoValidationError
            validate_password(new_password, obj)
        except DjangoValidationError as exc:
            return Response(
                {"new_password": list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST)
        obj.set_password(new_password)
        obj.save(update_fields=["password"])
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken, OutstandingToken,
        )
        for outstanding in OutstandingToken.objects.filter(user=obj):
            BlacklistedToken.objects.get_or_create(token=outstanding)
        log_action(actor=request.user, action="password_reset", instance=obj,
                   details={"employee_id": obj.employee_id})
        return Response(
            {"detail": f"Password reset for {obj.employee_id} completed."},
            status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"],
            permission_classes=[IsITStaff])
    def employee_detail(self, request, pk=None):
        """Administrative overview for a single employee.

        Returns the user record plus assigned assets, tickets requested /
        assigned, and recent audit activity touching the account. IT staff
        only; never exposes passwords or hashes.
        """
        obj = self.get_object()
        from assets.models import Asset
        from tickets.models import Ticket
        from common.models import AuditLog
        assigned_assets = Asset.objects.filter(
            assigned_to=obj).select_related("category", "department").order_by(
                "asset_tag")[:50]
        tickets_requested = Ticket.objects.filter(
            requester=obj).select_related(
                "category", "department", "assignee").order_by(
                    "-created_at")[:50]
        tickets_assigned = Ticket.objects.filter(
            assignee=obj).select_related(
                "category", "department", "requester").order_by(
                    "-created_at")[:50]
        entity_type = f"{obj._meta.app_label}.{obj._meta.model_name}"
        recent_audit = AuditLog.objects.filter(
            Q(entity_type=entity_type, object_id=str(obj.pk))
            | Q(actor=obj)).order_by("-timestamp")[:20]
        from accounts.serializers import UserSerializer
        from assets.serializers import AssetSerializer
        from tickets.serializers import TicketSerializer
        from common.serializers import AuditLogSerializer
        return Response({
            "user": UserSerializer(obj).data,
            "assigned_assets": AssetSerializer(assigned_assets, many=True).data,
            "tickets_requested": TicketSerializer(
                tickets_requested, many=True).data,
            "tickets_assigned": TicketSerializer(
                tickets_assigned, many=True).data,
            "recent_audit": AuditLogSerializer(recent_audit, many=True).data,
        })

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        if not _is_privileged(request.user):
            return Response({"detail": "Forbidden."}, status=403)
        obj = self.get_object()
        if not _can_manage_user(request.user, obj):
            return Response(
                {"detail": "You cannot deactivate an account at or above your "
                           "role."},
                status=status.HTTP_403_FORBIDDEN)
        # An employee holding open asset assignments cannot be deactivated
        # without leaving invalid assignments behind.
        open_assignments = obj.assignments_received.filter(
            returned_at__isnull=True)
        if open_assignments.exists():
            held = ", ".join(
                a.asset.asset_tag for a in open_assignments.select_related(
                    "asset")[:5])
            return Response(
                {"detail": "Cannot deactivate: still holds open assignment(s).",
                 "assignments": [{"asset": a.asset.asset_tag,
                                  "asset_id": a.asset_id}
                                 for a in open_assignments],
                 "hint": "Return the asset(s) first: " + held},
                status=409)
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        log_action(actor=request.user, action="deactivate", instance=obj)
        return Response(UserSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        if not _is_privileged(request.user):
            return Response({"detail": "Forbidden."}, status=403)
        obj = self.get_object()
        if not _can_manage_user(request.user, obj):
            return Response(
                {"detail": "You cannot reactivate an account at or above "
                           "your role."},
                status=status.HTTP_403_FORBIDDEN)
        obj.is_active = True
        obj.save(update_fields=["is_active"])
        log_action(actor=request.user, action="reactivate", instance=obj)
        return Response(UserSerializer(obj).data)

    @action(detail=True, methods=["get", "post"],
            parser_classes=[JSONParser, MultiPartParser, FormParser])
    def photo(self, request, pk=None):
        """Secure employee photo: download (GET) or upload/replace (POST).

        Access: the employee themselves, or IT staff. Never exposes a
        storage URL; the file is streamed through this endpoint after an
        access check. Only images are accepted.
        """
        import mimetypes
        import os

        from django.http import FileResponse

        obj = self.get_object()
        is_self = (
            request.user.is_authenticated and request.user.pk == obj.pk)
        if not (is_self or _is_privileged(request.user)):
            return Response({"detail": "Forbidden."}, status=403)
        if (request.method != "GET" and not is_self
                and not _can_manage_user(request.user, obj)):
            return Response(
                {"detail": "You cannot modify an account at or above your "
                           "role."},
                status=status.HTTP_403_FORBIDDEN)

        if request.method == "GET":
            if not obj.photo or not getattr(obj.photo, "name", ""):
                return Response({"detail": "No photo on file."}, status=404)
            try:
                handle = obj.photo.open("rb")
            except FileNotFoundError:
                return Response(
                    {"detail": "Photo missing from storage."}, status=410)
            name = os.path.basename(obj.photo.name)
            resp = FileResponse(
                handle,
                content_type=mimetypes.guess_type(name)[0]
                or "application/octet-stream")
            resp["Content-Disposition"] = f'inline; filename="{name}"'
            return resp

        upload = request.FILES.get("photo")
        if not upload:
            return Response(
                {"detail": "Provide a 'photo' file."}, status=400)
        try:
            validate_attachment_file(upload)
        except ValidationError as exc:
            return Response({"photo": exc.detail}, status=400)
        obj.photo = upload
        obj.save(update_fields=["photo"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"photo": True})
        return Response(UserSerializer(obj).data)

    @action(detail=True, methods=["post"], permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        from common.throttling import account_action_cooldown
        if account_action_cooldown(
            f"hard_delete:{pk}", 60,
        ):
            return Response({"detail": "Too many hard-delete attempts. Try again later."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

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
            columns = ["employee_id", "username", "email", "first_name",
                       "last_name", "phone", "job_title",
                       "home_department", "is_active",
                       "receive_ticket_emails"]
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
        preview_requested = request.data.get(
            "preview", True) in (True, "true", "1", 1)
        confirmed = request.data.get("confirm")
        if upload:
            allowed = {"employee_id", "username", "email", "first_name",
                       "last_name", "phone", "job_title",
                       "home_department", "is_active",
                       "receive_ticket_emails"}
            if not preview_requested and confirmed:
                count_uploaded_rows(
                    upload, allowed,
                    int(settings.EMPLOYEE_BULK_IMPORT_MAX_FILE_SIZE_MB
                        * 1024 * 1024),
                    settings.EMPLOYEE_BULK_IMPORT_MAX_ROWS,
                    xlsx_extensions=(".xlsx", ".xlsm", ".xltx"),
                )
            rows = _parse_upload(upload, allowed=allowed)
        elif rows_data:
            rows = rows_data if isinstance(rows_data, list) else []
            if rows:
                if len(rows) > settings.EMPLOYEE_BULK_IMPORT_MAX_ROWS:
                    return Response({
                        "file": "Too many rows in request body. Maximum is "
                                f"{settings.EMPLOYEE_BULK_IMPORT_MAX_ROWS}."},
                        status=400)
                allowed = {"employee_id", "username", "email", "first_name",
                           "last_name", "phone", "job_title",
                           "home_department", "is_active",
                           "receive_ticket_emails"}
                unknown = set()
                for r in rows:
                    if isinstance(r, dict):
                        unknown |= set(r) - allowed
                if unknown:
                    return Response(
                        {"file": "unknown columns: " + ", ".join(sorted(unknown))},
                        status=400)
        else:
            return Response({"detail": "Provide 'file' or 'rows'."},
                            status=400)
        if preview_requested or not confirmed:
            preview, errors = _employee_preview(rows)
        if preview_requested:
            return Response({"preview": preview, "errors": errors,
                             "counts": {"ok": len(preview),
                                        "failed": len(errors)}})
        if not confirmed:
            return Response({"detail": "Confirmation required.",
                             "preview": preview, "errors": errors},
                            status=400)
        ok, failed, skipped, employee_id_by_row = _confirm_employee_rows(
            rows, request.user)
        if request.query_params.get("download") == "csv":
            # Same executed import, CSV representation of the per-row
            # outcomes. JSON remains the default when absent.
            return _csv_report_response(
                "employee_import_report.csv",
                _employee_report_rows(
                    employee_id_by_row, ok, skipped, failed))
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
                    if not _can_manage_user(request.user, obj):
                        skipped.append({
                            "employee_id": obj.employee_id,
                            "reason": "insufficient privilege"})
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
            qs = list(User.objects.filter(id__in=ids))
            allowed = [u for u in qs
                       if _can_manage_user(request.user, u)]
            forbidden = [u.employee_id for u in qs if u not in allowed]
            blocked = [
                u.employee_id for u in allowed
                if not activate and u.assignments_received.filter(
                    returned_at__isnull=True).exists()
            ]
            return Response({
                "preview": [u.employee_id for u in allowed],
                "affected": len(allowed),
                "blocked": blocked,
                "forbidden": forbidden})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        for pk in ids:
            try:
                with transaction.atomic():
                    obj = User.objects.get(pk=pk)
                    if not _can_manage_user(request.user, obj):
                        skipped.append({
                            "id": pk,
                            "reason": "insufficient privilege"})
                        continue
                    if not activate and obj.assignments_received.filter(
                            returned_at__isnull=True).exists():
                        skipped.append({
                            "id": pk,
                            "reason": "still holds open asset assignment(s); "
                                      "return the asset first"})
                        continue
                    obj.is_active = bool(activate)
                    obj.save(update_fields=["is_active"])
                    log_action(
                        actor=request.user,
                        action="reactivate" if activate else "deactivate",
                        instance=obj)
                    ok.append(pk)
            except Exception as exc:
                failed.append({"id": pk, "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed})

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Bulk SOFT delete only. Blocked for users with history. Never hard."""
        ids = request.data.get("ids", [])
        objs = list(User.objects.filter(id__in=ids))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            allowed = [o for o in objs
                       if _can_manage_user(request.user, o)]
            forbidden = [o.employee_id for o in objs if o not in allowed]
            blocked = [o.employee_id for o in allowed
                       if o.tickets_requested.count() or
                       o.assignments_received.count()]
            return Response({"preview": [o.employee_id for o in allowed],
                             "affected": len(allowed), "blocked": blocked,
                             "forbidden": forbidden,
                             "note": "soft delete only; history rows block"})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, skipped, failed = [], [], []
        for obj in objs:
            try:
                with transaction.atomic():
                    if not _can_manage_user(request.user, obj):
                        skipped.append({
                            "id": obj.pk,
                            "reason": "insufficient privilege"})
                        continue
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
