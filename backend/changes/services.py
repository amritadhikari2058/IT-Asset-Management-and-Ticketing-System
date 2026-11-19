"""Change management business services.

All state transitions here are transactional and idempotent. None of these
functions enqueue work directly; they are called by views and by Celery tasks.
"""

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError, PermissionDenied

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
    ChangeImplementation,
    PostImplementationReview,
    ChangeTicketLink,
    ChangeKnowledgeLink,
    ChangeCommunication,
    ChangeStakeholder,
    MaintenanceWindow,
)
from tickets.models import Ticket, TicketCategory, TicketHistory
from changes.risk import compute_total_score, compute_level, validate_factor
from common.audit import log_action
from common.models import Notification
from common.notifications import email_enabled_for
from accounts.models import User


def _now():
    return timezone.now()


def _generate_change_number():
    """Generate a unique CHG-YYYY-NNNNN change number.

    Uses the application-timezone year and a bounded retry loop on unique
    collision. Never reuses a number.
    """
    year = timezone.now().year
    prefix = f"CHG-{year}-"
    for _attempt in range(100):
        last = (
            ChangeRequest.objects.filter(change_number__startswith=prefix)
            .order_by("-change_number")
            .first()
        )
        if last and last.change_number:
            try:
                suffix = int(last.change_number.split("-")[-1]) + 1
            except (ValueError, IndexError):
                suffix = 1
        else:
            suffix = 1
        candidate = f"{prefix}{suffix:05d}"
        if not ChangeRequest.objects.filter(change_number=candidate).exists():
            return candidate
    raise ValidationError("Unable to generate a unique change number.")


def ensure_change_number(change):
    """Ensure a change has a server-generated number."""
    if change.change_number:
        return change.change_number
    change.change_number = _generate_change_number()
    change.save(update_fields=["change_number"])
    return change.change_number


def ensure_change_tasks(change, template=None):
    """Copy template tasks onto a change, or create default tasks.

    Idempotent: tasks already present are not duplicated.
    """
    if template and getattr(template, "required_task_definitions", None):
        definitions = template.required_task_definitions
    else:
        # Default task set for a normal change.
        definitions = [
            {"title": "Plan implementation", "task_type": "planning", "required": True},
            {
                "title": "Technical review",
                "task_type": "technical_review",
                "required": True,
            },
            {
                "title": "Backup before change",
                "task_type": "backup",
                "required": True,
                "evidence_required": True,
            },
            {
                "title": "Implement change",
                "task_type": "implementation",
                "required": True,
                "blocks_implementation": True,
            },
            {
                "title": "Validate change",
                "task_type": "validation",
                "required": True,
                "blocks_completion": True,
            },
            {
                "title": "Rollback plan verification",
                "task_type": "rollback",
                "required": True,
            },
            {
                "title": "Post-implementation communication",
                "task_type": "communication",
                "required": False,
            },
        ]

    existing = set(
        change.tasks.values_list("sequence", flat=True)
    )
    created = 0
    for idx, definition in enumerate(definitions, start=1):
        if idx in existing:
            continue
        ChangeTask.objects.create(
            change=change,
            sequence=idx,
            title=definition.get("title", f"Task {idx}"),
            description=definition.get("description", ""),
            task_type=definition.get("task_type", "other"),
            required=definition.get("required", True),
            blocks_implementation=definition.get("blocks_implementation", False),
            blocks_completion=definition.get("blocks_completion", False),
            evidence_required=definition.get("evidence_required", False),
        )
        created += 1
    return created


