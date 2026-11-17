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
        raise DjangoValidationError({"expected_record_version": "Must be an integer."})
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
    """Read-only readiness evaluation for resolution/closure.

    Returns the authoritative contract required by Gate 2B:
    {
        "ready_for_resolution": False,
        "ready_for_closure": False,
        "blockers": [...],
        "warnings": [],
        "counts": {
            "open_blocking_tasks": 0,
            "open_required_actions": 0,
            "failed_validations": 0,
            "open_critical_tickets": 0,
            "active_exceptions": 0,
        },
    }
    """
    blockers = []

    def add_blocker(code, message, severity="high"):
        if any(b["code"] == code for b in blockers):
            return
        blockers.append({"code": code, "message": message, "severity": severity})

    # Counts (bounded/simple aggregates). Optional integrations guarded.
    try:
        open_blocking_tasks = problem.tasks.filter(is_deleted=False).exclude(
            status__in=["completed", "cancelled", "skipped"],
        ).filter(blocks_resolution=True).count()
    except Exception:
        open_blocking_tasks = 0

    try:
        actions_qs = problem.actions.filter(is_deleted=False)
        open_required_actions = actions_qs.exclude(
            status__in=["completed", "validated", "verified", "closed", "cancelled", "ineffective"],
        ).count()
    except Exception:
        open_required_actions = 0

    try:
        failed_validations = problem.validations.filter(is_deleted=False).filter(
            passed=False,
        ).exclude(status__in=["planned", "in_progress", "inconclusive", "cancelled"]).count()
    except Exception:
        try:
            failed_validations = problem.validations.filter(is_deleted=False, passed=False).count()
        except Exception:
            failed_validations = 0

    open_critical_tickets = 0
    try:
        if hasattr(problem, "ticket_links"):
            open_critical_tickets = problem.ticket_links.filter(is_deleted=False).filter(
                ticket__status__in=OPEN_TICKET_STATUSES,
            ).filter(
                ticket__priority__in=["critical", "high"],
            ).count()
    except Exception:
        open_critical_tickets = 0

    active_exceptions = 0
    try:
        now = timezone.now()
        ex_qs = problem.exceptions.filter(is_deleted=False)
        if hasattr(problem.exceptions.model, "status"):
            active_exceptions = ex_qs.filter(status__in=["approved", "active"]).count()
        else:
            active_exceptions = ex_qs.count()
        # treat expired as inactive when expires_at present
        active_exceptions = ex_qs.filter(
            **({"status__in": ["approved", "active"]} if hasattr(problem.exceptions.model, "status") else {})
        ).exclude(expires_at__lt=now).count() if hasattr(problem.exceptions.model, "expires_at") else active_exceptions
    except Exception:
        active_exceptions = 0

    counts = {
        "open_blocking_tasks": int(open_blocking_tasks or 0),
        "open_required_actions": int(open_required_actions or 0),
        "failed_validations": int(failed_validations or 0),
        "open_critical_tickets": int(open_critical_tickets or 0),
        "active_exceptions": int(active_exceptions or 0),
    }

    # Deterministic blocker evaluation (resolution/closure gates)
    # Approved RCA required unless approved unknown-root-cause exception exists.
    has_approved_rca = False
    try:
        has_approved_rca = problem.root_cause_analyses.filter(
            is_deleted=False, status="approved",
        ).exists()
    except Exception:
        has_approved_rca = False

    has_unknown_rca_exception = False
    try:
        ex_qs = problem.exceptions.filter(is_deleted=False)
        if hasattr(problem.exceptions.model, "status"):
            ex_qs = ex_qs.filter(status__in=["approved", "active"])
        now = timezone.now()
        if hasattr(problem.exceptions.model, "expires_at"):
            ex_qs = ex_qs.exclude(expires_at__lt=now)
        has_unknown_rca_exception = ex_qs.filter(
            exception_type__in=["unknown_root_cause", "unknown-root-cause", "rca_unknown"],
        ).exists()
    except Exception:
        has_unknown_rca_exception = False

    if not has_approved_rca and not has_unknown_rca_exception:
        add_blocker(
            "ROOT_CAUSE_MISSING",
            "An approved Root Cause Analysis is required.",
            "high",
        )

    if counts["open_blocking_tasks"] > 0:
        add_blocker(
            "OPEN_BLOCKING_TASKS",
            "Blocking tasks must be completed before transition.",
            "high",
        )
    if counts["open_required_actions"] > 0:
        add_blocker(
            "OPEN_REQUIRED_ACTIONS",
            "Required actions must be completed before transition.",
            "high",
        )
    if counts["failed_validations"] > 0:
        add_blocker(
            "FAILED_VALIDATIONS",
            "Failed validations must be resolved before transition.",
            "high",
        )
    if counts["open_critical_tickets"] > 0:
        add_blocker(
            "OPEN_CRITICAL_TICKETS",
            "Critical linked tickets remain open.",
            "high",
        )

    # Deterministic order by code for known blockers
    blocker_order = [
        "ROOT_CAUSE_MISSING",
        "OPEN_BLOCKING_TASKS",
        "OPEN_REQUIRED_ACTIONS",
        "FAILED_VALIDATIONS",
        "OPEN_CRITICAL_TICKETS",
    ]
    order_index = {c: i for i, c in enumerate(blocker_order)}
    blockers = sorted(blockers, key=lambda b: (order_index.get(b["code"], 999), b["code"]))

    ready_for_resolution = len(blockers) == 0
    ready_for_closure = ready_for_resolution and counts["open_critical_tickets"] == 0

    return {
        "ready_for_resolution": bool(ready_for_resolution),
        "ready_for_closure": bool(ready_for_closure),
        "blockers": blockers,
        "warnings": [],
        "counts": counts,
    }


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


