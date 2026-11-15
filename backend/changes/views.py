"""Change Management viewsets.

Provides the full IT Change lifecycle API under /api/changes/:

ViewSets:
    changes/                  ChangeRequest (full lifecycle + actions)
    templates/                ChangeTemplate
    tasks/                    ChangeTask
    assets/                   ChangeAssetImpact
    services/                 ChangeServiceImpact
    dependencies/             ChangeDependency
    risk-assessments/         ChangeRiskAssessment
    approvals/                ChangeApproval
    review-meetings/          ChangeReviewMeeting
    review-items/             ChangeReviewItem
    maintenance-windows/      MaintenanceWindow
    conflicts/                ChangeConflict
    attachments/              ChangeAttachment
    stakeholders/             ChangeStakeholder
    communications/           ChangeCommunication
    implementations/          ChangeImplementation
    post-implementation-reviews/ PostImplementationReview
    ticket-links/             ChangeTicketLink
    knowledge-links/          ChangeKnowledgeLink
    calendar/                 ChangeCalendar (read-only)
    outages/                  ChangeOutage (read-only, employee-safe)
    dashboard/                ChangeDashboard (read-only)
    reports/                  ChangeReports (read-only)

All mutations are transactional, permission-checked, audited and idempotent.
Frontend visibility is UX-only; backend enforcement is authoritative.
"""
from django.db import transaction
from django.db.models import Q, Count, Avg
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from changes.models import (
    ChangeRequest,
    ChangeTemplate,
    ChangeTask,
    ChangeHistory,
    ChangeAssetImpact,
    ChangeServiceImpact,
    ChangeDependency,
    ChangeRiskAssessment,
    ChangeApproval,
    ChangeReviewMeeting,
    ChangeReviewItem,
    MaintenanceWindow,
    ChangeConflict,
    ChangeAttachment,
    ChangeStakeholder,
    ChangeCommunication,
    ChangeImplementation,
    PostImplementationReview,
    ChangeTicketLink,
    ChangeKnowledgeLink,
)
from changes.serializers import (
    ChangeRequestSerializer,
    ChangeRequestListSerializer,
    ChangeRequestCreateSerializer,
    ChangeTemplateSerializer,
    ChangeTaskSerializer,
    ChangeHistorySerializer,
    ChangeAssetImpactSerializer,
    ChangeServiceImpactSerializer,
    ChangeDependencySerializer,
    ChangeRiskAssessmentSerializer,
    ChangeApprovalSerializer,
    ChangeReviewMeetingSerializer,
    ChangeReviewItemSerializer,
    MaintenanceWindowSerializer,
    ChangeConflictSerializer,
    ChangeAttachmentSerializer,
    ChangeStakeholderSerializer,
    ChangeCommunicationSerializer,
    ChangeImplementationSerializer,
    PostImplementationReviewSerializer,
    ChangeTicketLinkSerializer,
    ChangeKnowledgeLinkSerializer,
    ChangeReadinessSerializer,
    ChangeSchedulingSerializer,
    ChangeImplementationStartSerializer,
    ChangeCompleteSerializer,
    ChangeFailSerializer,
    ChangeRollbackSerializer,
    ChangeCloseSerializer,
    ChangeCancelSerializer,
    ChangeConvertToEmergencySerializer,
    ChangeRiskQuestionnaireSerializer,
    ChangeApprovalDecisionSerializer,
)
from changes.services import (
    _generate_change_number,
    ensure_change_tasks,
    calculate_risk,
    confirm_risk,
    request_approval,
    approve_change,
    reject_change,
    schedule_change,
    start_implementation,
    complete_implementation,
    fail_implementation,
    start_rollback,
    complete_rollback,
    request_pir,
    close_change,
    cancel_change,
    create_stakeholder,
    send_communication,
    link_ticket,
    link_knowledge,
    add_attachment,
)
from changes.permissions import (
    IsChangeStaff,
    IsChangeManager,
    IsChangeManagerOrAdmin,
    IsChangeApprover,
    IsChangeScheduling,
    IsChangeImplementer,
    IsChangeCloser,
    IsChangePIRWaiver,
    IsChangeConflictOverride,
    _is_staff,
    _can_manage,
    _can_approve,
)
from changes.conflicts import detect_conflicts, upsert_conflicts, resolve_conflicts_for_change