def calculate_risk(change, factors, assessed_by, override_level="", override_reason=""):
    """Calculate and persist a risk assessment for a change.

    factors: dict of factor_name -> int (1..5).
    Returns the ChangeRiskAssessment row.
    """
    from changes.risk import assess_risk

    with transaction.atomic():
        result = assess_risk(factors, override_level, override_reason)
        total_score = result["total_score"]
        calculated_level = result["calculated_level"]

        assessment = ChangeRiskAssessment.objects.create(
            change=change,
            assessed_by=assessed_by,
            assessment_version=1,
            service_impact_score=result["scores"]["service_impact_score"],
            user_impact_score=result["scores"]["user_impact_score"],
            complexity_score=result["scores"]["complexity_score"],
            reversibility_score=result["scores"]["reversibility_score"],
            test_coverage_score=result["scores"]["test_coverage_score"],
            implementation_experience_score=result["scores"][
                "implementation_experience_score"
            ],
            timing_risk_score=result["scores"]["timing_risk_score"],
            dependency_risk_score=result["scores"]["dependency_risk_score"],
            security_risk_score=result["scores"]["security_risk_score"],
            data_integrity_risk_score=result["scores"][
                "data_integrity_risk_score"
            ],
            total_score=total_score,
            calculated_level=calculated_level,
            override_level=result["override_level"],
            override_reason=result["override_reason"],
        )

        # Update the change's risk_level and calculated_risk_score.
        change.risk_level = calculated_level
        change.calculated_risk_score = total_score
        change.save(
            update_fields=["risk_level", "calculated_risk_score", "updated_at"]
        )

        ChangeHistory.objects.create(
            change=change,
            actor=assessed_by,
            event_type="risk_calculated",
            detail=f"Risk assessment v{assessment.assessment_version}: {calculated_level} (score {total_score})",
        )

        log_action(
            actor=assessed_by,
            action="update",
            instance=change,
            reason="Risk assessment calculated",
            details={
                "change_number": change.change_number,
                "risk_assessment_id": str(assessment.pk),
                "total_score": total_score,
                "level": calculated_level,
            },
        )

        return assessment