def create_problem_task(*, actor, problem, title, **fields):
    _require_staff(actor)
    title = (title or "").strip()
    if not title:
        raise ValidationError({"title": "Task title is required."})
    # Never trust client-controlled status/sequence/completion fields on create.
    for forbidden in ("status", "sequence", "started_at", "completed_at", "completed_by", "completion_note", "is_deleted"):
        fields.pop(forbidden, None)
    with transaction.atomic():
        locked_problem = Problem.objects.select_for_update().get(pk=problem.pk)
        task = ProblemTask(
            problem=locked_problem,
            title=title,
            created_by=actor,
            sequence=next_task_sequence(locked_problem),
            **fields,
        )
        try:
            task.full_clean()
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"detail": [str(exc)]}))
        task.save()
        record_history(
            locked_problem, "task_created", actor, task=task,
            detail=f"Task #{task.sequence} '{task.title}' created.",
            changed_fields=["task"],
        )
        log_action(
            actor=actor, action="problem_task_created", instance=task,
            details={"problem_id": locked_problem.pk, "sequence": task.sequence},
        )
        notify_staff(
            task.assigned_to, "Problem task assigned",
            f"{locked_problem.problem_number}: {task.title}",
            "problem_management.ProblemTask", task.pk,
        )
        return task


def create_task(*, actor, problem, title, **fields):
    """Compatibility alias for Gate 1 service naming."""
    return create_problem_task(actor=actor, problem=problem, title=title, **fields)


# ---------------------------------------------------------------------------
# Five Whys and Factor services
# ---------------------------------------------------------------------------

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
        detail=f"Factor added to RCA '{analysis.pk}': {factor[:100]}..",
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

    # Do not delete after RCA approval
    if factor.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": "Cannot delete Factor after RCA has been approved or superseded."
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
        detail=f'Action "{action.title}" created: {title[:200]}.',
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
        raise ValidationError({'action': f'Action can only be approved from planned state, got "{action.status}".'})


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
        detail=f'Action "{action.title}" completed.',
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
        detail=f'Action "{action.title}" validated.',
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
        detail=f'Action "{action.title}" marked ineffective.',
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
        detail=f'Action "{action.title}" cancelled.',
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
        detail=f'Workaround "{workaround.title}" created.',
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
        detail=f'Workaround "{workaround.title}" expired.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_expired',
        instance=workaround,
        reason=f'workaround={workaround.pk} expired',
    )

    return workaround


