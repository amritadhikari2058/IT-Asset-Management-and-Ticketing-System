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
from django.utils.dateparse import parse_date
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
    BlackoutPeriod,
    ChangeSchedulingException,
)
from changes.services import (
    _check_scheduling_policy,
    schedule_change,
    create_stakeholder,
    send_communication,
    add_attachment as add_change_attachment,
)
from changes.models import (
    ChangeAttachment,
    ChangeStakeholder,
    ChangeCommunication,
    ChangeImplementation,
    PostImplementationReview,
    ChangeTicketLink,
    ChangeKnowledgeLink,
)
from changes.serializers import (
    BlackoutPeriodSerializer,
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
    ChangeSchedulingExceptionSerializer,
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
    complete_pir,
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
    IsChangeManagerOrAdmin,
    IsChangeApprover,
    IsChangeCloser,
    _is_staff,
    _can_manage,
    _can_approve,
)
from changes.conflicts import detect_conflicts, upsert_conflicts, resolve_conflicts_for_change
from common.permissions import IsActiveAuthenticated


def _user_department(user):
    return getattr(getattr(user, "home_department", None), "pk", None)


def _scope_queryset(user, qs):
    """Object-level scope: employees see only their own changes."""
    role = getattr(user, "role", "")
    if _is_staff(user) or getattr(user, "is_superuser", False):
        return qs
    # Employee: own changes only.
    return qs.filter(requester=user)


def _scope_change_related_queryset(user, qs):
    """Scope child records through the requester on their parent change."""
    if _is_staff(user) or getattr(user, "is_superuser", False):
        return qs
    return qs.filter(change__requester=user)


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

# Valid status transitions - authoritative state machine
VALID_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"risk_assessment", "draft", "cancelled", "rejected"},
    "risk_assessment": {"technical_review", "submitted", "cancelled", "rejected"},
    "technical_review": {"pending_approval", "submitted", "cancelled", "rejected"},
    "pending_approval": {"approved", "rejected", "submitted", "cancelled"},
    "approved": {"scheduled", "on_hold", "cancelled"},
    "scheduled": {"in_progress", "on_hold", "approved", "cancelled"},
    "in_progress": {"validation", "failed", "on_hold"},
    "validation": {"completed", "failed", "in_progress", "on_hold"},
    "completed": {"pir_required", "closed"},
    "pir_required": {"closed"},
    "on_hold": {"approved", "scheduled", "in_progress", "cancelled"},
    "rejected": set(),
    "cancelled": set(),
    "failed": {"rolled_back", "closed"},
    "rolled_back": {"closed"},
    "closed": set(),
}

# Fields that become immutable after approval or implementation starts
IMMUTABLE_AFTER_APPROVAL = [
    "change_type", "category", "priority",
]

IMMUTABLE_AFTER_SCHEDULED = [
    "planned_start", "planned_end",
]

IMMUTABLE_AFTER_IMPLEMENTATION = [
    "implementation_plan", "rollback_plan",
]


