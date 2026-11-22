"""Lifecycle API views.

Backend enforcement; scoped querysets prevent IDOR. All mutations delegate
to lifecycle.services (transactions + select_for_update).
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Department, User
from assets.models import Asset
from common.audit import log_action
from common.models import Notification
from lifecycle import models as lm, services
from lifecycle import serializers as sl
from lifecycle.permissions import (
    IsEmployee, IsLifecycleManagerOrAdmin, IsLifecycleStaff,
    IsLifecycleSystemAdmin,
)

CASE_TYPE_ONBOARDING = "onboarding"
CASE_TYPE_OFFBOARDING = "offboarding"
CASE_TYPE_TRANSFER = "transfer"


def _role(user):
    return getattr(user, "role", "")


def _is_admin(user):
    return bool(user and user.is_authenticated and (
        _role(user) == "system_admin" or getattr(user, "is_superuser", False)))


def _is_manager(user):
    return _is_admin(user) or _role(user) == "it_manager"


def _is_staff(user):
    return _is_manager(user) or _role(user) == "it_support"


def _can_see_case(user, case):
    if case.is_deleted:
        return False
    if _is_admin(user) or _is_manager(user):
        return True
    if _is_staff(user):
        return True
    return case.employee_id == user.pk


def _base_case_qs(user):
    qs = lm.LifecycleCase.objects.filter(is_deleted=False).select_related(
        "employee", "department", "initiated_by", "assigned_coordinator")
    if _is_admin(user) or _is_manager(user) or _is_staff(user):
        return qs
    return qs.filter(employee=user)


class LifecycleTemplateViewSet(viewsets.ModelViewSet):
    queryset = lm.LifecycleTemplate.objects.filter(is_deleted=False)
    serializer_class = sl.LifecycleTemplateSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsLifecycleManagerOrAdmin()]
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsLifecycleManagerOrAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        case_type = self.request.query_params.get("case_type")
        if case_type:
            qs = qs.filter(case_type=case_type)
        if not (_is_admin(user) or _is_manager(user)):
            # IT Support / Employee: active templates only.
            qs = qs.filter(is_active=True)
        dept = self.request.query_params.get("department")
        if dept:
            qs = qs.filter(
                models_Q_department(dept, user))
        return qs

    def perform_destroy(self, instance):
        instance.soft_delete(by_user=self.request.user,
                             reason=self.request.data.get("reason", ""))
        log_action(actor=self.request.user, action="soft_delete",
                   instance=instance)


def models_Q_department(dept, user):
    from django.db.models import Q
    return Q(department_id=dept) | Q(department__isnull=True, is_global=True)


class LifecycleTemplateItemViewSet(viewsets.ModelViewSet):
    serializer_class = sl.LifecycleTemplateItemSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsLifecycleManagerOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = lm.LifecycleTemplateItem.objects.filter(
            template__is_deleted=False).select_related("template")
        template = self.request.query_params.get("template")
        if template:
            qs = qs.filter(template_id=template)
        return qs


class LifecycleCaseViewSet(viewsets.ModelViewSet):
    serializer_class = sl.LifecycleCaseDetailSerializer

    def get_permissions(self):
        if self.action in ("create",):
            return [IsLifecycleStaff()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsLifecycleManagerOrAdmin()]
        if self.action in ("plan", "complete", "cancel", "block", "unblock",
                           "apply_department_change", "deactivate_account"):
            return [IsLifecycleManagerOrAdmin()]
        if self.action in ("start", "mark_ready", "confirm_start",
                           "check_assets", "revoke_access"):
            return [IsLifecycleStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return _base_case_qs(self.request.user)

    def get_serializer_class(self):
        if self.action == "list":
            return sl.LifecycleCaseListSerializer
        if self.action == "create":
            return sl.LifecycleCaseCreateSerializer
        return sl.LifecycleCaseDetailSerializer

    def perform_create(self, serializer):
        template = serializer.context.get("template")
        if not template:
            raise ValidationError({"template_id": "Template is required."})
        employee = serializer.validated_data.get("employee")
        if getattr(employee, "is_deleted", False):
            raise ValidationError({"employee": "Deleted employee."})
        assigned_coordinator = serializer.validated_data.get(
            "assigned_coordinator")
        if isinstance(assigned_coordinator, int):
            try:
                assigned_coordinator = User.objects.get(
                    pk=assigned_coordinator)
            except User.DoesNotExist:
                raise ValidationError(
                    {"assigned_coordinator": "Invalid user."})
        case = services.create_case_from_template(
            template=template, employee=employee, actor=self.request.user,
            department=serializer.validated_data.get("department"),
            priority=serializer.validated_data.get("priority", "medium"),
            planned_date=serializer.validated_data.get("planned_date"),
            effective_date=serializer.validated_data.get("effective_date"),
            completion_target=serializer.validated_data.get(
                "completion_target"),
            source=serializer.validated_data.get("source", "manual"),
            source_reference=serializer.validated_data.get(
                "source_reference", ""),
            notes=serializer.validated_data.get("notes", ""),
            assigned_coordinator=assigned_coordinator,
        )
        serializer.instance = case

    def _case(self):
        return get_object_or_404(
            _base_case_qs(self.request.user), pk=self.kwargs["pk"])

    def _transition(self, next_status):
        case = self._case()
        if not _can_see_case(self.request.user, case):
            raise PermissionDenied("Cannot see this case.")
        ser = sl.LifecycleCaseTransitionSerializer(data=self.request.data)
        ser.is_valid(raise_exception=True)
        try:
            return services.transition_case(
                case, next_status, self.request.user,
                reason=ser.validated_data.get("reason", ""),
                version=ser.validated_data.get("version"))
        except ValidationError as exc:
            if getattr(exc, "code", None) == 409:
                return Response(exc.detail, status=status.HTTP_409_CONFLICT)
            raise

    @action(detail=True, methods=["post"])
    def plan(self, request, pk=None):
        case = self._transition("planned")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        case = self._transition("in_progress")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def mark_ready(self, request, pk=None):
        case = self._case()
        if case.case_type != CASE_TYPE_ONBOARDING:
            return Response({"detail": "Onboarding only."},
                            status=status.HTTP_400_BAD_REQUEST)
        case = self._transition("ready_for_employee")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def confirm_start(self, request, pk=None):
        case = self._case()
        if case.case_type != CASE_TYPE_ONBOARDING:
            return Response({"detail": "Onboarding only."},
                            status=status.HTTP_400_BAD_REQUEST)
        case = self._transition("employee_started")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        case = self._transition("completed")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        case = self._transition("blocked")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unblock(self, request, pk=None):
        case = self._transition("in_progress")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        case = self._transition("cancelled")
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def apply_department_change(self, request, pk=None):
        case = self._case()
        if case.case_type != CASE_TYPE_TRANSFER:
            return Response({"detail": "Transfer only."},
                            status=status.HTTP_400_BAD_REQUEST)
        ser = sl.LifecycleCaseTransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_dept_id = request.data.get("new_department")
        try:
            new_dept = Department.objects.get(pk=new_dept_id)
        except (Department.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"new_department": "Invalid department."})
        case = services.apply_department_change(
            case, request.user, new_dept,
            version=ser.validated_data.get("version"))
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def check_assets(self, request, pk=None):
        case = self._case()
        if case.case_type != CASE_TYPE_OFFBOARDING:
            return Response({"detail": "Offboarding only."},
                            status=status.HTTP_400_BAD_REQUEST)
        employee = case.employee
        from assets.models import Asset
        assets = Asset.objects.filter(assigned_to=employee, is_deleted=False)
        created = []
        for a in assets:
            res, _ = lm.LifecycleAssetResolution.objects.get_or_create(
                case=case, asset=a,
                defaults={"status": "pending", "resolution": "pending",
                          "resolved_by": request.user})
            created.append(res.pk)
        _history = services._history
        _history(case, None, request.user, "case_updated",
                 new_status=case.status,
                 detail=f"Asset check: {len(created)} assigned asset(s) found.")
        return Response({"assigned_assets": created})

    @action(detail=True, methods=["post"])
    def revoke_access(self, request, pk=None):
        case = self._case()
        if case.case_type != CASE_TYPE_OFFBOARDING:
            return Response({"detail": "Offboarding only."},
                            status=status.HTTP_400_BAD_REQUEST)
        count = services.revoke_user_tokens(case.employee, request.user)
        services._history(case, None, request.user, "tokens_revoked",
                          new_status=case.status,
                          detail=f"Revoked {count} token(s).")
        return Response({"tokens_revoked": count})

    @action(detail=True, methods=["post"])
    def deactivate_account(self, request, pk=None):
        case = self._case()
        if not _is_admin(request.user):
            raise PermissionDenied("System Admin only.")
        services.deactivate_account(case.employee, request.user)
        services._history(case, None, request.user, "account_deactivated",
                          new_status=case.status,
                          detail=f"Account {case.employee.employee_id} deactivated.")
        return Response({"deactivated": True})

    @action(detail=True, methods=["get"])
    def assigned_assets(self, request, pk=None):
        case = self._case()
        return Response(services.list_assigned_assets(case))

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        case = self._case()
        qs = lm.LifecycleHistory.objects.filter(
            case=case, is_deleted=False).select_related("actor", "task")
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = sl.LifecycleHistorySerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = sl.LifecycleHistorySerializer(qs, many=True)
        return Response(ser.data)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        case = self._case()
        data = {
            "id": case.pk, "case_number": case.case_number,
            "case_type": case.case_type, "status": case.status,
            "priority": case.priority, "employee": case.employee_id,
            "employee_email": case.employee.email,
            "department": case.department_id,
            "coordinator": case.assigned_coordinator_id,
            "checklist_progress": case.checklist_progress,
            "total_tasks": case.total_tasks,
            "completed_tasks": case.completed_tasks,
            "overdue_tasks": case.overdue_tasks,
            "effective_date": case.effective_date,
            "completion_target": case.completion_target,
            "completed_at": case.completed_at,
        }
        return Response(data)

    @action(detail=False, methods=["post"])
    def from_service_request(self, request):
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff only.")
        ser = sl.LifecycleCaseTransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            from services.models import ServiceRequest
            sr_id = request.data.get("service_request_id")
            sr = ServiceRequest.objects.select_related("requester").get(
                pk=sr_id, is_deleted=False)
        except Exception:
            raise ValidationError({"service_request_id": "Invalid service request."})
        # Actor must be authorized to view the requester's case scope.
        employee = sr.requester
        if getattr(employee, "is_deleted", False):
            raise ValidationError("Requester is deleted.")
        template_id = request.data.get("template_id")
        try:
            template = lm.LifecycleTemplate.objects.get(
                pk=template_id, is_deleted=False, is_active=True)
        except (lm.LifecycleTemplate.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"template_id": "Invalid template."})
        assigned_coordinator = request.data.get("assigned_coordinator")
        if isinstance(assigned_coordinator, int):
            try:
                assigned_coordinator = User.objects.get(pk=assigned_coordinator)
            except User.DoesNotExist:
                raise ValidationError({"assigned_coordinator": "Invalid user."})
        case = services.create_case_from_template(
            template=template, employee=employee, actor=request.user,
            department=sr.department or employee.home_department,
            source="service_request", source_reference=sr.request_number,
            assigned_coordinator=assigned_coordinator,
        )
        log_action(actor=request.user, action="create", instance=case,
                   details={"source_service_request": sr.pk})
        return Response(sl.LifecycleCaseDetailSerializer(
            case, context={"request": request}).data,
            status=status.HTTP_201_CREATED)


class LifecycleTaskViewSet(viewsets.ModelViewSet):
    serializer_class = sl.LifecycleTaskDetailSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsLifecycleManagerOrAdmin()]
        if self.action in ("start", "complete", "skip", "block",
                           "unblock", "assign", "retry_automation"):
            return [IsLifecycleStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = lm.LifecycleTask.objects.filter(
            case__is_deleted=False).select_related(
            "case", "assigned_to", "completed_by", "skipped_by",
            "source_template_item", "related_asset")
        user = self.request.user
        if _is_admin(user) or _is_manager(user) or _is_staff(user):
            return qs
        return qs.filter(assigned_to=user)

    def get_serializer_class(self):
        if self.action == "list":
            return sl.LifecycleTaskListSerializer
        return sl.LifecycleTaskDetailSerializer

    def _task(self):
        return get_object_or_404(
            self.get_queryset(), pk=self.kwargs["pk"])

    def _run(self, fn, *args, **kwargs):
        task = self._task()
        if not _can_see_case(self.request.user, task.case):
            raise PermissionDenied("Cannot see this task.")
        try:
            return fn(task, self.request.user, **kwargs)
        except ValidationError as exc:
            if getattr(exc, "code", None) == 409:
                return Response(exc.detail, status=status.HTTP_409_CONFLICT)
            raise

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        task = self._run(services.task_start,
                         version=request.data.get("version"))
        if isinstance(task, Response):
            return task
        return Response(sl.LifecycleTaskDetailSerializer(
            task, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self._task()
        ser = sl.LifecycleTaskCompleteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = self._run(
            services.task_complete,
            completion_note=ser.validated_data.get("completion_note", ""),
            version=ser.validated_data.get("version"))
        if isinstance(result, Response):
            return result
        return Response(sl.LifecycleTaskDetailSerializer(
            result, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def skip(self, request, pk=None):
        task = self._task()
        ser = sl.LifecycleTaskSkipSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = self._run(
            services.task_skip,
            reason=ser.validated_data.get("skip_reason", ""),
            version=ser.validated_data.get("version"))
        if isinstance(result, Response):
            return result
        return Response(sl.LifecycleTaskDetailSerializer(
            result, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        task = self._task()
        ser = sl.LifecycleTaskBlockSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = self._run(
            services.task_block,
            reason=ser.validated_data.get("blocked_reason", ""),
            version=ser.validated_data.get("version"))
        if isinstance(result, Response):
            return result
        return Response(sl.LifecycleTaskDetailSerializer(
            result, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unblock(self, request, pk=None):
        task = self._run(services.task_unblock,
                         version=request.data.get("version"))
        if isinstance(task, Response):
            return task
        return Response(sl.LifecycleTaskDetailSerializer(
            task, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        task = self._task()
        ser = sl.LifecycleTaskAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        assigned_to_id = ser.validated_data.get("assigned_to")
        assigned_to = None
        if assigned_to_id is not None:
            try:
                assigned_to = User.objects.get(pk=assigned_to_id)
            except (User.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"assigned_to": "Invalid user."})
        result = self._run(
            services.task_assign,
            assigned_to=assigned_to,
            version=ser.validated_data.get("version"))
        if isinstance(result, Response):
            return result
        return Response(sl.LifecycleTaskDetailSerializer(
            result, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def retry_automation(self, request, pk=None):
        task = self._task()
        if not _can_see_case(self.request.user, task.case):
            raise PermissionDenied("Cannot see this task.")
        if task.automation_type == "none":
            raise ValidationError("No automation configured for this task.")
        task.automation_status = "not_applicable"
        task.automation_error_summary = ""
        task.save(update_fields=[
            "automation_status", "automation_error_summary", "updated_at"])
        services._run_task_automation(task, request.user)
        task.refresh_from_db()
        return Response(sl.LifecycleTaskDetailSerializer(
            task, context={"request": request}).data)


class LifecycleAssetResolutionViewSet(viewsets.ModelViewSet):
    serializer_class = sl.LifecycleAssetResolutionSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsLifecycleManagerOrAdmin()]
        return [IsLifecycleStaff()]

    def get_queryset(self):
        qs = lm.LifecycleAssetResolution.objects.filter(
            case__is_deleted=False).select_related("case", "asset",
            "resolved_by", "related_task")
        if _is_admin(self.request.user) or _is_manager(
                self.request.user) or _is_staff(self.request.user):
            return qs
        return qs.filter(case__employee=self.request.user)

    def _resolution(self):
        return get_object_or_404(
            self.get_queryset(), pk=self.kwargs["pk"])

    def _resolve(self, resolution, note_field="notes"):
        res = self._resolution()
        if not _can_see_case(self.request.user, res.case):
            raise PermissionDenied("Cannot see this case.")
        ser = sl.AssetResolutionActionSerializer(data=self.request.data)
        ser.is_valid(raise_exception=True)
        resolution = ser.validated_data.get("resolution", resolution)
        note = ser.validated_data.get("notes", "")
        try:
            if resolution == "returned":
                out = services.resolve_asset_return(
                    res.case, res.asset_id, self.request.user, res, note)
            elif resolution == "lost":
                out = services.resolve_asset_lost(
                    res.case, res.asset_id, self.request.user, res, note)
            elif resolution == "damaged":
                out = services.resolve_asset_damaged(
                    res.case, res.asset_id, self.request.user, res, note)
            elif resolution == "transferred":
                ser2 = sl.AssetResolutionTransferSerializer(
                    data=self.request.data)
                ser2.is_valid(raise_exception=True)
                try:
                    new_assignee = User.objects.get(pk=ser2.validated_data["new_assignee"])
                except (User.DoesNotExist, ValueError, TypeError):
                    raise ValidationError(
                        {"new_assignee": "Invalid user."})
                out = services.resolve_asset_transfer(
                    res.case, res.asset_id, self.request.user, new_assignee,
                    res, ser2.validated_data.get("notes", ""))
            elif resolution == "approved_exception":
                out = services.resolve_asset_exception(
                    res.case, res.asset_id, self.request.user,
                    ser.validated_data.get("notes", ""), res)
            else:
                raise ValidationError({"resolution": "Unknown resolution."})
        except ValidationError as exc:
            if getattr(exc, "code", None) == 409:
                return Response(exc.detail, status=status.HTTP_409_CONFLICT)
            raise
        return Response(sl.LifecycleAssetResolutionSerializer(
            out, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def return_(self, request, pk=None):
        return self._resolve("returned")

    @action(detail=True, methods=["post"])
    def mark_lost(self, request, pk=None):
        return self._resolve("lost")

    @action(detail=True, methods=["post"])
    def mark_damaged(self, request, pk=None):
        return self._resolve("damaged")

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        return self._resolve("transferred")

    @action(detail=True, methods=["post"])
    def approve_exception(self, request, pk=None):
        return self._resolve("approved_exception")


class LifecycleTaskEvidenceViewSet(viewsets.ModelViewSet):
    serializer_class = sl.LifecycleTaskEvidenceSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated()]
        if self.action == "destroy":
            return [IsLifecycleStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = lm.LifecycleTaskEvidence.objects.filter(
            case__is_deleted=False, is_deleted=False).select_related(
            "case", "task", "uploaded_by")
        user = self.request.user
        if _is_admin(user) or _is_manager(user) or _is_staff(user):
            return qs
        return qs.filter(
            case__employee=user, task__assigned_to=user)

    def perform_create(self, serializer):
        task = serializer.validated_data.get("task")
        case = serializer.validated_data.get("case")
        if task is not None:
            task_pk = task.pk if hasattr(task, "pk") else task
            t = lm.LifecycleTask.objects.only("case_id", "assigned_to_id").get(
                pk=task_pk)
            if case is not None and t.case_id != case.pk:
                raise ValidationError(
                    {"task": "Task must belong to the case."})
            if not _is_staff(self.request.user) \
                    and t.assigned_to_id != self.request.user.pk:
                raise PermissionDenied(
                    "Evidence may only be uploaded to a task assigned to you.")
        if not _can_see_case(self.request.user, case):
            raise PermissionDenied("Cannot see this case.")
        obj = serializer.save(uploaded_by=self.request.user,
                              original_filename=getattr(
                                  serializer.validated_data.get("file"),
                                  "name", "")[:255])
        log_action(actor=self.request.user, action="create", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff only.")
        obj.soft_delete(by_user=request.user, reason="evidence removed")
        log_action(actor=request.user, action="soft_delete", instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        import mimetypes
        import os
        from django.http import FileResponse
        from common.attachment_security import (
            add_download_security_headers,
            safe_content_disposition_filename,
        )
        obj = self.get_object()
        if obj.is_deleted:
            return Response({"detail": "Evidence is deleted."}, status=404)
        try:
            handle = obj.file.open("rb")
        except FileNotFoundError:
            return Response({"detail": "File missing from storage."}, status=410)
        name = obj.original_filename or os.path.basename(obj.file.name)
        resp = FileResponse(
            handle,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream")
        safe_name = safe_content_disposition_filename(name)
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        add_download_security_headers(resp)
        return resp


class LifecycleHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = sl.LifecycleHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = lm.LifecycleHistory.objects.filter(
            case__is_deleted=False, is_deleted=False).select_related(
            "case", "task", "actor")
        case = self.request.query_params.get("case")
        if case:
            qs = qs.filter(case_id=case)
        user = self.request.user
        if not (_is_admin(user) or _is_manager(user) or _is_staff(user)):
            qs = qs.filter(case__employee=user)
        return qs


from django.db.models import Q  # noqa: E402


class LifecycleDashboardView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        user = request.user
        is_admin = _is_admin(user)
        is_manager = _is_manager(user)
        is_staff = is_manager or _role(user) == "it_support"

        base = lm.LifecycleCase.objects.filter(is_deleted=False)
        if not (is_admin or is_manager or is_staff):
            base = base.filter(employee=user)

        now = timezone.now()
        week_hence = now + timezone.timedelta(days=7)

        def _count(qs, **filters):
            return qs.filter(**filters).count()

        task_qs = lm.LifecycleTask.objects.filter(
            is_deleted=False, case__in=base)

        data = {
            "onboarding_in_progress": _count(
                base, case_type="onboarding", status="in_progress"),
            "onboarding_due_7d": _count(
                base, case_type="onboarding",
                completion_target__range=(now, week_hence)),
            "onboarding_blocked": _count(
                base, case_type="onboarding", status="blocked"),
            "offboarding_in_progress": _count(
                base, case_type="offboarding", status="in_progress"),
            "offboarding_effective_7d": _count(
                base, case_type="offboarding",
                effective_date__range=(now, week_hence)),
            "offboarding_unresolved_assets": _count(
                base, case_type="offboarding",
                asset_resolutions__resolution="pending",
                asset_resolutions__is_deleted=False),
            "offboarding_awaiting_deactivation": _count(
                base, case_type="offboarding", status__in=(
                    "awaiting_access_revocation", "ready_for_closure")),
            "transfers_in_progress": _count(
                base, case_type="transfer", status="in_progress"),
            "overdue_tasks": _count(
                task_qs, due_date__lt=now,
                status__in=("pending", "in_progress", "blocked")),
            "failed_automations": _count(
                task_qs, automation_status="failed"),
        }
        if is_admin or is_manager:
            data["recent_cases"] = list(
                base.order_by("-created_at")[:10].values(
                    "case_number", "case_type", "status", "created_at"))
            data["urgent_cases"] = list(
                base.filter(priority="urgent").exclude(
                    status__in=lm.TERMINAL_STATUSES).order_by(
                    "-created_at")[:10].values(
                    "case_number", "case_type", "status"))
            data["tasks_assigned_to_me"] = list(
                lm.LifecycleTask.objects.filter(
                    assigned_to=user, is_deleted=False).exclude(
                    status__in=("completed", "skipped", "cancelled")).order_by(
                    "due_date")[:20].values(
                    "id", "title", "case__case_number", "due_date", "status"))
        return Response(data)