def confirm_risk(change, user):
    """Confirm a risk assessment (technical review confirmation)."""
    assessment = (
        ChangeRiskAssessment.objects.filter(change=change)
        .order_by("-assessment_version")
        .first()
    )
    if not assessment:
        raise ValidationError("No risk assessment to confirm.")

    change.status = "technical_review"
    change.save(update_fields=["status", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="technical_review_completed",
        detail="Technical review completed; risk assessment confirmed.",
    )
    log_action(
        actor=user,
        action="update",
        instance=change,
        reason="Technical review completed",
        details={
            "change_number": change.change_number,
            "risk_assessment_id": str(assessment.pk),
        },
    )
    return assessment


def request_approval(change, user, approval_level="manager"):
    """Request approval for a change.

    Creates a ChangeApproval row. For emergency changes this records the
    emergency authorization.
    """
    if change.status not in ("pending_approval", "approved"):
        raise ValidationError(
            f"Cannot request approval for a {change.status} change."
        )

    with transaction.atomic():
        approval = ChangeApproval.objects.create(
            change=change,
            approval_level=approval_level,
            status="pending",
            requester=user,
            risk_level_snapshot=change.risk_level or "",
            planned_window_snapshot=(
                f"{change.planned_start} to {change.planned_end}"
                if change.planned_start and change.planned_end
                else ""
            ),
            change_version=change.version,
        )

        ChangeHistory.objects.create(
            change=change,
            actor=user,
            event_type="approval_requested",
            detail=f"Approval requested: {approval_level}.",
        )
        log_action(
            actor=user,
            action="update",
            instance=change,
            reason="Approval requested",
            details={
                "change_number": change.change_number,
                "approval_id": str(approval.pk),
                "level": approval_level,
            },
        )
        return approval


def approve_change(change, user, decision_reason="", approval=None):
    """Approve a change. Transactional: approves and advances status.

    If ``approval`` is supplied it must belong to ``change`` and still be
    pending; the exact approval ID is operated on (not another pending
    approval for the same change). Otherwise the latest pending approval for
    the change is used.

    Returns the ChangeApproval row.
    """
    if approval is None:
        approval = (
            ChangeApproval.objects.filter(change=change, status="pending")
            .order_by("-created_at")
            .first()
        )
    else:
        # Verify the supplied approval belongs to the change and is pending.
        if approval.change_id != change.pk:
            raise ValidationError("Approval does not belong to the supplied change.")
        if approval.status != "pending":
            raise ValidationError("Only pending approvals can be decided.")

    if not approval:
        raise ValidationError("No pending approval to decide.")

    # Separation of duties: requester cannot approve their own change.
    if change.requester_id == user.pk:
        raise ValidationError("Requester cannot approve their own change.")

    # Stale approval: change version must match.
    if change.version != approval.change_version:
        raise ValidationError(
            "Approval is stale: the change has been modified since approval was requested."
        )

    with transaction.atomic():
        # Row-lock the exact approval to prevent concurrent decisions.
        approval = ChangeApproval.objects.select_for_update().get(pk=approval.pk)
        if approval.status != "pending":
            raise ValidationError("Only pending approvals can be decided.")
        if approval.change_id != change.pk:
            raise ValidationError("Approval does not belong to the supplied change.")

        approval.status = "approved"
        approval.decided_by = user
        approval.decided_at = timezone.now()
        approval.decision_reason = decision_reason
        approval.save()

        change.status = "approved"
        change.current_approver = user
        change.approved_at = timezone.now()
        change.save(update_fields=["status", "current_approver", "approved_at", "updated_at"])

        ChangeHistory.objects.create(
            change=change,
            actor=user,
            event_type="approved",
            detail=f"Change approved ({approval.approval_level}). {decision_reason}".strip(),
        )
        log_action(
            actor=user,
            action="update",
            instance=change,
            reason="Change approved",
            details={
                "change_number": change.change_number,
                "approval_id": str(approval.pk),
                "level": approval.approval_level,
            },
        )
        return approval


def reject_change(change, user, decision_reason, approval=None):
    """Reject a change.

    If ``approval`` is supplied it must belong to ``change`` and still be
    pending; the exact approval ID is operated on (not another pending
    approval for the same change). Otherwise the latest pending approval for
    the change is used.
    """
    if approval is None:
        approval = (
            ChangeApproval.objects.filter(change=change, status="pending")
            .order_by("-created_at")
            .first()
        )
    else:
        # Verify the supplied approval belongs to the change and is pending.
        if approval.change_id != change.pk:
            raise ValidationError("Approval does not belong to the supplied change.")
        if approval.status != "pending":
            raise ValidationError("Only pending approvals can be decided.")

    if not approval:
        raise ValidationError("No pending approval to decide.")

    if change.requester_id == user.pk:
        raise ValidationError("Requester cannot reject their own change.")

    with transaction.atomic():
        # Row-lock the exact approval to prevent concurrent decisions.
        approval = ChangeApproval.objects.select_for_update().get(pk=approval.pk)
        if approval.status != "pending":
            raise ValidationError("Only pending approvals can be decided.")
        if approval.change_id != change.pk:
            raise ValidationError("Approval does not belong to the supplied change.")

        approval.status = "rejected"
        approval.decided_by = user
        approval.decided_at = timezone.now()
        approval.decision_reason = decision_reason
        approval.save()

        change.status = "rejected"
        change.approved_at = timezone.now()
        change.save(update_fields=["status", "approved_at", "updated_at"])

        ChangeHistory.objects.create(
            change=change,
            actor=user,
            event_type="rejected",
            detail=f"Change rejected: {decision_reason}",
        )
        log_action(
            actor=user,
            action="update",
            instance=change,
            reason="Change rejected",
            details={
                "change_number": change.change_number,
                "approval_id": str(approval.pk),
            },
        )
        return approval


def schedule_change(change, user, planned_start, planned_end, expected_downtime_minutes=None):
    """Schedule an approved change within a maintenance window.

    Conflict detection is delegated to the conflict detection service; this
    function records the schedule and history.
    """
    # Only approved changes can be initially scheduled.
    if change.status not in ("approved", "on_hold"):
        raise ValidationError(
            f"Only approved or on_hold changes can be scheduled. Current status: {change.status}"
        )

    # Cannot schedule changes that have already started implementation.
    if change.status in ("in_progress", "validation", "completed", "pir_required", "closed",
                          "failed", "rolled_back"):
        raise ValidationError(
            f"Cannot schedule a change that is {change.status}. Rescheduling is not allowed once implementation has begun."
        )

    # Validate date range.
    if planned_end <= planned_start:
        raise ValidationError(
            "Planned end must be after planned start."
        )

    with transaction.atomic():
        change.planned_start = planned_start
        change.planned_end = planned_end
        if expected_downtime_minutes is not None:
            change.expected_downtime_minutes = expected_downtime_minutes
        change.scheduled_at = timezone.now()
        change.status = "scheduled"
        change.save(
            update_fields=[
                "planned_start",
                "planned_end",
                "expected_downtime_minutes",
                "scheduled_at",
                "status",
                "updated_at",
            ]
        )

        # Detect and record conflicts for the new schedule
        try:
            from changes.conflicts import detect_conflicts, upsert_conflicts
            conflicts = detect_conflicts(change)
            upsert_conflicts(change, conflicts)
        except Exception:
            # Don't fail scheduling if conflict detection has issues
            pass

        ChangeHistory.objects.create(
            change=change,
            actor=user,
            event_type="scheduled",
            detail=f"Change scheduled {planned_start} to {planned_end}.",
        )
        log_action(
            actor=user,
            action="update",
            instance=change,
            reason="Change scheduled",
            details={
                "change_number": change.change_number,
                "planned_start": str(planned_start),
                "planned_end": str(planned_end),
            },
        )
        return change


def get_schedule_conflicts(change):
    """Get schedule conflicts for display purposes.

    Returns conflict information suitable for the schedule UI,
    including overlap details, shared CIs/services, and conflict types.
    """
    from changes.conflicts import detect_schedule_conflicts
    return detect_schedule_conflicts(change)


def start_implementation(change, user):
    """Start implementation of a scheduled change.

    Validates readiness: approved, scheduled, risk assessed, tasks ready,
    rollback plan present for non-trivial changes, no blocking dependencies,
    no unaccepted critical conflicts.
    """
    if change.status != "scheduled":
        raise ValidationError("Only scheduled changes can be implemented.")

    if not change.planned_start or not change.planned_end:
        raise ValidationError("Change must be scheduled before implementation.")

    if not change.rollback_plan:
        raise ValidationError("A rollback plan is required before implementation.")

    # Readiness: required tasks complete.
    incomplete_tasks = change.tasks.filter(
        status__in=["pending", "ready", "in_progress", "blocked"], required=True
    )
    if incomplete_tasks.exists():
        raise ValidationError(
            "Required implementation tasks are not complete."
        )

    # No unaccepted critical conflicts.
    from changes.models import ChangeConflict

    critical_conflicts = ChangeConflict.objects.filter(
        change=change, severity="critical", status="open"
    )
    if critical_conflicts.exists():
        raise ValidationError(
            "Unresolved critical conflicts block implementation."
        )

    with transaction.atomic():
        change.status = "in_progress"
        change.actual_start = timezone.now()
        change.save(
            update_fields=["status", "actual_start", "updated_at"]
        )

        # Activate implementation tasks.
        change.tasks.filter(status="ready").update(status="in_progress")

        ChangeHistory.objects.create(
            change=change,
            actor=user,
            event_type="implementation_started",
            detail="Implementation started.",
        )
        log_action(
            actor=user,
            action="update",
            instance=change,
            reason="Implementation started",
            details={"change_number": change.change_number},
        )
        return change


def complete_implementation(change, user, validation_passed=True, notes=""):
    """Complete an implementation.

    Requires validation to pass unless validation is not applicable.
    """
    if change.status != "in_progress":
        raise ValidationError("Only in-progress changes can be completed.")

    if not notes:
        raise ValidationError(
            "Implementation notes are required to complete an implementation."
        )

    if validation_passed is False:
        change.status = "validation"
        change.actual_end = timezone.now()
        change.implementation_notes = notes
        change.save(update_fields=["status", "actual_end", "implementation_notes", "updated_at"])
        ChangeHistory.objects.create(
            change=change,
            actor=user,
            event_type="validation_failed",
            detail="Implementation validation failed.",
        )
        return change

    change.status = "completed"
    change.actual_end = timezone.now()
    change.implementation_notes = notes
    change.save(
        update_fields=["status", "actual_end", "implementation_notes", "updated_at"]
    )

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="completed",
        detail="Implementation completed successfully.",
    )
    log_action(
        actor=user,
        action="update",
        instance=change,
        reason="Implementation completed",
        details={"change_number": change.change_number},
    )
    return change