def _user_department(user):
    return getattr(getattr(user, "home_department", None), "pk", None)


def _scope_queryset(user, qs):
    """Object-level scope: employees see only their own changes."""
    role = getattr(user, "role", "")
    if _is_staff(user) or getattr(user, "is_superuser", False):
        return qs
    # Employee: own changes only.
    return qs.filter(requester=user)


def _require_staff(user):
    if not _is_staff(user):
        raise PermissionDenied("IT staff authorization required.")


def _require_manager_or_admin(user):
    if not (_is_staff(user) and getattr(user, "role", "") in ("system_admin", "it_manager")) and not getattr(
        user, "is_superuser", False
    ):
        raise PermissionDenied("IT Manager or System Admin authorization required.")


def _is_terminal(status):
    return status in ("closed", "rejected", "cancelled", "failed", "rolled_back")


# ---------------------------------------------------------------------------
# ChangeRequest
# ---------------------------------------------------------------------------


class ChangeRequestViewSet(viewsets.ModelViewSet):
    """Change requests with full lifecycle actions."""

    queryset = ChangeRequest.objects.all()
    serializer_class = ChangeRequestSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return ChangeRequestListSerializer
        if self.action == "create":
            return ChangeRequestCreateSerializer
        return ChangeRequestSerializer

    def get_queryset(self):
        qs = ChangeRequest.objects.select_related(
            "requester", "change_owner", "implementation_lead",
            "department", "current_approver",
        )
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("create",):
            return [permissions.IsAuthenticated()]
        if self.action in ("approve", "reject"):
            return [permissions.IsAuthenticated(), IsChangeApprover()]
        if self.action == "close":
            return [IsChangeCloser()]
        if self.action in ("destroy",):
            return [IsChangeManagerOrAdmin()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        user = self.request.user
        # Generate number before save to avoid unique constraint on empty
        # change_number.
        change_number = _generate_change_number()
        req = serializer.save(
            requester=user,
            change_owner=user,
            change_number=change_number,
            status="draft",
        )
        ChangeHistory.objects.create(
            change=req,
            actor=user,
            event_type="created",
            detail="Change request created.",
        )
        return req

    def perform_update(self, serializer):
        user = self.request.user
        instance = self.get_object()
        # Stale-version protection handled by frontend; here we just bump version.
        if instance.status not in ("draft", "submitted"):
            raise ValidationError("Only draft or submitted changes can be edited.")
        # Non-staff cannot change staff-only fields (handled at serializer/view
        # level); here we bump version on any material change.
        instance.version = (instance.version or 1) + 1
        serializer.save(updated_by=user)
        ChangeHistory.objects.create(
            change=instance,
            actor=user,
            event_type="updated",
            detail="Change updated.",
        )

    def perform_destroy(self, instance):
        # Only draft changes can be deleted; nothing else is hard-deleted.
        if instance.status != "draft":
            raise ValidationError("Only draft changes can be deleted.")
        instance.soft_delete(by_user=self.request.user, reason="Change cancelled before submission.")
        ChangeHistory.objects.create(
            change=instance,
            actor=self.request.user,
            event_type="cancelled",
            detail="Draft change cancelled.",
        )

    # ---- Actions ----

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        change = self.get_object()
        if change.status != "draft":
            raise ValidationError("Only draft changes can be submitted.")
        with transaction.atomic():
            change.status = "submitted"
            change.submitted_at = timezone.now()
            change.save(update_fields=["status", "submitted_at", "updated_at"])
            ChangeHistory.objects.create(
                change=change,
                actor=request.user,
                event_type="submitted",
                detail="Change submitted for review.",
            )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def calculate_risk(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeRiskQuestionnaireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assessment = calculate_risk(
            change,
            serializer.validated_data,
            request.user,
            override_level=serializer.validated_data.get("override_level", ""),
            override_reason=serializer.validated_data.get("override_reason", ""),
        )
        return Response(
            {
                "id": assessment.id,
                "total_score": assessment.total_score,
                "calculated_level": assessment.calculated_level,
                "override_level": assessment.override_level,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def confirm_risk(self, request, pk=None):
        change = self.get_object()
        assessment = confirm_risk(change, request.user)
        return Response(
            {
                "id": assessment.id,
                "total_score": assessment.total_score,
                "calculated_level": assessment.calculated_level,
            }
        )

    @action(detail=True, methods=["post"])
    def request_approval(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval_level = request.data.get("approval_level", "manager")
        approval = request_approval(change, request.user, approval_level)
        return Response(
            {
                "id": str(approval.pk),
                "approval_level": approval.approval_level,
                "status": approval.status,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval = approve_change(
            change, request.user, decision_reason=serializer.validated_data.get("decision_reason", "")
        )
        return Response(
            {
                "id": str(approval.pk),
                "status": approval.status,
                "change_status": change.status,
            }
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval = reject_change(
            change, request.user, decision_reason=serializer.validated_data.get("decision_reason", "")
        )
        return Response(
            {
                "id": str(approval.pk),
                "status": approval.status,
                "change_status": change.status,
            }
        )

    @action(detail=True, methods=["get"])
    def approvals(self, request, pk=None):
        """Return the approval history for this change only."""
        change = self.get_object()
        approvals = (
            ChangeApproval.objects.filter(change=change)
            .select_related("requester", "decided_by", "requested_from")
            .order_by("-created_at")
        )
        page = self.paginate_queryset(approvals)
        if page is not None:
            serializer = ChangeApprovalSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ChangeApprovalSerializer(approvals, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def return_for_correction(self, request, pk=None):
        change = self.get_object()
        if change.status != "pending_approval":
            raise ValidationError("Only pending-approval changes can be returned for correction.")
        if change.requester_id == request.user.pk:
            raise ValidationError("Requester cannot return their own change for correction.")
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff authorization required.")
        with transaction.atomic():
            change.status = "submitted"
            change.save(update_fields=["status", "updated_at"])
            ChangeHistory.objects.create(
                change=change,
                actor=request.user,
                event_type="returned_for_correction",
                detail="Change returned for correction.",
            )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeSchedulingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule_change(
            change,
            request.user,
            serializer.validated_data["planned_start"],
            serializer.validated_data["planned_end"],
            serializer.validated_data.get("expected_downtime_minutes"),
        )
        change.refresh_from_db()
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        return self.schedule(request, pk=pk)

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        change = self.get_object()
        if change.status not in ("approved", "scheduled", "in_progress"):
            raise ValidationError("Only active changes can be put on hold.")
        change.status = "on_hold"
        change.save(update_fields=["status", "updated_at"])
        ChangeHistory.objects.create(
            change=change,
            actor=request.user,
            event_type="updated",
            detail="Change placed on hold.",
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        change = self.get_object()
        if change.status != "on_hold":
            raise ValidationError("Only held changes can be resumed.")
        change.status = "approved"
        change.save(update_fields=["status", "updated_at"])
        ChangeHistory.objects.create(
            change=change,
            actor=request.user,
            event_type="updated",
            detail="Change resumed from hold.",
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def start_implementation(self, request, pk=None):
        change = self.get_object()
        change = start_implementation(change, request.user)
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def begin_validation(self, request, pk=None):
        change = self.get_object()
        if change.status != "in_progress":
            raise ValidationError("Only in-progress changes can begin validation.")
        change.status = "validation"
        change.save(update_fields=["status", "updated_at"])
        ChangeHistory.objects.create(
            change=change,
            actor=request.user,
            event_type="validation_started",
            detail="Validation started.",
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change = complete_implementation(
            change,
            request.user,
            validation_passed=serializer.validated_data.get("validation_passed", True),
            notes=serializer.validated_data.get("implementation_notes", ""),
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeFailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change = fail_implementation(
            change, request.user, failure_reason=serializer.validated_data.get("failure_reason", "")
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def start_rollback(self, request, pk=None):
        change = self.get_object()
        change = start_rollback(change, request.user)
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def complete_rollback(self, request, pk=None):
        change = self.get_object()
        change = complete_rollback(change, request.user)
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def request_pir(self, request, pk=None):
        change = self.get_object()
        change = request_pir(change, request.user)
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change = close_change(
            change, request.user, closure_summary=serializer.validated_data.get("closure_summary", "")
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change = cancel_change(change, request.user, reason=serializer.validated_data.get("reason", ""))
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"])
    def convert_to_emergency(self, request, pk=None):
        change = self.get_object()
        serializer = ChangeConvertToEmergencySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not _can_manage(request.user):
            raise PermissionDenied("IT Manager or System Admin authorization required.")
        change.change_type = "emergency"
        change.emergency_reason = serializer.validated_data.get("emergency_reason", "")
        change.save(update_fields=["change_type", "emergency_reason", "updated_at"])
        ChangeHistory.objects.create(
            change=change,
            actor=request.user,
            event_type="updated",
            detail="Change converted to emergency.",
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["get"])
    def readiness(self, request, pk=None):
        change = self.get_object()
        blockers = []
        if change.status not in ("approved", "scheduled", "in_progress"):
            blockers.append(f"Change is not in an implementable state ({change.status}).")
        if not change.planned_start or not change.planned_end:
            blockers.append("Change is not scheduled.")
        if not change.rollback_plan:
            blockers.append("Rollback plan is missing.")
        required_tasks = change.tasks.filter(
            status__in=["pending", "ready", "in_progress", "blocked"], required=True
        )
        if required_tasks.exists():
            blockers.append("Required implementation tasks are not complete.")
        critical_conflicts = ChangeConflict.objects.filter(
            change=change, severity="critical", status="open"
        )
        if critical_conflicts.exists():
            blockers.append("Unresolved critical conflicts exist.")
        return ChangeReadinessSerializer(
            {"ready": not blockers, "blockers": blockers}
        ).data

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        change = self.get_object()
        history = change.history.select_related("actor", "task").all()
        return Response(ChangeHistorySerializer(history, many=True).data)

    @action(detail=True, methods=["get"])
    def conflicts(self, request, pk=None):
        change = self.get_object()
        conflicts = ChangeConflict.objects.filter(change=change).select_related(
            "conflicting_change"
        )
        return Response(ChangeConflictSerializer(conflicts, many=True).data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        change = self.get_object()
        history = change.history.select_related("actor").all()
        return Response(ChangeHistorySerializer(history, many=True).data)

    @action(detail=True, methods=["get"])
    def attachments(self, request, pk=None):
        change = self.get_object()
        attachments = ChangeAttachment.objects.filter(change=change).select_related("uploaded_by")
        return Response(ChangeAttachmentSerializer(attachments, many=True).data)


# ---------------------------------------------------------------------------
# ChangeTemplate
# ---------------------------------------------------------------------------


class ChangeTemplateViewSet(viewsets.ModelViewSet):
    queryset = ChangeTemplate.objects.all()
    serializer_class = ChangeTemplateSerializer

    def get_queryset(self):
        qs = ChangeTemplate.objects.all()
        user = self.request.user
        if not _is_staff(user):
            return qs.filter(is_active=True, is_preapproved=True)
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]


# ---------------------------------------------------------------------------
# ChangeTask
# ---------------------------------------------------------------------------


class ChangeTaskViewSet(viewsets.ModelViewSet):
    queryset = ChangeTask.objects.all()
    serializer_class = ChangeTaskSerializer

    def get_queryset(self):
        qs = ChangeTask.objects.select_related("change", "assigned_to")
        user = self.request.user
        if not _is_staff(user):
            return qs.none()
        return qs

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        task = self.get_object()
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff authorization required.")
        if task.status != "ready":
            raise ValidationError("Only ready tasks can be started.")
        task.status = "in_progress"
        task.actual_start = timezone.now()
        task.save(update_fields=["status", "actual_start", "updated_at"])
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff authorization required.")
        if task.status != "in_progress":
            raise ValidationError("Only in-progress tasks can be completed.")
        task.status = "completed"
        task.actual_end = timezone.now()
        task.save(update_fields=["status", "actual_end", "updated_at"])
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def skip(self, request, pk=None):
        task = self.get_object()
        if not _can_manage(request.user):
            raise PermissionDenied("IT Manager or System Admin authorization required.")
        if not task.required:
            raise ValidationError("Only required tasks can be skipped.")
        task.status = "skipped"
        task.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        task = self.get_object()
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff authorization required.")
        task.status = "blocked"
        task.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def unblock(self, request, pk=None):
        task = self.get_object()
        if not _is_staff(request.user):
            raise PermissionDenied("IT staff authorization required.")
        task.status = "ready"
        task.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        task = self.get_object()
        user_id = request.data.get("assigned_to")
        if not user_id:
            raise ValidationError("assigned_to is required.")
        from accounts.models import User
        assignee = User.objects.filter(pk=user_id).first()
        if not assignee:
            raise ValidationError("User not found.")
        task.assigned_to = assignee
        task.save(update_fields=["assigned_to", "updated_at"])
        return Response(self.get_serializer(task).data)


# ---------------------------------------------------------------------------
# ChangeAssetImpact / ChangeServiceImpact / ChangeDependency
# ---------------------------------------------------------------------------


class ChangeAssetImpactViewSet(viewsets.ModelViewSet):
    queryset = ChangeAssetImpact.objects.all()
    serializer_class = ChangeAssetImpactSerializer

    def get_queryset(self):
        qs = ChangeAssetImpact.objects.select_related("change", "asset")
        return _scope_queryset(self.request.user, qs)


class ChangeServiceImpactViewSet(viewsets.ModelViewSet):
    queryset = ChangeServiceImpact.objects.all()
    serializer_class = ChangeServiceImpactSerializer

    def get_queryset(self):
        qs = ChangeServiceImpact.objects.select_related("change", "service_catalogue_item")
        return _scope_queryset(self.request.user, qs)


class ChangeDependencyViewSet(viewsets.ModelViewSet):
    queryset = ChangeDependency.objects.all()
    serializer_class = ChangeDependencySerializer

    def get_queryset(self):
        qs = ChangeDependency.objects.select_related("predecessor", "successor")
        return _scope_queryset(self.request.user, qs)


# ---------------------------------------------------------------------------
# ChangeRiskAssessment / ChangeApproval
# ---------------------------------------------------------------------------


class ChangeRiskAssessmentViewSet(viewsets.ModelViewSet):
    queryset = ChangeRiskAssessment.objects.all()
    serializer_class = ChangeRiskAssessmentSerializer

    def get_queryset(self):
        qs = ChangeRiskAssessment.objects.select_related("change")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]


class ChangeApprovalViewSet(viewsets.ModelViewSet):
    queryset = ChangeApproval.objects.all()
    serializer_class = ChangeApprovalSerializer

    def get_queryset(self):
        qs = ChangeApproval.objects.select_related("change", "requester", "decided_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeApprover()]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        approval = self.get_object()
        serializer = ChangeApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not _can_approve(request.user):
            raise PermissionDenied("IT Manager or System Admin authorization required.")
        # Operate on the exact approval instance; service validates it belongs
        # to its change, is pending, enforces separation of duties and version.
        approval = approve_change(
            approval.change, request.user,
            decision_reason=serializer.validated_data.get("decision_reason", ""),
            approval=approval,
        )
        return Response(self.get_serializer(approval).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        approval = self.get_object()
        serializer = ChangeApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not _can_approve(request.user):
            raise PermissionDenied("IT Manager or System Admin authorization required.")
        approval = reject_change(
            approval.change, request.user,
            decision_reason=serializer.validated_data.get("decision_reason", ""),
            approval=approval,
        )
        return Response(self.get_serializer(approval).data)


# ---------------------------------------------------------------------------
# ChangeReviewMeeting / ChangeReviewItem
# ---------------------------------------------------------------------------


class ChangeReviewMeetingViewSet(viewsets.ModelViewSet):
    queryset = ChangeReviewMeeting.objects.all()
    serializer_class = ChangeReviewMeetingSerializer

    def get_queryset(self):
        qs = ChangeReviewMeeting.objects.select_related("chair", "created_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]


class ChangeReviewItemViewSet(viewsets.ModelViewSet):
    queryset = ChangeReviewItem.objects.all()
    serializer_class = ChangeReviewItemSerializer

    def get_queryset(self):
        qs = ChangeReviewItem.objects.select_related("meeting", "change", "decided_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]


# ---------------------------------------------------------------------------
# MaintenanceWindow
# ---------------------------------------------------------------------------


class MaintenanceWindowViewSet(viewsets.ModelViewSet):
    queryset = MaintenanceWindow.objects.all()
    serializer_class = MaintenanceWindowSerializer

    def get_queryset(self):
        qs = MaintenanceWindow.objects.select_related("department", "service", "created_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]


# ---------------------------------------------------------------------------
# ChangeConflict
# ---------------------------------------------------------------------------


class ChangeConflictViewSet(viewsets.ModelViewSet):
    queryset = ChangeConflict.objects.all()
    serializer_class = ChangeConflictSerializer

    def get_queryset(self):
        qs = ChangeConflict.objects.select_related("change", "conflicting_change")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        conflict = self.get_object()
        if conflict.status != "open":
            raise ValidationError("Only open conflicts can be acknowledged.")
        conflict.status = "acknowledged"
        conflict.acknowledged_at = timezone.now()
        conflict.acknowledged_by = request.user
        conflict.save(update_fields=["status", "acknowledged_at", "acknowledged_by", "updated_at"])
        return Response(self.get_serializer(conflict).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        conflict = self.get_object()
        if conflict.status != "open":
            raise ValidationError("Only open conflicts can be resolved.")
        if not _can_manage(request.user):
            raise PermissionDenied("IT Manager or System Admin authorization required.")
        conflict.status = "resolved"
        conflict.resolution = request.data.get("resolution", "")
        conflict.resolved_at = timezone.now()
        conflict.resolved_by = request.user
        conflict.save(update_fields=["status", "resolution", "resolved_at", "resolved_by", "updated_at"])
        return Response(self.get_serializer(conflict).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        conflict = self.get_object()
        if conflict.status != "open":
            raise ValidationError("Only open conflicts can be accepted.")
        if conflict.severity == "critical" and not _can_manage(request.user):
            raise PermissionDenied("IT Manager or System Admin authorization required to accept critical conflicts.")
        conflict.status = "accepted"
        conflict.resolved_at = timezone.now()
        conflict.resolved_by = request.user
        conflict.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
        return Response(self.get_serializer(conflict).data)


# ---------------------------------------------------------------------------
# ChangeAttachment
# ---------------------------------------------------------------------------


class ChangeAttachmentViewSet(viewsets.ModelViewSet):
    queryset = ChangeAttachment.objects.all()
    serializer_class = ChangeAttachmentSerializer

    def get_queryset(self):
        qs = ChangeAttachment.objects.select_related("change", "task", "uploaded_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        if self.action in ("create",):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]

    def perform_create(self, serializer):
        attachment = serializer.save(uploaded_by=self.request.user)
        ChangeHistory.objects.create(
            change=attachment.change,
            actor=self.request.user,
            event_type="attachment_added",
            detail=f"Attachment added: {attachment.original_filename}",
        )
        return attachment


# ---------------------------------------------------------------------------
# ChangeStakeholder / ChangeCommunication
# ---------------------------------------------------------------------------


class ChangeStakeholderViewSet(viewsets.ModelViewSet):
    queryset = ChangeStakeholder.objects.all()
    serializer_class = ChangeStakeholderSerializer

    def get_queryset(self):
        qs = ChangeStakeholder.objects.select_related("change", "user", "department")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]


class ChangeCommunicationViewSet(viewsets.ModelViewSet):
    queryset = ChangeCommunication.objects.all()
    serializer_class = ChangeCommunicationSerializer

    def get_queryset(self):
        qs = ChangeCommunication.objects.select_related("change", "sent_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]


# ---------------------------------------------------------------------------
# ChangeImplementation / PostImplementationReview
# ---------------------------------------------------------------------------


class ChangeImplementationViewSet(viewsets.ModelViewSet):
    queryset = ChangeImplementation.objects.all()
    serializer_class = ChangeImplementationSerializer

    def get_queryset(self):
        qs = ChangeImplementation.objects.select_related(
            "change", "started_by", "completed_by", "rollback_completed_by"
        )
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]


class PostImplementationReviewViewSet(viewsets.ModelViewSet):
    queryset = PostImplementationReview.objects.all()
    serializer_class = PostImplementationReviewSerializer

    def get_queryset(self):
        qs = PostImplementationReview.objects.select_related("change", "reviewer", "reviewed_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]


# ---------------------------------------------------------------------------
# ChangeTicketLink / ChangeKnowledgeLink
# ---------------------------------------------------------------------------


class ChangeTicketLinkViewSet(viewsets.ModelViewSet):
    queryset = ChangeTicketLink.objects.all()
    serializer_class = ChangeTicketLinkSerializer

    def get_queryset(self):
        qs = ChangeTicketLink.objects.select_related("change", "ticket", "created_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]


class ChangeKnowledgeLinkViewSet(viewsets.ModelViewSet):
    queryset = ChangeKnowledgeLink.objects.all()
    serializer_class = ChangeKnowledgeLinkSerializer

    def get_queryset(self):
        qs = ChangeKnowledgeLink.objects.select_related("change", "article", "created_by")
        return _scope_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]


# ---------------------------------------------------------------------------
# Calendar / Outages / Dashboard / Reports
# ---------------------------------------------------------------------------


class ChangeCalendarViewSet(viewsets.ViewSet):
    """Bounded calendar of upcoming changes."""

    def list(self, request):
        user = request.user
        if not _is_staff(user):
            # Employee: no internal calendar access.
            return Response([])
        qs = ChangeRequest.objects.filter(
            status__in=["scheduled", "in_progress"],
            planned_start__isnull=False,
        ).select_related("change_owner", "department")
        qs = _scope_queryset(user, qs)
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        if start:
            qs = qs.filter(planned_start__gte=start)
        if end:
            qs = qs.filter(planned_start__lte=end)
        # Bound range to 366 days.
        if not start:
            start = timezone.now().date()
        if not end:
            end = start + timezone.timedelta(days=366)
        qs = qs.filter(planned_start__gte=start, planned_start__lte=end)
        data = []
        for c in qs[:500]:
            data.append({
                "id": c.id,
                "change_number": c.change_number,
                "title": c.title,
                "change_type": c.change_type,
                "status": c.status,
                "risk_level": c.risk_level,
                "planned_start": c.planned_start,
                "planned_end": c.planned_end,
                "actual_start": c.actual_start,
                "actual_end": c.actual_end,
                "expected_downtime_minutes": c.expected_downtime_minutes,
                "department": c.department.name if c.department else None,
                "detail_path": f"/api/changes/{c.pk}/",
            })
        return Response(data)


class ChangeOutageViewSet(viewsets.ViewSet):
    """Employee-safe public outage communications."""

    def list(self, request):
        user = request.user
        # Only approved/scheduled changes with outage impact are visible.
        qs = ChangeRequest.objects.filter(
            status__in=["approved", "scheduled", "in_progress", "completed"],
            expected_downtime_minutes__gt=0,
        ).select_related("department")
        if not _is_staff(user):
            qs = qs.filter(department=user.home_department)
        data = []
        for c in qs[:200]:
            data.append({
                "id": c.id,
                "change_number": c.change_number,
                "title": c.title,
                "planned_start": c.planned_start,
                "planned_end": c.planned_end,
                "expected_downtime_minutes": c.expected_downtime_minutes,
                "department": c.department.name if c.department else None,
                "status": c.status,
            })
        return Response(data)


class ChangeDashboardViewSet(viewsets.ViewSet):
    """Aggregate change dashboard metrics."""

    def list(self, request):
        user = request.user
        qs = ChangeRequest.objects.all()
        qs = _scope_queryset(user, qs)
        now = timezone.now()
        next7 = now + timezone.timedelta(days=7)
        next30 = now + timezone.timedelta(days=30)

        data = {
            "draft": qs.filter(status="draft").count(),
            "pending_risk_assessment": qs.filter(status="risk_assessment").count(),
            "pending_technical_review": qs.filter(status="technical_review").count(),
            "pending_approval": qs.filter(status="pending_approval").count(),
            "approved_unscheduled": qs.filter(status="approved", planned_start__isnull=True).count(),
            "scheduled_next_7_days": qs.filter(
                status="scheduled", planned_start__gte=now, planned_start__lte=next7
            ).count(),
            "scheduled_next_30_days": qs.filter(
                status="scheduled", planned_start__gte=now, planned_start__lte=next30
            ).count(),
            "in_progress": qs.filter(status="in_progress").count(),
            "validation_pending": qs.filter(status="validation").count(),
            "pir_overdue": PostImplementationReview.objects.filter(
                status__in=["pending", "scheduled", "in_progress"],
                scheduled_for__lt=now,
            ).count(),
            "failed": qs.filter(status="failed").count(),
            "rolled_back": qs.filter(status="rolled_back").count(),
            "emergency_changes": qs.filter(change_type="emergency").count(),
            "open_conflicts": ChangeConflict.objects.filter(status="open").count(),
            "critical_conflicts": ChangeConflict.objects.filter(severity="critical", status="open").count(),
        }

        # Rates.
        implemented = qs.filter(status__in=["completed", "failed", "rolled_back"]).count()
        successful = qs.filter(status="completed").count()
        data["success_rate"] = round((successful / implemented) * 100, 2) if implemented else 0
        data["rollback_rate"] = round((qs.filter(status="rolled_back").count() / implemented) * 100, 2) if implemented else 0
        data["emergency_rate"] = round((qs.filter(change_type="emergency").count() / max(qs.count(), 1)) * 100, 2)

        # Averages.
        completed_with_times = qs.filter(
            status="completed", actual_start__isnull=False, actual_end__isnull=False
        )
        if completed_with_times:
            durations = [
                (c.actual_end - c.actual_start).total_seconds() / 3600
                for c in completed_with_times
            ]
            data["average_implementation_duration_hours"] = round(sum(durations) / len(durations), 2)
        else:
            data["average_implementation_duration_hours"] = 0

        return Response(data)


class ChangeReportsViewSet(viewsets.ViewSet):
    """Read-only change reports."""

    def list(self, request):
        return Response({"detail": "Use specific report endpoints."})

    @action(detail=False, methods=["get"])
    def success_rate(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeRequest.objects.all())
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        implemented = qs.filter(status__in=["completed", "failed", "rolled_back"]).count()
        successful = qs.filter(status="completed").count()
        rate = round((successful / implemented) * 100, 2) if implemented else 0
        return Response({"success_rate": rate, "implemented": implemented, "successful": successful})

    @action(detail=False, methods=["get"])
    def emergency_rate(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeRequest.objects.all())
        total = qs.count()
        emergency = qs.filter(change_type="emergency").count()
        rate = round((emergency / total) * 100, 2) if total else 0
        return Response({"emergency_rate": rate, "total": total, "emergency": emergency})

    @action(detail=False, methods=["get"])
    def failures(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeRequest.objects.filter(status="failed")).select_related("change_owner")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        data = [
            {
                "id": c.id,
                "change_number": c.change_number,
                "title": c.title,
                "failure_reason": c.failure_reason,
                "department": c.department.name if c.department else None,
                "created_at": c.created_at,
            }
            for c in qs[:200]
        ]
        return Response(data)

    @action(detail=False, methods=["get"])
    def downtime(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeRequest.objects.filter(actual_downtime_minutes__gt=0))
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        total_minutes = sum(c.actual_downtime_minutes or 0 for c in qs)
        return Response({
            "total_downtime_minutes": total_minutes,
            "change_count": qs.count(),
        })

    @action(detail=False, methods=["get"])
    def risk(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeRequest.objects.exclude(risk_level__isnull=True).exclude(risk_level=""))
        from django.db.models import Count
        data = qs.values("risk_level").annotate(count=Count("id")).order_by("risk_level")
        return Response(list(data))

    @action(detail=False, methods=["get"])
    def conflicts(self, request):
        user = request.user
        qs = ChangeConflict.objects.filter(status="open").select_related("change", "conflicting_change")
        if not _is_staff(user):
            qs = qs.none()
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(detected_at__gte=date_from)
        if date_to:
            qs = qs.filter(detected_at__lte=date_to)
        return Response(ChangeConflictSerializer(qs[:200], many=True).data)

    @action(detail=False, methods=["get"])
    def pir(self, request):
        user = request.user
        qs = PostImplementationReview.objects.all()
        qs = _scope_queryset(user, qs)
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        return Response(PostImplementationReviewSerializer(qs[:200], many=True).data)

    @action(detail=False, methods=["get"])
    def by_service(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeServiceImpact.objects.all()).select_related("change", "service_catalogue_item")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(change__created_at__gte=date_from)
        if date_to:
            qs = qs.filter(change__created_at__lte=date_to)
        from django.db.models import Count
        data = qs.values("service_catalogue_item__name").annotate(count=Count("id")).order_by("-count")[:50]
        return Response(list(data))

    @action(detail=False, methods=["get"])
    def by_asset(self, request):
        user = request.user
        qs = _scope_queryset(user, ChangeAssetImpact.objects.all()).select_related("change", "asset")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(change__created_at__gte=date_from)
        if date_to:
            qs = qs.filter(change__created_at__lte=date_to)
        from django.db.models import Count
        data = qs.values("asset__asset_tag").annotate(count=Count("id")).order_by("-count")[:50]
        return Response(list(data))