def _validate_status_transition(change, new_status, user):
    """Validate that a status transition is allowed.

    Returns the validated new status or raises ValidationError.
    """
    current = change.status
    if new_status == current:
        return new_status

    allowed = VALID_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise ValidationError(
            f"Cannot transition from '{current}' to '{new_status}'. "
            f"Allowed transitions: {', '.join(sorted(allowed)) or 'none (terminal state)'}."
        )

    # Terminal states cannot be changed except by cancel/close
    if _is_terminal(current) and new_status not in ("closed",):
        raise ValidationError(f"Cannot modify a {current} change.")

    return new_status


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
        qs = _scope_queryset(self.request.user, qs)

        # Schedule-page filters apply only to list requests. Keeping them
        # out of detail/action lookups prevents query parameters from
        # unexpectedly hiding an otherwise accessible change.
        if self.action == "list":
            params = self.request.query_params

            for param, field in (
                ("status", "status"),
                ("priority", "priority"),
                ("risk", "risk_level"),
            ):
                value = params.get(param)
                if value:
                    qs = qs.filter(**{field: value})

            date_from = params.get("date_from")
            date_to = params.get("date_to")
            parsed_from = None
            parsed_to = None

            if date_from:
                parsed_from = parse_date(date_from)
                if parsed_from is None:
                    raise ValidationError({
                        "date_from": "Use a valid YYYY-MM-DD date."
                    })
                qs = qs.filter(planned_start__date__gte=parsed_from)

            if date_to:
                parsed_to = parse_date(date_to)
                if parsed_to is None:
                    raise ValidationError({
                        "date_to": "Use a valid YYYY-MM-DD date."
                    })
                qs = qs.filter(planned_start__date__lte=parsed_to)

            if parsed_from and parsed_to and parsed_from > parsed_to:
                raise ValidationError({
                    "date_to": "Must be on or after date_from."
                })

            search = params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(change_number__icontains=search)
                    | Q(title__icontains=search)
                )

        return qs
    def get_permissions(self):
        if self.action in ("create",):
            return [permissions.IsAuthenticated()]
        if self.action in ("approve", "reject"):
            return [permissions.IsAuthenticated(), IsChangeApprover()]
        if self.action == "close":
            return [IsChangeCloser()]
        if self.action in (
            "calculate_risk", "confirm_risk", "destroy",
            "schedule", "reschedule",
        ):
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
        
        # Enforce immutability after approval/implementation
        if instance.status in ("approved", "scheduled", "in_progress", "validation",
                                "completed", "pir_required", "closed", "on_hold"):
            # Check immutable fields
            mutable_data = serializer.validated_data if hasattr(serializer, 'validated_data') else {}
            for field in IMMUTABLE_AFTER_APPROVAL:
                if field in mutable_data and mutable_data[field] != getattr(instance, field):
                    raise ValidationError(
                        {field: f"{field} is immutable after approval."}
                    )
            for field in IMMUTABLE_AFTER_SCHEDULED:
                if field in mutable_data and mutable_data[field] != getattr(instance, field):
                    raise ValidationError(
                        {field: f"{field} is immutable after scheduling."}
                    )
            for field in IMMUTABLE_AFTER_IMPLEMENTATION:
                if field in mutable_data and mutable_data[field] != getattr(instance, field):
                    raise ValidationError(
                        {field: f"{field} is immutable after implementation starts."}
                    )

        # Only draft or submitted changes can be edited
        if instance.status not in ("draft", "submitted"):
            raise ValidationError("Only draft or submitted changes can be edited.")
        
        # Stale-version protection handled by frontend; here we just bump version.
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
        
        # Validate required fields before submission
        errors = {}
        if not change.title:
            errors["title"] = "Title is required before submission."
        if not change.change_type:
            errors["change_type"] = "Change type is required before submission."
        if not change.category:
            errors["category"] = "Category is required before submission."
        if not change.priority:
            errors["priority"] = "Priority is required before submission."
        if not change.business_reason:
            errors["business_reason"] = "Business reason is required before submission."
        if not change.implementation_plan:
            errors["implementation_plan"] = "Implementation plan is required before submission."
        if not change.rollback_plan:
            errors["rollback_plan"] = "Rollback plan is required before submission."
        if errors:
            raise ValidationError(errors)
        
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
    def schedule_conflicts(self, request, pk=None):
        """Get schedule conflicts for display in scheduling UI.

        Returns time-based overlaps with other scheduled changes,
        including shared CIs/services and overlap details.
        """
        # Retrieve the object without queryset scoping so we can check
        # permissions even for changes the user doesn't own.
        try:
            change = ChangeRequest.objects.get(pk=pk)
        except ChangeRequest.DoesNotExist:
            raise NotFound(detail="Change not found.")
        if request.user != change.requester and not _is_staff(request.user):
            raise PermissionDenied("You can only view schedule conflicts for your own changes.")
        try:
            from changes.services import get_schedule_conflicts
            conflicts = get_schedule_conflicts(change)
        except Exception:
            conflicts = []

        data = []
        for c in conflicts:
            other = c.get("conflicting_change")
            if not other:
                continue
            data.append({
                "id": other.id,
                "change_number": other.change_number,
                "title": other.title,
                "status": other.status,
                "risk_level": other.risk_level,
                "priority": other.priority,
                "change_type": other.change_type,
                "planned_start": other.planned_start,
                "planned_end": other.planned_end,
                "department": other.department.name if other.department else None,
                "conflict_type": c.get("conflict_type"),
                "severity": c.get("severity"),
                "overlap_start": c.get("overlap_start"),
                "overlap_end": c.get("overlap_end"),
                "overlap_minutes": c.get("overlap_minutes"),
                "shared_assets": c.get("shared_assets", []),
                "shared_services": c.get("shared_services", []),
                "detail_path": f"/api/changes/{other.pk}/",
            })
        return Response(data)

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
        qs = _scope_queryset(self.request.user, qs)

        change_id = self.request.query_params.get("change")
        if change_id is not None:
            try:
                change_id = int(change_id)
            except (TypeError, ValueError):
                return qs.none()

            qs = qs.filter(change_id=change_id)

        return qs

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