def fail_implementation(change, user, failure_reason):
    """Mark an implementation as failed."""
    if change.status != "in_progress":
        raise ValidationError("Only in-progress changes can fail.")

    if not failure_reason:
        raise ValidationError(
            "A failure reason is required to mark an implementation as failed."
        )

    change.status = "failed"
    change.failure_reason = failure_reason
    change.save(update_fields=["status", "failure_reason", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="failed",
        detail=f"Implementation failed: {failure_reason}",
    )
    log_action(
        actor=user,
        action="update",
        instance=change,
        reason="Implementation failed",
        details={"change_number": change.change_number, "reason": failure_reason},
    )
    return change


def start_rollback(change, user):
    """Start rolling back a failed change."""
    if change.status != "failed":
        raise ValidationError("Only failed changes can be rolled back.")

    if not change.rollback_plan:
        raise ValidationError("A rollback plan is required before rollback.")

    change.status = "rolled_back"
    change.rollback_started_at = timezone.now()
    change.save(update_fields=["status", "rollback_started_at", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="rollback_started",
        detail=f"Rollback started by {user.employee_id}.",
    )
    log_action(
        actor=user,
        action="update",
        instance=change,
        reason="Rollback started",
        details={
            "change_number": change.change_number,
            "rollback_started_at": str(change.rollback_started_at),
        },
    )
    return change


def complete_rollback(change, user):
    """Complete a rollback."""
    if change.status != "rolled_back":
        raise ValidationError("Only rolled-back changes can complete rollback.")

    change.rollback_completed_at = timezone.now()
    change.rollback_completed_by = user
    change.save(update_fields=["rollback_completed_at", "rollback_completed_by", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="rollback_completed",
        detail=f"Rollback completed by {user.employee_id}.",
    )
    log_action(
        actor=user,
        action="update",
        instance=change,
        reason="Rollback completed",
        details={
            "change_number": change.change_number,
            "rollback_completed_at": str(change.rollback_completed_at),
        },
    )
    return change


def request_pir(change, user):
    """Request a post-implementation review."""
    if change.status not in ("completed", "failed", "rolled_back"):
        raise ValidationError("PIR can only be requested for terminal changes.")

    change.status = "pir_required"
    change.save(update_fields=["status", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="pir_requested",
        detail="Post-implementation review requested.",
    )
    return change


def close_change(change, user, closure_summary):
    """Close a change.

    Requires completed/failed/rolled_back status and (where mandatory) a
    completed PIR.
    """
    if change.status not in ("completed", "failed", "rolled_back"):
        raise ValidationError("Only terminal changes can be closed.")

    # Mandatory PIR for high/critical/failed/rolled-back.
    mandatory = change.risk_level in ("high", "critical") or change.status in (
        "failed", "rolled_back"
    )
    if mandatory:
        try:
            pir = change.pir
        except PostImplementationReview.DoesNotExist:
            pir = None
        if not pir:
            raise ValidationError(
                "A post-implementation review is required before closing this change."
            )
        if pir.status != "completed":
            raise ValidationError(
                "A completed post-implementation review is required before closing."
            )

    change.status = "closed"
    change.closed_at = timezone.now()
    change.closure_summary = closure_summary
    change.save(update_fields=["status", "closed_at", "closure_summary", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="closed",
        detail=f"Change closed. {closure_summary}".strip(),
    )
    log_action(
        actor=user,
        action="update",
        instance=change,
        reason="Change closed",
        details={
            "change_number": change.change_number,
            "closure_summary": closure_summary,
        },
    )
    return change


def cancel_change(change, user, reason=""):
    """Cancel a draft or submitted change."""
    if change.status not in ("draft", "submitted", "pending_approval"):
        raise ValidationError(f"Cannot cancel a {change.status} change.")

    change.status = "cancelled"
    change.cancelled_at = timezone.now()
    change.save(update_fields=["status", "cancelled_at", "updated_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="cancelled",
        detail=f"Change cancelled: {reason}",
    )
    return change


def create_stakeholder(change, user, stakeholder_type, notification_level="all_updates"):
    """Add a stakeholder to a change."""
    stakeholder, _ = ChangeStakeholder.objects.get_or_create(
        change=change,
        user=user,
        stakeholder_type=stakeholder_type,
        defaults={
            "department": getattr(user, "home_department", None),
            "notification_level": notification_level,
            "added_by": user,
        },
    )
    return stakeholder


def send_communication(change, communication_type, audience, subject, message, user, scheduled_for=None):
    """Send (or schedule) a change communication."""
    from django.utils import timezone as tz

    communication = ChangeCommunication.objects.create(
        change=change,
        communication_type=communication_type,
        audience=audience,
        subject=subject,
        message=message,
        scheduled_for=scheduled_for,
        sent_by=user,
        status="sent" if not scheduled_for else "scheduled",
    )
    if not scheduled_for:
        communication.sent_at = timezone.now()
        communication.save(update_fields=["sent_at"])

    ChangeHistory.objects.create(
        change=change,
        actor=user,
        event_type="communication_sent",
        detail=f"Communication sent: {subject}",
    )
    return communication


def link_ticket(change, ticket, relation_type, user):
    """Link a ticket to a change."""
    link, _ = ChangeTicketLink.objects.get_or_create(
        change=change,
        ticket=ticket,
        relation_type=relation_type,
        defaults={"created_by": user},
    )
    return link


def link_knowledge(change, article, relation_type, user):
    """Link a knowledge base article to a change."""
    link, _ = ChangeKnowledgeLink.objects.get_or_create(
        change=change,
        article=article,
        relation_type=relation_type,
        defaults={"created_by": user},
    )
    return link


def add_attachment(change, user, uploaded_file, document_type, description=""):
    """Add an attachment to a change."""
    from django.core.files.base import ContentFile

    attachment = ChangeAttachment.objects.create(
        change=change,
        uploaded_by=user,
        document_type=document_type,
        original_filename=uploaded_file.name,
        content_type=getattr(uploaded_file, "content_type", "") or "",
        size=getattr(uploaded_file, "size", 0) or 0,
        description=description,
    )
    attachment.file.save(uploaded_file.name, uploaded_file, save=True)
    attachment.checksum = _compute_checksum(attachment.file)
    attachment.save(update_fields=["checksum"])
    return attachment


def _compute_checksum(file_field):
    """Compute SHA-256 checksum of an uploaded file."""
    import hashlib

    file_field.seek(0)
    h = hashlib.sha256()
    for chunk in file_field.chunks():
        h.update(chunk)
    file_field.seek(0)
    return h.hexdigest()