def retire_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    workaround.status = 'retired'
    workaround.save(update_fields=['status'])

    record_history(
        workaround.problem, 'workaround_retired', actor,
        detail=f'Workaround "{workaround.title}" retired.',
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
    analysis.approved_at = timezone.now()
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


def supersede_root_cause_analysis(*, actor, analysis, **extra):
    """Supersede an approved RCA with a replacement belonging to the same Problem."""
    _require_governance(actor)
    if analysis.status not in ("approved",):
        raise ValidationError({"analysis": f"Only approved RCA can be superseded."})
    # superseding RCA must belong to the same Problem
    if analysis.problem_id != extra.get("problem").pk if extra.get("problem") else None:
        raise ValidationError({"analysis": "Superseding RCA must belong to the same Problem."})
    analysis.status = "superseded"
    analysis.save(update_fields=["status"])
    record_history(analysis.problem, "rca_superseded", actor,
        detail=f"RCA '{analysis.pk}' superseded.",
        changed_fields=["status"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_superseded",
        instance=analysis, reason=f"rca={analysis.pk} superseded by replacement")
    return analysis

# ---------------------------------------------------------------------------
# Validation services
# ---------------------------------------------------------------------------

def create_problem_validation(*, actor, problem, title, description="",
                              validation_type="functional", test_plan="",
                              test_results="", **extra):
    _require_staff(actor)

    if not title:
        raise ValidationError({"title": "Title is required."})

    validation = ProblemValidation.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or "").strip(),
        validation_type=validation_type,
        test_plan=(test_plan or "").strip(),
        test_results=(test_results or "").strip(),
        passed=False,
        created_by=actor,
    )

    record_history(
        problem, "validation_created", actor,
        detail=f"Validation '{validation.title}' created.",
        changed_fields=["validation"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_validation_created",
        instance=validation,
        reason=f"validation={validation.pk}, title={title[:200]}",
    )

    return validation


def start_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    validation.save(update_fields=["status"])

    record_history(
        validation.problem, "validation_started", actor,
        detail=f"Validation '{validation.title}' started.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_validation_started",
        instance=validation,
        reason=f"validation={validation.pk} started by {actor.id}",
    )

    return validation


def pass_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    validation.status = "verified"
    validation.passed = True
    validation.validated_by = actor
    validation.validated_at = timezone.now()
    validation.save(update_fields=["status", "passed", "validated_by", "validated_at"])

    record_history(
        validation.problem, "validation_passed", actor,
        detail=f"Validation '{validation.title}' passed.",
        changed_fields=["status", "passed"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_validation_passed",
        instance=validation,
        reason=f"validation={validation.pk} passed by {actor.id}",
    )

    return validation


def fail_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    validation.status = "failed"
    validation.passed = False
    validation.save(update_fields=["status", "passed"])

    record_history(
        validation.problem, "validation_failed", actor,
        detail=f"Validation '{validation.title}' failed.",
        changed_fields=["status", "passed"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_validation_failed",
        instance=validation,
        reason=f"validation={validation.pk} failed by {actor.id}",
    )

    return validation


def mark_problem_validation_inconclusive(*, actor, validation, **extra):
    _require_staff(actor)

    validation.status = "inconclusive"
    validation.save(update_fields=["status"])

    record_history(
        validation.problem, "validation_inconclusive", actor,
        detail=f"Validation '{validation.title}' marked inconclusive.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_validation_inconclusive",
        instance=validation,
        reason=f"validation={validation.pk} marked inconclusive by {actor.id}",
    )

    return validation


def cancel_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    validation.status = "cancelled"
    validation.save(update_fields=["status"])

    record_history(
        validation.problem, "validation_cancelled", actor,
        detail=f"Validation '{validation.title}' cancelled.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_validation_cancelled",
        instance=validation,
        reason=f"validation={validation.pk} cancelled by {actor.id}",
    )

    return validation


# ---------------------------------------------------------------------------
# Exception services
# ---------------------------------------------------------------------------

def create_problem_exception(*, actor, problem, title, description="",
                             exception_type="operational", **extra):
    _require_staff(actor)

    if not title:
        raise ValidationError({"title": "Title is required."})

    exception = ProblemException.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or "").strip(),
        exception_type=exception_type,
        created_by=actor,
    )

    record_history(
        problem, "exception_created", actor,
        detail=f"Exception '{exception.title}' created.",
        changed_fields=["exception"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_exception_created",
        instance=exception,
        reason=f"exception={exception.pk}, title={title[:200]}",
    )

    return exception


def submit_problem_exception(*, actor, exception, **extra):
    _require_staff(actor)

    if exception.status != "draft" if hasattr(exception, "status") else True:
        raise ValidationError({"exception": f"Only draft exceptions can be submitted."})

    exception.status = "active"
    exception.save(update_fields=["status"])

    record_history(
        exception.problem, "exception_submitted", actor,
        detail=f"Exception '{exception.title}' submitted for review.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_exception_submitted",
        instance=exception,
        reason=f"exception={exception.pk} submitted by {actor.id}",
    )

    return exception


def approve_problem_exception(*, actor, exception, **extra):
    _require_governance(actor)

    if exception.status not in ("active",):
        raise ValidationError({"exception": f"Only active exceptions can be approved."})

    if exception.created_by_id == actor.id:
        raise ValidationError({"exception": "Creator cannot self-approve an exception."})

    exception.status = "approved"
    exception.approved_by = actor
    exception.approved_at = timezone.now()
    exception.save(update_fields=["status", "approved_by", "approved_at"])

    record_history(
        exception.problem, "exception_approved", actor,
        detail=f"Exception '{exception.title}' approved.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_exception_approved",
        instance=exception,
        reason=f"exception={exception.pk} approved by {actor.id}",
    )

    return exception


def reject_problem_exception(*, actor, exception, reason="", **extra):
    _require_governance(actor)

    if not reason:
        raise ValidationError({"reason": "A rejection reason is required."})

    exception.status = "rejected"
    exception.save(update_fields=["status"])

    record_history(
        exception.problem, "exception_rejected", actor,
        detail=f"Exception '{exception.title}' rejected: {reason[:200]}.",
        changed_fields=["status", "rejection_reason"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_exception_rejected",
        instance=exception,
        reason=f"exception={exception.pk} rejected by {actor.id}, reason={reason[:200]}",
    )

    return exception


def revoke_problem_exception(*, actor, exception, reason="", **extra):
    _require_staff(actor)

    if not reason:
        raise ValidationError({"reason": "A revocation reason is required."})

    exception.status = "revoked"
    exception.save(update_fields=["status"])

    record_history(
        exception.problem, "exception_revoked", actor,
        detail=f"Exception '{exception.title}' revoked: {reason[:200]}.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_exception_revoked",
        instance=exception,
        reason=f"exception={exception.pk} revoked by {actor.id}, reason={reason[:200]}",
    )

    return exception


def expire_problem_exception(*, actor, exception, **extra):
    _require_staff(actor)

    now = timezone.now()
    if hasattr(exception, "expires_at") and exception.expires_at and exception.expires_at < now:
        raise ValidationError({"exception": "Exception has already expired."})

    exception.status = "expired"
    if hasattr(exception, "expires_at"):
        exception.expires_at = now
    exception.save(update_fields=["status"] if not hasattr(exception, "expires_at") else ["status", "expires_at"])

    record_history(
        exception.problem, "exception_expired", actor,
        detail=f"Exception '{exception.title}' expired.",
        changed_fields=["status"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_exception_expired",
        instance=exception,
        reason=f"exception={exception.pk} expired",
    )

    return exception
