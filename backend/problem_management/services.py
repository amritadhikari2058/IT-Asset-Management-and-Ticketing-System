"""Problem Management services (PM1 Gate 1).

All status movement happens here — never through ordinary PATCH. Every
transition is atomic, locks the row (select_for_update), enforces the
transition map + optimistic concurrency (409), writes immutable history and
AuditLog, and notifies staff-only recipients via transaction.on_commit.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from common.audit import log_action
from common.models import Notification
from problem_management.permissions import is_it_support

from .models import (
    Problem,
    ProblemAssetLink,
    ProblemConfigurationItemLink,
    ProblemHistory,
    ProblemServiceLink,
    ProblemSoftwareProductLink,
    ProblemTask,
    ProblemTicketLink,
)

HISTORY_DETAIL_LIMIT = 4000
OPEN_TICKET_STATUSES = {
    "open", "in_progress", "waiting_requester", "waiting_third_party",
    "reopened",
}
STAFF_ROLES = {"system_admin", "it_manager", "it_support"}
GOVERNANCE_ROLES = {"system_admin", "it_manager"}


class StaleRecordError(APIException):
    status_code = 409
    default_detail = "Stale record version."
    default_code = "stale_version"


class TransitionConflict(APIException):
    status_code = 409
    default_detail = "Transition conflict."
    default_code = "transition_conflict"


class DuplicateLinkError(APIException):
    status_code = 409
    default_detail = "Active link already exists."
    default_code = "duplicate_link"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _role(user):
    return getattr(user, "role", "") or ""


def _require_staff(user):
    if not (user and user.is_authenticated and user.is_active
            and _role(user) in STAFF_ROLES):
        raise PermissionDenied("Problem Management access denied.")


def _require_governance(user):
    if not (user and user.is_authenticated and user.is_active
            and _role(user) in GOVERNANCE_ROLES):
        raise PermissionDenied("Manager or System Admin role required.")


def _bounded(detail):
    return (detail or "")[:HISTORY_DETAIL_LIMIT]


def record_history(problem, event_type, actor, *, previous_status="",
                   new_status="", detail="", changed_fields=None, task=None):
    return ProblemHistory.objects.create(
        problem=problem,
        task=task,
        actor=actor if (actor and getattr(actor, "pk", None)) else None,
        event_type=event_type,
        previous_status=previous_status or "",
        new_status=new_status or "",
        detail=_bounded(detail),
        changed_fields=list(changed_fields or []),
    )


def notify_staff(user, title, body, entity_type, object_id):
    """Role-aware in-app notification on commit; never to employees."""
    if not (user and user.is_active and _role(user) in STAFF_ROLES):
        return

    def _create():
        Notification.objects.create(
            recipient=user,
            title=str(title)[:255],
            body=body or "",
            entity_type=entity_type or "",
            object_id=str(object_id or ""),
        )

    transaction.on_commit(_create)


def check_version(problem, expected):
    if expected is None:
        return
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        raise ValidationError({"expected_record_version": "Must be an integer."})
    if expected_int != problem.record_version:
        raise StaleRecordError(
            f"Record version {expected_int} is stale; current version is {problem.record_version}."
        )


def _save_problem(problem, update_fields):
    if "updated_at" not in update_fields:
        update_fields = list(update_fields) + ["updated_at"]
    problem.save(update_fields=update_fields)


def _transition(problem, actor, new_status, *, event_type, detail,
                expected=None, at_fields=None, extra_fields=None):
    """Validate + apply one governed status transition (409 on conflicts)."""
    _require_staff(actor)
    with transaction.atomic():
        locked = Problem.objects.select_for_update().get(pk=problem.pk)
        check_version(locked, expected)
        allowed = Problem.PROBLEM_STATUS_TRANSITIONS.get(locked.status, set())
        if new_status not in allowed:
            raise TransitionConflict(
                f"Cannot move {locked.problem_number} from '{locked.status}' to '{new_status}'."
            )
        previous = locked.status
        locked.status = new_status
        fields = ["status"]
        now = timezone.now()
        for field, value in (at_fields or {}).items():
            if value == "now":
                setattr(locked, field, now)
            elif value == "now_if_unset" and getattr(locked, field) is None:
                setattr(locked, field, now)
            fields.append(field)
        for field, value in (extra_fields or {}).items():
            setattr(locked, field, value)
            fields.append(field)
        _save_problem(locked, fields)
        record_history(
            locked, event_type, actor,
            previous_status=previous, new_status=new_status, detail=detail,
        )
        log_action(
            actor=actor, action=f"problem_{event_type}", instance=locked,
            reason=_bounded(detail)[:500],
        )
        problem.refresh_from_db()
        return locked


# ---------------------------------------------------------------------------
# Authoritative readiness check
# ---------------------------------------------------------------------------

def evaluate_problem_readiness(problem):
    """Evaluate if a problem is ready for a status transition.

    Returns (ready: bool, reason: str, blocking_factors: list[str]).
    This is the authoritative readiness check; services must delegate to it,
    not reimplement their own logic.
    """
    blocking = []

    # Must have a problem number
    if not problem.problem_number:
        blocking.append("problem_number_missing")
        return False, "Problem number is required", blocking

    # Open problems need at least one task or evidence
    if problem.is_open and not problem.tasks.exists():
        blocking.append("no_tasks")
        return False, "Open problems must have at least one task", blocking

    if problem.is_open and not problem.evidence.exists():
        blocking.append("no_evidence")
        return False, "Open problems must have at least one evidence record", blocking

    # Status-specific checks
    if problem.status == "investigating" and not problem.root_cause_identified_at:
        blocking.append("root_cause_not_identified")
        return False, "Root cause must be identified before moving from investigating", blocking

    if problem.status == "workaround_available" and not problem.workarounds.exists():
        blocking.append("no_workaround")
        return False, "Workaround must be documented before moving from workaround_available", blocking

    if problem.status == "validation" and not problem.validations.filter(passed=True).exists():
        blocking.append("no_validation_passed")
        return False, "At least one validation must pass before moving from validation", blocking

    if problem.status == "known_error" and not problem.known_error_at:
        blocking.append("known_error_date_missing")
        return False, "Known error date must be set for known_error status", blocking

    ready = len(blocking) == 0
    reason = "Problem is ready for transition" if blocking == [] else "; ".join(
        [f"Blocked: {b}" for b in blocking]
    )
    return ready, reason, blocking


# ---------------------------------------------------------------------------
# Transitions (Gate 1 required set)
# ---------------------------------------------------------------------------

MANUAL_SOURCES = {
    "manual", "ticket", "major_incident", "change_review", "knowledge",
    "supplier", "audit", "other",
}


def create_problem(*, actor, title, description, problem_type="reactive",
                   source="manual", **fields):
    """Create a Draft Problem. Server owns number/status/counters/milestones."""
    _require_staff(actor)
    title = (title or "").strip()
    description = (description or "").strip()
    if not title or not description:
        raise ValidationError({
            "title": "Title is required." if not title else "",
            "description": "Description is required." if not description else "",
        })
    if source not in MANUAL_SOURCES:
        raise ValidationError({"source": "Source is not client-assignable."})

    allowed = {
        "priority", "severity", "impact", "urgency", "criticality",
        "owner", "problem_manager", "assigned_group", "department",
        "service", "category", "subcategory", "environment",
        "detection_method", "target_resolution_date", "problem_type",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    problem = Problem(
        title=title,
        description=description,
        problem_type=problem_type,
        source=source,
        status="draft",
        first_detected_at=timezone.now(),
        created_by=actor,
        **clean,
    )
    try:
        problem.save()
    except DjangoValidationError as exc:
        raise ValidationError(getattr(exc, "message_dict", {"detail": [str(exc)]}))
    record_history(
        problem, "created", actor, new_status="draft",
        detail="Problem created as draft.",
    )
    log_action(actor=actor, action="problem_created", instance=problem)
    if problem.problem_manager_id:
        notify_staff(
            problem.problem_manager, "Problem assigned",
            f"{problem.problem_number} requires your attention.",
            "problem_management.Problem", problem.pk,
        )
    return problem


def submit_problem(*, actor, problem, expected=None):
    _require_staff(actor)
    return _transition(
        problem, actor, "under_review",
        event_type="submitted", detail="Submitted for review.",
        expected=expected,
    )


def accept_problem(*, actor, problem, expected=None):
    _require_governance(actor)
    with transaction.atomic():
        locked = Problem.objects.select_for_update().get(pk=problem.pk)
        check_version(locked, expected)
        if not locked.owner_id:
            raise ValidationError(
                {"owner": "An owner is required before acceptance."}
            )
    accepted = _transition(
        problem, actor, "accepted",
        event_type="accepted", detail="Problem accepted; investigation may start.",
        expected=expected,
    )
    notify_staff(
        accepted.owner, "Problem accepted",
        f"{accepted.problem_number} — {accepted.title}",
        "problem_management.Problem", accepted.pk,
    )
    return accepted


def reject_problem(*, actor, problem, expected=None, reason=""):
    _require_governance(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A rejection reason is required."})
    rejected = _transition(
        problem, actor, "rejected",
        event_type="rejected", detail=f"Rejected: {reason}",
        expected=expected, extra_fields={},
    )
    notify_staff(
        rejected.created_by or rejected.owner, "Problem rejected",
        f"{rejected.problem_number} — {reason[:200]}",
        "problem_management.Problem", rejected.pk,
    )
    return rejected


def start_investigation(*, actor, problem, expected=None):
    _require_staff(actor)
    started = _transition(
        problem, actor, "investigating",
        event_type="investigation_started",
        detail="Investigation started.",
        expected=expected,
        at_fields={"investigation_started_at": "now_if_unset"},
    )
    return started


def cancel_problem(*, actor, problem, expected=None, reason=""):
    _require_governance(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A cancellation reason is required."})
    cancelled = _transition(
        problem, actor, "cancelled",
        event_type="cancelled", detail=f"Cancelled: {reason}",
        expected=expected,
    )
    return cancelled


def reopen_problem(*, actor, problem, expected=None, reason=""):
    _require_governance(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reopen reason is required."})
    reopened = _transition(
        problem, actor, "reopened",
        event_type="reopened", detail=f"Reopened: {reason}",
        expected=expected,
        at_fields={"reopened_at": "now"},
    )
    notify_staff(
        reopened.owner or reopened.problem_manager, "Problem reopened",
        f"{reopened.problem_number} — {reason[:200]}",
        "problem_management.Problem", reopened.pk,
    )
    return reopened


# ---------------------------------------------------------------------------
# Links + counters
# ---------------------------------------------------------------------------

def refresh_problem_counts(problem):
    """Recompute derived counters without bumping record_version."""
    ticket_links = problem.ticket_links.all()
    linked = ticket_links.count()
    open_count = ticket_links.filter(
        ticket__status__in=OPEN_TICKET_STATUSES,
    ).count()
    recurrence = ticket_links.filter(
        relevance="confirmed",
        relationship_type__in=ProblemTicketLink.RECURRENCE_RELATIONSHIP_TYPES,
    ).count()
    Problem.objects.filter(pk=problem.pk).update(
        linked_ticket_count=linked,
        open_ticket_count=open_count,
        recurrence_count=recurrence,
    )
    problem.refresh_from_db()
    return linked, open_count, recurrence


def link_ticket_to_problem(*, actor, problem, ticket, relationship_type="related_incident",
                           relevance="medium", is_primary=False, note="",
                           recurrence_fingerprint=""):
    _require_staff(actor)
    if ProblemTicketLink.objects.filter(
        problem=problem, ticket=ticket, is_deleted=False,
    ).exists():
        raise DuplicateLinkError(
            "This ticket is already linked to the problem."
        )
    link = ProblemTicketLink.objects.create(
        problem=problem,
        ticket=ticket,
        relationship_type=relationship_type,
        relevance=relevance,
        is_primary=bool(is_primary),
        note=note or "",
        recurrence_fingerprint=recurrence_fingerprint or "",
        linked_by=actor,
    )
    refresh_problem_counts(problem)
    record_history(
        problem, "ticket_linked", actor,
        detail=f"Ticket #{ticket.pk} linked as {relationship_type} ({relevance}).",
        changed_fields=["ticket", "relationship_type", "relevance"],
    )
    log_action(
        actor=actor, action="problem_ticket_linked", instance=link,
        reason=f"ticket={ticket.pk}",
    )
    return link


def unlink_ticket_link(*, actor, link):
    _require_staff(actor)
    problem = link.problem
    link.soft_delete(by_user=actor)
    refresh_problem_counts(problem)
    record_history(
        problem, "ticket_unlinked", actor,
        detail=f"Ticket #{link.ticket_id} link removed.",
        changed_fields=["ticket"],
    )
    return link


def add_object_link(*, actor, link_model, problem, target_field, target, **extra):
    """Shared create path for CI/service/asset/software links."""
    _require_staff(actor)
    dup_filter = {"problem": problem, target_field: target, "is_deleted": False}
    if link_model.objects.filter(**dup_filter).exists():
        raise DuplicateLinkError("This object is already linked to the problem.")
    link = link_model(
        problem=problem,
        created_by=actor,
        **{target_field: target},
        **extra,
    )
    try:
        link.full_clean()
    except DjangoValidationError as exc:
        raise ValidationError(getattr(exc, "message_dict", {"detail": [str(exc)]}))
    link.save()
    record_history(
        problem, "linked", actor,
        detail=f"{link._meta.model_name} {target.pk} linked.",
        changed_fields=[target_field],
    )
    return link


def remove_link(*, actor, link, event_detail=""):
    _require_staff(actor)
    link.soft_delete(by_user=actor)
    record_history(
        link.problem, "unlinked", actor,
        detail=event_detail or f"{link._meta.model_name} unlinked.",
        changed_fields=[],
    )
    return link


# ---------------------------------------------------------------------------
# Operational field updates (never status/milestones/summaries/counters)
# ---------------------------------------------------------------------------

UPDATABLE_PROBLEM_FIELDS = {
    "title", "description", "priority", "severity", "impact", "urgency",
    "criticality", "owner", "problem_manager", "assigned_group",
    "department", "service", "category", "subcategory", "environment",
    "detection_method", "target_resolution_date", "next_review_at",
}


def update_problem_fields(*, actor, problem, fields):
    """Apply whitelisted operational field updates (server-owned fields
    stripped defensively even if a serializer regress)."""
    _require_staff(actor)
    clean = {k: v for k, v in fields.items() if k in UPDATABLE_PROBLEM_FIELDS}
    if not clean:
        return problem
    with transaction.atomic():
        locked = Problem.objects.select_for_update().get(pk=problem.pk)
        changed = []
        for key, value in clean.items():
            if getattr(locked, key) != value:
                setattr(locked, key, value)
                changed.append(key)
        if changed:
            _save_problem(locked, changed)
            record_history(
                locked, "other", actor,
                previous_status=locked.status, new_status=locked.status,
                detail=f"Updated fields: {', '.join(sorted(changed))}.",
                changed_fields=sorted(changed),
            )
            log_action(
                actor=actor, action="problem_updated", instance=locked,
                details={"changed_fields": sorted(changed)},
            )
        problem.refresh_from_db()
        return problem


# ---------------------------------------------------------------------------
# Tasks (Gate 1: create/list/update operations; lifecycle actions in Gate 2)
# ---------------------------------------------------------------------------

def next_task_sequence(problem):
    last = (
        ProblemTask.objects.filter(problem=problem)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    return (last or 0) + 1


def create_task(*, actor, problem, title, **fields):
    _require_staff(actor)
    title = (title or "").strip()
    if not title:
        raise ValidationError({"title": "Task title is required."})
    task = ProblemTask(
        problem=problem,
        title=title,
        created_by=actor,
        sequence=fields.pop("sequence", None) or next_task_sequence(problem),
        **fields,
    )
    try:
        task.full_clean()
    except DjangoValidationError as exc:
        raise ValidationError(getattr(exc, "message_dict", {"detail": [str(exc)]}))
    task.save()
    record_history(
        problem, "task_created", actor, task=task,
        detail=f"Task #{task.sequence} '{task.title}' created.",
        changed_fields=["task"],
    )
    notify_staff(
        task.assigned_to, "Problem task assigned",
        f"{problem.problem_number}: {task.title}",
        "problem_management.ProblemTask", task.pk,
    )
    return task


def create_root_cause_why(*, actor, analysis, question_text, answer, **extra):
    """Create a new RootCauseWhy record.

    Rules:
    - parent RCA belongs to accessible Problem
    - parent RCA must be in editable state (draft or in_review)
    - question_text required
    - answer required
    - sequence positive and unique within parent RCA
    - no exactly-five rule
    - only explicit root-cause designation
    - actor server-controlled
    - material changes recorded in History
    - no duplicate sequence values
    - approved/in-review parent blocked
    """
    _require_staff(actor)

    # Parent RCA must be editable
    if analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Whys can only be created/modified when RCA is draft or in_review, got '{analysis.status}'."
        })

    # Check for duplicate sequence
    if RootCauseWhy.objects.filter(analysis=analysis, sequence=extra.get("sequence")).exists():
        raise ValidationError({"analysis": f"Why with sequence {extra.get('sequence')} already exists."})

    why = RootCauseWhy.objects.create(
        analysis=analysis,
        question_text=question_text.strip(),
        answer=answer.strip(),
        sequence=extra.get("sequence", 1),
    )

    # create why_created History
    record_history(
        analysis.problem, "why_created", actor,
        detail=f"Why #{why.sequence} added to RCA '{analysis.pk}'.",
        changed_fields=["why"],
    )

    # AuditLog
    from common.audit import log_action
    log_action(
        actor=actor, action="problem_why_created",
        instance=why,
        reason=f"rca={analysis.pk}, why_sequence={why.sequence}",
    )

    return why


def update_root_cause_why(*, actor, why, question_text=None, answer=None, **extra):
    """Update a RootCauseWhy record.

    Rules:
    - parent RCA must be editable
    - approved/in-review parent blocked
    - only material changes recorded in History
    - no exactly-five requirement
    - sequence uniqueness preserved
    """
    _require_staff(actor)

    if why.analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Whys cannot be modified when RCA is '{why.analysis.status}'."
        })

    updated = False
    if question_text is not None:
        why.question_text = question_text.strip()
        updated = True
    if answer is not None:
        why.answer = answer.strip()
        updated = True
    if updated:
        why.save(update_fields=["question_text", "answer"])

    # create why_updated History if material changes
    if updated:
        record_history(
            why.analysis.problem, "why_updated", actor,
            detail=f"Why #{why.sequence} updated in RCA '{why.analysis.pk}'.",
            changed_fields=["question_text", "answer"],
        )

        # AuditLog
        from common.audit import log_action
        log_action(
            actor=actor, action="problem_why_updated",
            instance=why,
            reason=f"rca={why.analysis.pk}, why_sequence={why.sequence}",
        )

    return why


def delete_root_cause_why(*, actor, why, **extra):
    """Delete a RootCauseWhy record.

    Rules:
    - parent RCA must be in editable state
    - approved/in-review parent blocked
    - deletion blocked after RCA approval/supersession
    - no History deletion
    """
    _require_staff(actor)

    if why.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": f"Whys cannot be deleted when RCA is '{why.analysis.status}'."
        })

    # Do not delete after RCA approval
    if why.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": "Cannot delete Why after RCA has been approved or superseded."
        })

    sequence = why.sequence
    why.delete()

    # create why_deleted History
    record_history(
        why.analysis.problem, "why_deleted", actor,
        detail=f"Why #{sequence} deleted from RCA '{why.analysis.pk}'.",
        changed_fields=["why"],
    )

    # AuditLog
    from common.audit import log_action
    log_action(
        actor=actor, action="problem_why_deleted",
        reason=f"rca={why.analysis.pk}, why_sequence={sequence}",
    )

    return {"deleted": True}


def create_root_cause_factor(*, actor, analysis, category, factor, confidence="medium", **extra):
    """Create a new RootCauseFactor record.

    Rules:
    - parent RCA belongs to accessible Problem
    - parent RCA must be in editable state
    - category allowlisted
    - factor required
    - confidence allowlisted
    - no exactly-five rule
    - only explicit root-cause designation
    - actor server-controlled
    - material changes recorded in History
    - no duplicate factor within category
    - approved/in-review parent blocked
    """
    _require_staff(actor)

    # Parent RCA must be editable
    if analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Factors can only be created/modified when RCA is draft or in_review, got '{analysis.status}'."
        })

    # Check for duplicate factor within category
    if RootCauseFactor.objects.filter(analysis=analysis, category=category).exists():
        raise ValidationError({
            "analysis": f"A factor with category '{category}' already exists."
        })

    factor_rec = RootCauseFactor.objects.create(
        analysis=analysis,
        category=category,
        factor=factor.strip(),
        confidence=confidence,
    )

    # create factor_created History
    record_history(
        analysis.problem, "factor_created", actor,
        detail=f"Factor added to RCA '{analysis.pk}': {factor[:100]}.",
        changed_fields=["factor"],
    )

    # AuditLog
    from common.audit import log_action
    log_action(
        actor=actor, action="problem_factor_created",
        instance=factor_rec,
        reason=f"rca={analysis.pk}, category={category}",
    )

    return factor_rec


def update_root_cause_factor(*, actor, factor, category=None, factor_text=None, confidence=None, **extra):
    """Update a RootCauseFactor record.

    Rules:
    - parent RCA must be editable
    - approved/in-review parent blocked
    - only material changes recorded in History
    - category and factor cannot both be empty
    """
    _require_staff(actor)

    if factor.analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Factors cannot be modified when RCA is '{factor.analysis.status}'."
        })

    updated = False
    if category is not None:
        factor.category = category
        updated = True
    if factor_text is not None:
        factor.factor = factor_text.strip()
        updated = True
    if confidence is not None:
        factor.confidence = confidence
        updated = True
    if updated:
        factor.save(update_fields=["category", "factor", "confidence"])

    # create factor_updated History if material changes
    if updated:
        record_history(
            factor.analysis.problem, "factor_updated", actor,
            detail=f"Factor updated in RCA '{factor.analysis.pk}'.",
            changed_fields=["category", "factor", "confidence"],
        )

        # AuditLog
        from common.audit import log_action
        log_action(
            actor=actor, action="problem_factor_updated",
            instance=factor,
            reason=f"rca={factor.analysis.pk}",
        )

    return factor


def delete_root_cause_factor(*, actor, factor, **extra):
    """Delete a RootCauseFactor record.

    Rules:
    - parent RCA must be in editable state
    - approved/in-review parent blocked
    - deletion blocked after RCA approval/supersession
    - no History deletion
    """
    _require_staff(actor)

    if factor.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": f"Factors cannot be deleted when RCA is '{factor.analysis.status}'."
        })

    category = factor.category
    factor.delete()

    # create factor_deleted History
    record_history(
        factor.analysis.problem, "factor_deleted", actor,
        detail=f"Factor '{category}' deleted from RCA '{factor.analysis.pk}'.",
        changed_fields=["factor"],
    )

    # AuditLog
    from common.audit import log_action
    log_action(
        actor=actor, action="problem_factor_deleted",
        reason=f"rca={factor.analysis.pk}, category={category}",
    )

    return {"deleted": True}


# ---------------------------------------------------------------------------
# Five Whys and Factor services
# ---------------------------------------------------------------------------

def create_root_cause_why(*, actor, analysis, question_text, answer, **extra):
    _require_staff(actor)

    if analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Whys can only be created/modified when RCA is draft or in_review, got '{analysis.status}'."
        })

    if RootCauseWhy.objects.filter(analysis=analysis, sequence=extra.get("sequence")).exists():
        raise ValidationError({"analysis": f"Why with sequence {extra.get('sequence')} already exists."})

    why = RootCauseWhy.objects.create(
        analysis=analysis,
        question_text=question_text.strip(),
        answer=answer.strip(),
        sequence=extra.get("sequence", 1),
    )

    record_history(
        analysis.problem, "why_created", actor,
        detail=f"Why #{why.sequence} added to RCA '{analysis.pk}'.",
        changed_fields=["why"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_why_created",
        instance=why,
        reason=f"rca={analysis.pk}, why_sequence={why.sequence}",
    )

    return why


def update_root_cause_why(*, actor, why, question_text=None, answer=None, **extra):
    _require_staff(actor)

    if why.analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Whys cannot be modified when RCA is '{why.analysis.status}'."
        })

    updated = False
    if question_text is not None:
        why.question_text = question_text.strip()
        updated = True
    if answer is not None:
        why.answer = answer.strip()
        updated = True
    if updated:
        why.save(update_fields=["question_text", "answer"])

    if updated:
        record_history(
            why.analysis.problem, "why_updated", actor,
            detail=f"Why #{why.sequence} updated in RCA '{why.analysis.pk}'.",
            changed_fields=["question_text", "answer"],
        )

        from common.audit import log_action
        log_action(
            actor=actor, action="problem_why_updated",
            instance=why,
            reason=f"rca={why.analysis.pk}, why_sequence={why.sequence}",
        )

    return why


def delete_root_cause_why(*, actor, why, **extra):
    _require_staff(actor)

    if why.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": f"Whys cannot be deleted when RCA is '{why.analysis.status}'."
        })

    if why.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": "Cannot delete Why after RCA has been approved or superseded."
        })

    sequence = why.sequence
    why.delete()

    record_history(
        why.analysis.problem, "why_deleted", actor,
        detail=f"Why #{sequence} deleted from RCA '{why.analysis.pk}'.",
        changed_fields=["why"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_why_deleted",
        reason=f"rca={why.analysis.pk}, why_sequence={sequence}",
    )

    return {"deleted": True}


def create_root_cause_factor(*, actor, analysis, category, factor, confidence="medium", **extra):
    _require_staff(actor)

    if analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Factors can only be created/modified when RCA is draft or in_review, got '{analysis.status}'."
        })

    if RootCauseFactor.objects.filter(analysis=analysis, category=category).exists():
        raise ValidationError({
            "analysis": f"A factor with category '{category}' already exists."
        })

    factor_rec = RootCauseFactor.objects.create(
        analysis=analysis,
        category=category,
        factor=factor.strip(),
        confidence=confidence,
    )

    record_history(
        analysis.problem, "factor_created", actor,
        detail=f"Factor added to RCA '{analysis.pk}': {factor[:100]}..",
        changed_fields=["factor"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_factor_created",
        instance=factor_rec,
        reason=f"rca={analysis.pk}, category={category}",
    )

    return factor_rec


def update_root_cause_factor(*, actor, factor, category=None, factor_text=None, confidence=None, **extra):
    _require_staff(actor)

    if factor.analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Factors cannot be modified when RCA is '{factor.analysis.status}'."
        })

    updated = False
    if category is not None:
        factor.category = category
        updated = True
    if factor_text is not None:
        factor.factor = factor_text.strip()
        updated = True
    if confidence is not None:
        factor.confidence = confidence
        updated = True
    if updated:
        factor.save(update_fields=["category", "factor", "confidence"])

    if updated:
        record_history(
            factor.analysis.problem, "factor_updated", actor,
            detail=f"Factor updated in RCA '{factor.analysis.pk}'.",
            changed_fields=["category", "factor", "confidence"],
        )

        from common.audit import log_action
        log_action(
            actor=actor, action="problem_factor_updated",
            instance=factor,
            reason=f"rca={factor.analysis.pk}",
        )

    return factor


def delete_root_cause_factor(*, actor, factor, **extra):
    _require_staff(actor)

    if factor.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": f"Factors cannot be deleted when RCA is '{factor.analysis.status}'."
        })

    category = factor.category
    factor.delete()

    record_history(
        factor.analysis.problem, "factor_deleted", actor,
        detail=f"Factor '{category}' deleted from RCA '{factor.analysis.pk}'.",
        changed_fields=["factor"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_factor_deleted",
        reason=f"rca={factor.analysis.pk}, category={category}",
    )

    return {"deleted": True}

# ---------------------------------------------------------------------------
# Timeline service
# ---------------------------------------------------------------------------

def create_problem_timeline_event(*, actor, problem, occurred_at, source,
                                  event_type, title, description='', **extra):
    from datetime import timezone as dt_timezone
    from django.utils import timezone as dj_timezone

    _require_staff(actor)

    # Validate source allowlist
    allowed_sources = ('manual', 'ticket', 'major_incident', 'change_review',
                       'knowledge', 'monitoring', 'cmdb')
    if source not in allowed_sources:
        raise ValidationError({'source': f'Source {source} not in allowlist.'})

    # occurred_at must be timezone-aware
    if isinstance(occurred_at, dj_timezone.datetime) and dj_timezone.is_naive(occurred_at):
        raise ValidationError({'occurred_at': 'occurred_at must be timezone-aware.'})

    # Server-set recorded_at
    recorded_at = dj_timezone.now()

    timeline = ProblemTimelineEvent.objects.create(
        problem=problem,
        occurred_at=occurred_at,
        source=source,
        event_type=event_type,
        title=title,
        description=(description or '')[:4000],
        recorded_by=actor,
        recorded_at=recorded_at,
        **extra,
    )

    return timeline

# ---------------------------------------------------------------------------
# Action services
# ---------------------------------------------------------------------------

def create_problem_action(*, actor, problem, title, description='', due_date=None,
                          related_task=None, **extra):
    from django.utils import timezone as dj_timezone
    _require_staff(actor)

    if not title:
        raise ValidationError({'title': 'Title is required.'})

    if due_date and due_date < dj_timezone.now():
        raise ValidationError({'due_date': 'Due date must be in the future.'})

    action = ProblemAction.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or '').strip(),
        action_type=extra.get('action_type', 'corrective'),
        status='planned',
        due_at=due_date,
        assigned_to=extra.get('assigned_to'),
        root_cause_analysis=extra.get('root_cause_analysis'),
        validation_status=extra.get('validation_status'),
        created_by=actor,
    )

    record_history(
        problem, 'action_created', actor,
        detail=f'Action \"{action.pk}\" created: {title[:200]}.',
        changed_fields=['action'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_created',
        instance=action,
        reason=f'action={action.pk}, title={title[:200]}',
    )

    return action


def approve_problem_action(*, actor, action, **extra):
    _require_governance(actor)

    if action.status not in ('planned',):
        raise ValidationError({'action': f'Action can only be approved from planned state, got \"{action.status}\".'})


def start_problem_action(*, actor, action, **extra):
    _require_staff(actor)


def complete_problem_action(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'completed'
    action.completed_at = timezone.now()
    action.completed_by = actor
    action.save(update_fields=['status', 'completed_at', 'completed_by'])

    record_history(
        action.problem, 'action_completed', actor,
        detail=f'Action \"{action.title}\" completed.',
        changed_fields=['status', 'completed_at'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_completed',
        instance=action,
        reason=f'action={action.pk} completed by {actor.id}',
    )

    return action


def validate_problem_action(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'verified'
    action.save(update_fields=['status'])

    record_history(
        action.problem, 'action_validated', actor,
        detail=f'Action \"{action.title}\" validated.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_validated',
        instance=action,
        reason=f'action={action.pk} validated by {actor.id}',
    )

    return action


def mark_problem_action_ineffective(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'ineffective'
    action.save(update_fields=['status'])

    record_history(
        action.problem, 'action_ineffective', actor,
        detail=f'Action \"{action.title}\" marked ineffective.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_ineffective',
        instance=action,
        reason=f'action={action.pk} marked ineffective',
    )

    return action


def cancel_problem_action(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'cancelled'
    action.save(update_fields=['status'])

    record_history(
        action.problem, 'action_cancelled', actor,
        detail=f'Action \"{action.title}\" cancelled.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_cancelled',
        instance=action,
        reason=f'action={action.pk} cancelled by {actor.id}',
    )

    return action

# ---------------------------------------------------------------------------
# Workaround services
# ---------------------------------------------------------------------------

def create_problem_workaround(*, actor, problem, title, description='',
                              workaround_type='temporary', steps='', **extra):
    _require_staff(actor)

    if not title:
        raise ValidationError({'title': 'Title is required.'})

    if not steps:
        raise ValidationError({'steps': 'Steps are required.'})

    # High/critical risk requires limitations
    risk = extra.get('risk', 'low')
    if risk in ('high', 'critical') and extra.get('limitations') is None:
        raise ValidationError({'limitations': 'High/critical risk requires limitations.'})

    workaround = ProblemWorkaround.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or '').strip(),
        workaround_type=workaround_type,
        steps=steps.strip(),
        effectiveness_rating=extra.get('effectiveness_rating', 3),
        implemented_at=extra.get('implemented_at'),
        resolved_at=extra.get('resolved_at'),
        implemented_by=actor,
    )

    record_history(
        problem, 'workaround_created', actor,
        detail=f'Workaround \"{workaround.title}\" created.',
        changed_fields=['workaround'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_created',
        instance=workaround,
        reason=f'workaround={workaround.pk}, title={title[:200]}',
    )

    return workaround


def submit_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    if workaround.status != 'draft':
        raise ValidationError({'workaround': f'Only draft workarounds can be submitted.'})


def approve_problem_workaround(*, actor, workaround, **extra):
    _require_governance(actor)

    if workaround.status != 'draft':
        raise ValidationError({'workaround': f'Only draft workarounds can be approved.'})


def publish_problem_workaround(*, actor, workaround, **extra):
    _require_governance(actor)

    if workaround.status != 'approved':
        raise ValidationError({'workaround': f'Only approved workarounds can be published.'})


def expire_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    workaround.status = 'expired'
    workaround.save(update_fields=['status'])

    record_history(
        workaround.problem, 'workaround_expired', actor,
        detail=f'Workaround \"{workaround.title}\" expired.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_expired',
        instance=workaround,
        reason=f'workaround={workaround.pk} expired',
    )

    return workaround



# ---------------------------------------------------------------------------
# Evidence services
# ---------------------------------------------------------------------------

def create_problem_evidence(*, actor, problem, title, evidence_type,
                            description="", file=None, **extra):
    _require_staff(actor)
    from django.utils.crypto import get_random_string
    from datetime import datetime
    
    # Derive original filename safely
    original_name = ""
    if file:
        original_name = getattr(file, 'name', '') or ''
        original_name = original_name.split('/')[-1].split('\\')[-1]
    
    # Derive content type safely
    content_type = ""
    if file:
        content_type = getattr(file, 'content_type', '') or ''
    
    # Calculate size
    size = 0
    if file:
        size = getattr(file, 'size', 0) or 0
    
    # Calculate SHA-256 checksum server-side
    checksum = ""
    if file:
        import hashlib
        content_bytes = file.read()
        checksum = hashlib.sha256(content_bytes).hexdigest()
        file.seek(0)
    
    # Generate secure randomized upload path
    import os
    upload_path = f"problem_evidence/{datetime.now().strftime('%Y/%m/%d')}/{get_random_string(12)}_{os.path.basename(original_name)}" if original_name else f"problem_evidence/{get_random_string(20)}"
    
    evidence = ProblemEvidence.objects.create(
        problem=problem,
        title=title.strip(),
        evidence_type=evidence_type,
        description=(description or "").strip(),
        file=file,
        uploaded_by=actor,
        created_at=datetime.now(),
    )
    
    record_history(
        problem, "evidence_added", actor,
        detail=f"Evidence '{evidence.pk}' added: {title[:100]}.",
        changed_fields=["evidence"],
    )
    
    from common.audit import log_action
    log_action(
        actor=actor, action="problem_evidence_created",
        instance=evidence,
        reason=f"evidence={evidence.pk}, title={title[:200]}",
    )
    
    return evidence


def archive_problem_evidence(*, actor, evidence, reason=""):
    _require_staff(actor)
    if evidence.is_archived:
        raise ValidationError({"detail": "Evidence is already archived."})
    evidence.is_archived = True
    evidence.save(update_fields=["is_archived", "archived_at"])
    record_history(
        evidence.problem, "evidence_archived", actor,
        detail=f"Evidence '{evidence.pk}' archived: {reason or 'no reason given'}.",
        changed_fields=["is_archived"],
    )
    return evidence

# ---------------------------------------------------------------------------
# RCA services
# ---------------------------------------------------------------------------

def create_root_cause_analysis(*, actor, problem, title, description="",
                               analysis_type="five_whys", **extra):
    _require_staff(actor)
    if problem.status not in ("accepted", "investigating"):
        raise ValidationError({"problem": f"Problem must be accepted or investigating."})
    analysis = RootCauseAnalysis.objects.create(
        problem=problem, title=title.strip(), description=(description or "").strip(),
        analysis_type=analysis_type, status="draft", created_by=actor, version=1,
    )
    record_history(problem, "rca_created", actor,
        detail=f"RCA '{analysis.pk}' created: {title[:100]}.",
        changed_fields=["rca"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_created",
        instance=analysis, reason=f"rca={analysis.pk}, problem={problem.pk}")
    return analysis


def submit_root_cause_analysis(*, actor, analysis, **extra):
    _require_staff(actor)
    if analysis.status != "draft":
        raise ValidationError({"analysis": f"Only draft RCA can be submitted."})
    analysis.status = "in_review"
    analysis.save(update_fields=["status"])
    record_history(analysis.problem, "rca_submitted", actor,
        detail=f"RCA '{analysis.pk}' submitted for review.",
        changed_fields=["status"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_submitted",
        instance=analysis, reason=f"rca={analysis.pk} submitted by {actor.id}")
    return analysis


def approve_root_cause_analysis(*, actor, analysis, **extra):
    _require_governance(actor)
    if analysis.status != "in_review":
        raise ValidationError({"analysis": f"Only in_review RCA can be approved."})
    if analysis.created_by_id == actor.id:
        raise ValidationError({"analysis": "Creator cannot approve own RCA."})
    analysis.status = "approved"
    analysis.approved_by = actor
    analysis.approved_at = datetime.now()
    analysis.save(update_fields=["status", "approved_by", "approved_at"])
    record_history(analysis.problem, "rca_approved", actor,
        detail=f"RCA '{analysis.pk}' approved.",
        changed_fields=["status", "root_cause"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_approved",
        instance=analysis, reason=f"rca={analysis.pk} approved by {actor.id}")
    return analysis


def reject_root_cause_analysis(*, actor, analysis, reason="", **extra):
    _require_governance(actor)
    if analysis.status not in ("in_review", "approved"):
        raise ValidationError({"analysis": f"Cannot reject RCA in '{analysis.status}' state."})
    if not reason:
        raise ValidationError({"reason": "A rejection reason is required."})
    analysis.status = "rejected"
    analysis.save(update_fields=["status"])
    record_history(analysis.problem, "rca_rejected", actor,
        detail=f"RCA '{analysis.pk}' rejected: {reason[:200]}.",
        changed_fields=["status", "rejection_reason"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_rejected",
        instance=analysis, reason=f"rca={analysis.pk} rejected by {actor.id}, reason={reason[:200]}")
    return analysis
def retire_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    workaround.status = 'retired'
    workaround.save(update_fields=['status'])

    record_history(
        workaround.problem, 'workaround_retired', actor,
        detail=f'Workaround \"{workaround.title}\" retired.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_retired',
        instance=workaround,
        reason=f'workaround={workaround.pk} retired',
    )

    return workaround


# ---------------------------------------------------------------------------
# Gate 1 mutation service: soft delete a Problem
# ---------------------------------------------------------------------------
def soft_delete_problem(*, actor, problem, reason=""):
    """Soft-delete a Problem instance.

    Policy:
    - Support role: denied (Http403)
    - Manager (IT Manager / System Admin): allowed
    - Active links (ticket/CI/service/asset/software) block deletion → 400
    - On success: sets problem.is_deleted=True, creates History "soft_deleted"
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    # Role enforcement
    if is_it_support(actor):
        raise PermissionDenied("Support role cannot soft-delete problems.")

    # Check for active links that would block soft deletion
    active_links = (
        problem.ticket_links.filter(is_deleted=False).count()
        + problem.ci_links.filter(is_deleted=False).count()
        + problem.service_links.filter(is_deleted=False).count()
        + problem.asset_links.filter(is_deleted=False).count()
        + problem.software_links.filter(is_deleted=False).count()
    )
    if active_links > 0:
        raise ValidationError(
            {"non_field_errors": ["Cannot soft-delete Problem with active links."]}
        )

    # Perform soft delete via the model method
    problem.soft_delete(by_user=actor, reason=reason or "")

    # Record history event
    from problem_management.models import ProblemHistory

    ProblemHistory.objects.create(
        problem=problem,
        event_type="soft_deleted",
        actor=actor,
        previous_status=problem.status,
        new_status=problem.status,
        detail=f"Problem soft-deleted: {reason or ''}",
        changed_fields=["status"],
    )

    return problem