# ---------------------------------------------------------------------------
# BlackoutPeriod
# ---------------------------------------------------------------------------


class BlackoutPeriodViewSet(viewsets.ModelViewSet):
    """Blackout periods used by the scheduling policy and conflict engine.

    Read access is available to any authenticated user (the change schedule
    view needs it to display policy feedback). Writes follow the existing
    Change Management authorization model: IT Manager or System Admin only.

    Mounted both under ``/api/changes/blackout-periods/`` and, because the
    frontend calls it directly, at ``/api/blackout-periods/``.
    """

    queryset = BlackoutPeriod.objects.all()
    serializer_class = BlackoutPeriodSerializer

    def get_queryset(self):
        qs = BlackoutPeriod.objects.select_related(
            "scope_department", "scope_service", "created_by")
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        period_type = self.request.query_params.get("period_type")
        if period_type:
            qs = qs.filter(period_type=period_type)
        active = (self.request.query_params.get("active") or "").lower()
        if active in ("1", "true", "yes"):
            qs = qs.filter(status="active")
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


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
        if self.action in ("list", "retrieve", "acknowledge", "accept"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]

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
        return _scope_change_related_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve", "download", "create"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]

    def perform_create(self, serializer):
        data = serializer.validated_data
        change = data.get("change")

        if change is None or not _scope_queryset(
            self.request.user, ChangeRequest.objects.filter(pk=change.pk)
        ).exists():
            raise NotFound("Change request not found.")

        task = data.get("task")
        if task and task.change_id != change.pk:
            raise ValidationError({
                "task": "The selected task does not belong to this change."
            })

        attachment = add_change_attachment(
            change=change,
            user=self.request.user,
            uploaded_file=data["file"],
            document_type=data["document_type"],
            description=data.get("description", ""),
            task=task,
        )

        serializer.instance = attachment

        ChangeHistory.objects.create(
            change=attachment.change,
            actor=self.request.user,
            event_type="attachment_added",
            detail=f"Attachment added: {attachment.original_filename}",
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Download an attachment without exposing its storage URL."""
        import mimetypes
        import os

        from django.http import FileResponse
        from common.attachment_security import (
            add_download_security_headers,
            safe_content_disposition_filename,
        )

        attachment = self.get_object()

        try:
            handle = attachment.file.open("rb")
        except FileNotFoundError:
            return Response(
                {"detail": "File missing from storage."},
                status=status.HTTP_410_GONE,
            )

        name = attachment.original_filename or os.path.basename(
            attachment.file.name
        )
        response = FileResponse(
            handle,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream",
        )
        safe_name = safe_content_disposition_filename(name)
        response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        add_download_security_headers(response)
        return response


# ---------------------------------------------------------------------------
# ChangeStakeholder / ChangeCommunication
# ---------------------------------------------------------------------------


class ChangeStakeholderViewSet(viewsets.ModelViewSet):
    queryset = ChangeStakeholder.objects.all()
    serializer_class = ChangeStakeholderSerializer

    def get_queryset(self):
        qs = ChangeStakeholder.objects.select_related(
            "change", "user", "department", "added_by"
        )
        return _scope_change_related_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]

    def perform_create(self, serializer):
        data = serializer.validated_data
        change = data.get("change")

        if change is None or not _scope_queryset(
            self.request.user, ChangeRequest.objects.filter(pk=change.pk)
        ).exists():
            raise NotFound("Change request not found.")

        stakeholder = create_stakeholder(
            change=change,
            user=data["user"],
            stakeholder_type=data["stakeholder_type"],
            notification_level=data.get("notification_level", "all_updates"),
            added_by=self.request.user,
        )
        serializer.instance = stakeholder


class ChangeCommunicationViewSet(viewsets.ModelViewSet):
    queryset = ChangeCommunication.objects.all()
    serializer_class = ChangeCommunicationSerializer

    def get_queryset(self):
        qs = ChangeCommunication.objects.select_related("change", "sent_by")
        return _scope_change_related_queryset(self.request.user, qs)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsChangeManagerOrAdmin()]

    def perform_create(self, serializer):
        data = serializer.validated_data
        change = data.get("change")

        if change is None or not _scope_queryset(
            self.request.user, ChangeRequest.objects.filter(pk=change.pk)
        ).exists():
            raise NotFound("Change request not found.")

        communication = send_communication(
            change=change,
            communication_type=data["communication_type"],
            audience=data["audience"],
            subject=data["subject"],
            message=data["message"],
            user=self.request.user,
            scheduled_for=data.get("scheduled_for"),
        )
        serializer.instance = communication

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
        return _scope_change_related_queryset(self.request.user, qs)

    def get_permissions(self):
        return [IsActiveAuthenticated()]


class PostImplementationReviewViewSet(viewsets.ModelViewSet):
    queryset = PostImplementationReview.objects.all()
    serializer_class = PostImplementationReviewSerializer

    def get_queryset(self):
        qs = PostImplementationReview.objects.select_related("change", "reviewer", "reviewed_by")
        user = self.request.user
        if not getattr(user, "is_active", False):
            return qs.none()
        qs = _scope_change_related_queryset(user, qs)

        change_id = self.request.query_params.get("change")
        if change_id:
            try:
                qs = qs.filter(change_id=int(change_id))
            except (TypeError, ValueError):
                return qs.none()
        return qs

    def get_permissions(self):
        if self.action == "complete":
            return [IsActiveAuthenticated(), IsChangeManagerOrAdmin()]
        return [IsActiveAuthenticated()]

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        pir = self.get_object()
        pir = complete_pir(pir, request.user)
        return Response(self.get_serializer(pir).data)


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
            # Additional operational metrics
            "scheduled_past_due": qs.filter(
                status__in=["scheduled", "in_progress"],
                planned_end__lt=now,
            ).exclude(status="in_progress").count(),
            "in_progress_overdue": qs.filter(
                status="in_progress",
                planned_end__lt=now,
            ).count(),
            "awaiting_pir": qs.filter(status="pir_required").count(),
            "changes_with_conflicts": ChangeConflict.objects.filter(
                status="open",
                change__status__in=["scheduled", "in_progress", "approved"],
            ).values("change").distinct().count(),
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

        # Upcoming scheduled changes for the schedule view
        upcoming = qs.filter(
            status__in=["scheduled", "in_progress"],
            planned_start__isnull=False,
        ).order_by("planned_start")[:20]
        data["upcoming_changes"] = [
            {
                "id": c.id,
                "change_number": c.change_number,
                "title": c.title,
                "status": c.status,
                "risk_level": c.risk_level,
                "priority": c.priority,
                "change_type": c.change_type,
                "planned_start": c.planned_start,
                "planned_end": c.planned_end,
                "actual_start": c.actual_start,
                "actual_end": c.actual_end,
                "department": c.department.name if c.department else None,
                "detail_path": f"/api/changes/{c.pk}/",
            }
            for c in upcoming
        ]

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
# ---------------------------------------------------------------------------
# Scheduling Exceptions
# ---------------------------------------------------------------------------


class ChangeSchedulingExceptionPermission(permissions.BasePermission):
    """
    Action-specific permissions for ChangeSchedulingException.

    Rules:
    - LIST/RETRIEVE: Any authenticated user with change access
    - CREATE: Any authenticated user (requester can create own exception)
    - UPDATE/PARTIAL_UPDATE: Only ChangeManager or System Admin, AND
      requester cannot approve their own exception
    - DESTROY: Only ChangeManager or System Admin
    """

    def has_permission(self, request, view):
        # Allow authenticated users for list/create
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return request.user.is_authenticated
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        user = request.user
        change = obj.change

        # Read-only actions for authenticated users
        if view.action in ("list", "retrieve"):
            return user.is_authenticated

        # Create: any authenticated user can create
        if view.action == "create":
            return user.is_authenticated

        # Update/partial_update: only managers, and requester cannot approve own exception
        if view.action in ("update", "partial_update"):
            # Must be manager or admin
            if not (user.role in ("it_manager", "system_admin") or _can_manage(user)):
                return False
            # Requester cannot approve or reject their own exception
            if obj.requesting_user == user:
                return False
            # Cannot modify decision fields if already decided
            if obj.decided_by and obj.status != "pending":
                return False
            return True

        # Destroy: only managers
        if view.action == "destroy":
            return user.role in ("it_manager", "system_admin") or _can_manage(user)

        return False


class ChangeSchedulingExceptionViewSet(viewsets.ModelViewSet):
    """Manage scheduling exceptions for changes."""

    queryset = ChangeSchedulingException.objects.all()
    serializer_class = ChangeSchedulingExceptionSerializer
    permission_classes = [ChangeSchedulingExceptionPermission]

    def get_queryset(self):
        qs = ChangeSchedulingException.objects.select_related(
            "change", "blackout_period", "maintenance_window",
            "requesting_user", "decided_by"
        )
        user = self.request.user
        if _is_staff(user) or getattr(user, "is_superuser", False):
            return qs
        # Employees see their own requests and exceptions tied to their changes.
        return qs.filter(Q(requesting_user=user) | Q(change__requester=user))

    def perform_create(self, serializer):
        # Set the requesting user if not set
        if not serializer.validated_data.get("requesting_user"):
            serializer.save(requesting_user=self.request.user)
        else:
            serializer.save()

    def perform_update(self, serializer):
        # Enforce separation of duties: requesters cannot approve/reject
        # their own scheduling exception requests.
        instance = serializer.instance
        if serializer.validated_data.get("status") in ("approved", "rejected"):
            if instance.requesting_user_id == self.request.user.pk:
                raise PermissionDenied(
                    "Requesters cannot approve or reject their own scheduling exception."
                )
            if not (self.request.user.role in ("it_manager", "system_admin") or _can_manage(self.request.user)):
                raise PermissionDenied("IT Manager or System Admin authorization required.")
        # Track who is making the decision and when.
        if serializer.validated_data.get("status") in ("approved", "rejected") and not instance.decided_by:
            serializer.save(
                decided_by=self.request.user,
                decision_timestamp=timezone.now(),
            )
        else:
            serializer.save()
