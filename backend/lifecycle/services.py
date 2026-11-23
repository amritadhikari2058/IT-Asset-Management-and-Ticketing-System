"""Employee Lifecycle business logic.

Integrates with existing modules WITHOUT modifying them:
- accounts.User / Department
- assets.Asset / Assignment / AssetHistory
- tickets.Ticket / services.ServiceRequest
- common.{Notification, AuditLog, BackgroundTaskRun, SoftDeleteModel}

All mutations go through transaction.atomic() + select_for_update() where
concurrency matters. History rows are append-only. Automation is an
explicit allowlisted dictionary dispatch (never eval/import from user text).
"""
import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.models import User
from assets.models import Asset, Assignment, AssetHistory
from common.audit import log_action
from common.models import BackgroundTaskRun
from common.notifications import notify_user
from lifecycle import models as lm

logger = logging.getLogger(__name__)

CASE_TYPE_PREFIX = {
    "onboarding": "ONB",
    "offboarding": "OFF",
    "transfer": "TRF",
}

# ---------------------------------------------------------------------------
# Case number generation (server-side, unique, concurrency-safe, bounded retry)
# ---------------------------------------------------------------------------

def generate_case_number(case_type):
    """Propose a unique case number like ONB-2026-00001.

    The number is computed from the current maximum sequence for the
    prefix/year. Uniqueness under concurrency is guaranteed by the
    database unique constraint plus the bounded retry in
    :func:`create_case_from_template` (the case row is what actually
    reserves the number).
    """
    if case_type not in CASE_TYPE_PREFIX:
        raise ValidationError(f"Unknown case type: {case_type}")
    prefix = CASE_TYPE_PREFIX[case_type]
    year = timezone.now().year
    pattern = f"{prefix}-{year}-"
    max_seq = (
        lm.LifecycleCase.objects.filter(
            case_number__startswith=pattern)
        .aggregate(m=Max("case_number"))["m"]
    )
    next_seq = 1
    if max_seq:
        tail = str(max_seq)[len(pattern):]
        if tail.isdigit():
            next_seq = int(tail) + 1
    return f"{pattern}{next_seq:05d}"


# ---------------------------------------------------------------------------
# History / notification helpers
# ---------------------------------------------------------------------------

def _history(case, task, actor, event_type, previous_status="",
             new_status="", detail=""):
    return lm.LifecycleHistory.objects.create(
        case=case, task=task, actor=actor,
        event_type=event_type, previous_status=previous_status or "",
        new_status=new_status or "", detail=detail or "")


def _notify(recipient, actor, title, body, case=None, task=None):
    """In-app notification; never the actor, never inactive/deleted users."""
    if recipient is None or getattr(recipient, "pk", None) is None:
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    target = case if case is not None else task
    notify_user(
        recipient, "lifecycle_event", title, body or "",
        entity_type="lifecycle.LifecycleCase", object_id=str(target.pk),
        actor=actor, post_commit=False,
    )


# ---------------------------------------------------------------------------
# Progress calculation (central service, client cannot write these fields)
# ---------------------------------------------------------------------------

def recalc_progress(case):
    """Recompute totals / progress / overdue and persist."""
    tasks = case.tasks.filter(is_deleted=False)
    total = tasks.count()
    completed_eq = tasks.filter(
        Q(status="completed") | Q(status="skipped")).count()
    overdue = tasks.filter(
        due_date__lt=timezone.now(),
        status__in=("pending", "in_progress", "blocked")).count()
    progress = int(round((completed_eq / total) * 100)) if total else 0
    lm.LifecycleCase.objects.filter(pk=case.pk).update(
        total_tasks=total, completed_tasks=completed_eq,
        overdue_tasks=overdue, checklist_progress=progress,
        updated_at=timezone.now())


# ---------------------------------------------------------------------------
# Template → case task copying
# ---------------------------------------------------------------------------

def _resolve_assignee(template_item, case):
    """Resolve default assignee per spec policy. Never inactive users."""
    role = template_item.default_assignee_role
    coordinator = case.assigned_coordinator
    employee = case.employee

    def _active(user):
        return user is not None and getattr(user, "is_active", True) \
            and not getattr(user, "is_deleted", False)

    if role == "employee":
        return employee if _active(employee) else None
    if role == "unassigned":
        return None
    if role in ("system_admin", "it_manager", "it_support"):
        if coordinator is not None and _active(coordinator):
            coordinator_role = getattr(coordinator, "role", "")
            if role == "system_admin" and coordinator_role == "system_admin":
                return coordinator
            if role == "it_manager" and coordinator_role in (
                    "it_manager", "system_admin"):
                return coordinator
            if role == "it_support" and coordinator_role in (
                    "it_support", "it_manager", "system_admin"):
                return coordinator
        return None
    return None


def copy_template_tasks(case, template):
    """Copy active template items into LifecycleTask rows (atomic)."""
    items = (template.items.filter(is_deleted=False)
             .order_by("sequence", "id"))
    base_date = case.effective_date or case.planned_date or timezone.now()
    tasks = []
    for item in items:
        due_date = None
        if base_date:
            due_date = base_date + timedelta(days=item.due_offset_days)
        assigned_to = _resolve_assignee(item, case)
        tasks.append(lm.LifecycleTask(
            case=case, source_template_item=item,
            sequence=item.sequence, title=item.title,
            description=item.description, category=item.category,
            responsibility=item.responsibility,
            assigned_to=assigned_to, status="pending",
            required=item.required,
            blocks_completion=item.blocks_completion,
            requires_evidence=item.requires_evidence,
            due_date=due_date, automation_type=item.automation_type,
            automation_config=dict(item.automation_config or {}),
            version=1))
    lm.LifecycleTask.objects.bulk_create(tasks)
    for t in tasks:
        _history(case, t, None, "task_created",
                 detail=f"Copied from template {template.code}")
    recalc_progress(case)
    return tasks


# ---------------------------------------------------------------------------
# Case creation from template
# ---------------------------------------------------------------------------

def _conflicting_active_cases(employee, case_type):
    qs = lm.LifecycleCase.objects.filter(
        employee=employee, is_deleted=False).exclude(
        status__in=lm.TERMINAL_STATUSES)
    if case_type == "onboarding":
        return qs.filter(case_type="onboarding")
    if case_type == "offboarding":
        return qs.filter(case_type="offboarding")
    return qs.none()


def _conflicting_opposite_case(employee, case_type):
    if case_type not in ("onboarding", "offboarding"):
        return lm.LifecycleCase.objects.none()
    other = "offboarding" if case_type == "onboarding" else "onboarding"
    return lm.LifecycleCase.objects.filter(
        employee=employee, is_deleted=False, case_type=other).exclude(
        status__in=lm.TERMINAL_STATUSES)


def create_case_from_template(*, template, employee, actor, department=None,
                              priority="medium", planned_date=None,
                              effective_date=None, completion_target=None,
                              source="manual", source_reference="",
                              notes="", assigned_coordinator=None):
    """Create a case + copied tasks + history atomically."""
    if template.is_deleted or not template.is_active:
        raise ValidationError("Template is not active.")
    if getattr(employee, "is_deleted", False):
        raise ValidationError("Cannot create a case for a deleted employee.")
    if _conflicting_active_cases(employee, template.case_type).exists():
        raise ValidationError(
            f"Employee already has an active {template.case_type} case.")
    if _conflicting_opposite_case(employee, template.case_type).exists():
        other = ("offboarding" if template.case_type == "onboarding"
                 else "onboarding")
        raise ValidationError(f"Employee already has an active {other} case.")

    case_number = generate_case_number(template.case_type)
    case = lm.LifecycleCase(
        case_number=case_number, case_type=template.case_type,
        employee=employee,
        department=department or employee.home_department,
        initiated_by=actor, assigned_coordinator=assigned_coordinator,
        status="draft", priority=priority,
        planned_date=planned_date, effective_date=effective_date,
        completion_target=completion_target, source=source,
        source_reference=source_reference, notes=notes, version=1)
    case.full_clean()
    saved = False
    last_error = None
    for _attempt in range(6):
        try:
            with transaction.atomic():
                case.save()
                copy_template_tasks(case, template)
                _history(case, None, actor, "case_created",
                         new_status="draft",
                         detail=f"Case created from template {template.code}")
                recalc_progress(case)
                saved = True
                break
        except IntegrityError as exc:
            last_error = exc
            case.case_number = generate_case_number(template.case_type)
            continue
    if not saved:
        if last_error:
            raise last_error
        raise ValidationError("Unable to create case; retry.")
    transaction.on_commit(lambda: _notify_case_assigned(case, actor))
    return case


def _notify_case_assigned(case, actor):
    if case.assigned_coordinator:
        _notify(case.assigned_coordinator, actor,
                f"Lifecycle case assigned: {case.case_number}",
                f"You are the coordinator for {case.case_type} "
                f"case {case.case_number}.", case=case)
    if getattr(case.employee, "email", None):
        _notify(case.employee, actor,
                f"Lifecycle case created: {case.case_number}",
                f"A {case.case_type} case has been created for you.",
                case=case)


# ---------------------------------------------------------------------------
# Case transitions (protected actions)
# ---------------------------------------------------------------------------

def _role_of(user):
    return getattr(user, "role", "")


def _is_admin(user):
    return bool(user and user.is_authenticated and (
        _role_of(user) == "system_admin" or getattr(user, "is_superuser", False)))


def _is_manager(user):
    return _is_admin(user) or _role_of(user) == "it_manager"


def _is_staff(user):
    return _is_manager(user) or _role_of(user) == "it_support"


_ALLOWED_TRANSITIONS = {
    "onboarding": [
        ("draft", "planned"), ("draft", "in_progress"), ("draft", "blocked"),
        ("draft", "cancelled"),
        ("planned", "in_progress"), ("planned", "blocked"), ("planned", "cancelled"),
        ("in_progress", "ready_for_employee"), ("in_progress", "employee_started"),
        ("in_progress", "awaiting_asset_return"), ("in_progress", "awaiting_access_revocation"),
        ("in_progress", "ready_for_closure"), ("in_progress", "access_updated"),
        ("in_progress", "asset_changes_completed"), ("in_progress", "blocked"),
        ("in_progress", "cancelled"), ("in_progress", "completed"),
        ("ready_for_employee", "employee_started"), ("ready_for_employee", "in_progress"),
        ("ready_for_employee", "blocked"), ("ready_for_employee", "cancelled"),
        ("employee_started", "in_progress"), ("employee_started", "awaiting_asset_return"),
        ("employee_started", "awaiting_access_revocation"), ("employee_started", "ready_for_closure"),
        ("employee_started", "blocked"), ("employee_started", "cancelled"),
        ("awaiting_asset_return", "awaiting_access_revocation"),
        ("awaiting_asset_return", "ready_for_closure"), ("awaiting_asset_return", "asset_changes_completed"),
        ("awaiting_asset_return", "blocked"), ("awaiting_asset_return", "cancelled"),
        ("awaiting_access_revocation", "ready_for_closure"), ("awaiting_access_revocation", "asset_changes_completed"),
        ("awaiting_access_revocation", "blocked"), ("awaiting_access_revocation", "cancelled"),
        ("ready_for_closure", "completed"), ("ready_for_closure", "blocked"), ("ready_for_closure", "cancelled"),
        ("access_updated", "asset_changes_completed"), ("access_updated", "ready_for_closure"),
        ("access_updated", "completed"), ("access_updated", "blocked"), ("access_updated", "cancelled"),
        ("asset_changes_completed", "ready_for_closure"), ("asset_changes_completed", "completed"),
        ("asset_changes_completed", "blocked"), ("asset_changes_completed", "cancelled"),
        ("blocked", "in_progress"), ("blocked", "cancelled"),
    ],
    "offboarding": [
        ("draft", "planned"), ("draft", "in_progress"), ("draft", "blocked"), ("draft", "cancelled"),
        ("planned", "in_progress"), ("planned", "blocked"), ("planned", "cancelled"),
        ("in_progress", "awaiting_asset_return"), ("in_progress", "awaiting_access_revocation"),
        ("in_progress", "ready_for_closure"), ("in_progress", "access_updated"),
        ("in_progress", "asset_changes_completed"), ("in_progress", "blocked"),
        ("in_progress", "cancelled"), ("in_progress", "completed"),
        ("awaiting_asset_return", "awaiting_access_revocation"), ("awaiting_asset_return", "ready_for_closure"),
        ("awaiting_asset_return", "asset_changes_completed"), ("awaiting_asset_return", "blocked"),
        ("awaiting_asset_return", "cancelled"),
        ("awaiting_access_revocation", "ready_for_closure"), ("awaiting_access_revocation", "asset_changes_completed"),
        ("awaiting_access_revocation", "blocked"), ("awaiting_access_revocation", "cancelled"),
        ("ready_for_closure", "completed"), ("ready_for_closure", "blocked"), ("ready_for_closure", "cancelled"),
        ("access_updated", "asset_changes_completed"), ("access_updated", "ready_for_closure"),
        ("access_updated", "completed"), ("access_updated", "blocked"), ("access_updated", "cancelled"),
        ("asset_changes_completed", "ready_for_closure"), ("asset_changes_completed", "completed"),
        ("asset_changes_completed", "blocked"), ("asset_changes_completed", "cancelled"),
        ("blocked", "in_progress"), ("blocked", "cancelled"),
    ],
    "transfer": [
        ("draft", "planned"), ("draft", "in_progress"), ("draft", "blocked"), ("draft", "cancelled"),
        ("planned", "in_progress"), ("planned", "blocked"), ("planned", "cancelled"),
        ("in_progress", "access_updated"), ("in_progress", "asset_changes_completed"),
        ("in_progress", "ready_for_closure"), ("in_progress", "blocked"),
        ("in_progress", "cancelled"), ("in_progress", "completed"),
        ("access_updated", "asset_changes_completed"), ("access_updated", "ready_for_closure"),
        ("access_updated", "completed"), ("access_updated", "blocked"), ("access_updated", "cancelled"),
        ("asset_changes_completed", "ready_for_closure"), ("asset_changes_completed", "completed"),
        ("asset_changes_completed", "blocked"), ("asset_changes_completed", "cancelled"),
        ("ready_for_closure", "completed"), ("ready_for_closure", "blocked"), ("ready_for_closure", "cancelled"),
        ("blocked", "in_progress"), ("blocked", "cancelled"),
    ],
}

def _require_transition(case, next_status):
    allowed = [t[1] for t in _ALLOWED_TRANSITIONS.get(case.case_type, [])
               if t[0] == case.status]
    if next_status not in allowed and next_status not in ("blocked", "cancelled"):
        raise ValidationError(
            f"Cannot transition {case.status} → {next_status} for "
            f"{case.case_type}.")


def _can_complete(case):
    tasks = case.tasks.filter(is_deleted=False)
    if tasks.filter(status="blocked").exists():
        return False, "A task is blocked; unblock it before completing."
    if tasks.filter(automation_status="failed").exclude(
            automation_status__in=("succeeded", "manual_review")).exists():
        return False, "An automation requires manual review."
    incomplete = tasks.filter(
        required=True, blocks_completion=True).exclude(
        status__in=("completed", "skipped"))
    if incomplete.exists():
        return False, "Required blocking tasks remain incomplete."
    return True, ""


def transition_case(case, next_status, actor, reason="", version=None):
    """Protected case status transition. Optimistic concurrency via version."""
    if version is not None and case.version != version:
        raise ValidationError(
            {"version": "Stale version; the case was modified concurrently."},
            code=409)
    if case.is_deleted:
        raise ValidationError("Case is deleted.")
    _require_transition(case, next_status)
    if case.is_terminal and next_status != "cancelled":
        raise ValidationError("Case is already terminal.")

    if next_status == "cancelled" and not reason.strip():
        raise ValidationError(
            {"reason": "A cancellation reason is required."})
    if next_status == "blocked" and not reason.strip():
        raise ValidationError(
            {"reason": "A block reason is required."})

    is_admin = _is_admin(actor)
    is_manager = _is_manager(actor)
    is_staff = _is_staff(actor)

    if next_status == "planned" and not is_manager:
        raise ValidationError(
            "Only IT Manager or System Admin may plan a case.")
    if next_status == "cancelled" and not is_staff:
        raise ValidationError("Only IT staff may cancel a case.")
    if next_status == "completed" and not is_manager:
        raise ValidationError(
            "Only IT Manager or System Admin may complete a case.")

    if next_status == "completed":
        ok, msg = _can_complete(case)
        if not ok:
            raise ValidationError({"detail": msg})

    if next_status == "employee_started":
        if actor != case.employee and not is_staff:
            raise ValidationError(
                "Only the employee or IT staff may confirm start.")

    if next_status == "completed" and case.case_type == "transfer":
        if not case.tasks.filter(
                status__in=("completed", "skipped")).exists():
            raise ValidationError("Transfer tasks must be resolved first.")

    with transaction.atomic():
        case = lm.LifecycleCase.objects.select_for_update().get(pk=case.pk)
        if version is not None and case.version != version:
            raise ValidationError(
                {"version": "Stale version; the case was modified concurrently."},
                code=409)
        previous = case.status
        case.status = next_status
        if next_status in ("in_progress", "employee_started") and not case.started_at:
            case.started_at = timezone.now()
        if next_status == "completed":
            case.completed_at = timezone.now()
        if next_status == "cancelled":
            case.cancelled_at = timezone.now()
            case.cancellation_reason = reason or ""
        if next_status == "blocked":
            case.blocked_reason = reason or ""
        case.version = case.version + 1
        case.save(update_fields=[
            "status", "started_at", "completed_at", "cancelled_at",
            "cancellation_reason", "blocked_reason", "version", "updated_at"])
        _history(case, None, actor, f"case_{next_status}",
                 previous_status=previous, new_status=next_status,
                 detail=reason or "")
        recalc_progress(case)
    transaction.on_commit(lambda: _notify_transition(case, next_status, actor))
    return case


def _notify_transition(case, next_status, actor):
    title_map = {
        "planned": f"Case planned: {case.case_number}",
        "started": f"Case started: {case.case_number}",
        "completed": f"Case completed: {case.case_number}",
        "cancelled": f"Case cancelled: {case.case_number}",
        "blocked": f"Case blocked: {case.case_number}",
    }
    if case.assigned_coordinator:
        _notify(case.assigned_coordinator, actor,
                title_map.get(next_status, f"Case updated: {case.case_number}"),
                f"Case {case.case_number} moved to {next_status}.", case=case)


def block_case(case, actor, reason, version=None):
    if case.is_terminal or case.status == "blocked":
        raise ValidationError("Case cannot be blocked.")
    return transition_case(case, "blocked", actor, reason=reason, version=version)


def unblock_case(case, actor, version=None):
    if case.status != "blocked":
        raise ValidationError("Case is not blocked.")
    return transition_case(case, "in_progress", actor, reason="",
                           version=version)


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------

def _task_actor_may_manage(actor, task):
    if _is_admin(actor) or _is_manager(actor):
        return True
    if _is_staff(actor) and task.responsibility == "it":
        return True
    if task.responsibility == "employee" and task.assigned_to_id == actor.pk:
        return True
    return False


def _get_task(task, version=None):
    if version is not None and task.version != version:
        raise ValidationError({"version": "Stale version."}, code=409)
    if task.is_deleted:
        raise ValidationError("Task is deleted.")
    return task


def task_start(task, actor, version=None):
    task = _get_task(task, version)
    if task.status != "pending":
        raise ValidationError("Only a pending task can be started.")
    if not _task_actor_may_manage(actor, task):
        raise ValidationError("Not authorized to start this task.")
    with transaction.atomic():
        task = lm.LifecycleTask.objects.select_for_update().get(pk=task.pk)
        task = _get_task(task, version)
        previous = task.status
        if task.status != "pending":
            raise ValidationError("Only a pending task can be started.")
        task.status = "in_progress"
        task.started_at = timezone.now()
        task.version = task.version + 1
        task.save(update_fields=["status", "started_at", "version", "updated_at"])
        _history(task.case, task, actor, "task_started",
                 previous_status=previous, new_status="in_progress")
        recalc_progress(task.case)
    return task


def task_complete(task, actor, completion_note="", version=None):
    task = _get_task(task, version)
    if task.status == "completed":
        raise ValidationError("Task is already completed.", code=409)
    if task.status == "blocked":
        raise ValidationError("Task is blocked; unblock it first.")
    if task.status in ("skipped", "cancelled"):
        raise ValidationError("Task cannot be completed after being skipped/cancelled.")
    if not _task_actor_may_manage(actor, task):
        raise ValidationError("Not authorized to complete this task.")
    if task.requires_evidence:
        has_evidence = task.evidence.filter(is_deleted=False).exists()
        if not has_evidence:
            raise ValidationError(
                {"detail": "Evidence is required before completing this task."})
    with transaction.atomic():
        task = lm.LifecycleTask.objects.select_for_update().get(pk=task.pk)
        task = _get_task(task, version)
        previous = task.status
        if task.status in ("completed", "skipped", "cancelled", "blocked"):
            raise ValidationError("Task cannot be completed in its current state.")
        task.status = "completed"
        task.completed_at = timezone.now()
        task.completed_by = actor
        task.version = task.version + 1
        task.save(update_fields=["status", "completed_at", "completed_by",
                                 "version", "updated_at"])
        _history(task.case, task, actor, "task_completed",
                 previous_status=previous, new_status="completed",
                 detail=completion_note or "")
        recalc_progress(task.case)
        _run_task_automation(task, actor)
    return task


def task_skip(task, actor, reason, version=None):
    task = _get_task(task, version)
    if not reason.strip():
        raise ValidationError({"skip_reason": "A skip reason is required."})
    if task.status == "skipped":
        raise ValidationError("Task is already skipped.", code=409)
    if task.status in ("completed", "cancelled"):
        raise ValidationError("Task cannot be skipped.")
    is_admin = _is_admin(actor)
    is_manager = _is_manager(actor)
    if task.required and task.blocks_completion and not is_manager:
        raise ValidationError(
            "Required blocking tasks may only be skipped by IT Manager "
            "or System Admin.")
    with transaction.atomic():
        task = lm.LifecycleTask.objects.select_for_update().get(pk=task.pk)
        task = _get_task(task, version)
        previous = task.status
        task.status = "skipped"
        task.skipped_at = timezone.now()
        task.skipped_by = actor
        task.skip_reason = reason
        task.version = task.version + 1
        task.save(update_fields=["status", "skipped_at", "skipped_by",
                                 "skip_reason", "version", "updated_at"])
        _history(task.case, task, actor, "task_skipped",
                 previous_status=previous, new_status="skipped", detail=reason)
        recalc_progress(task.case)
    return task


def task_block(task, actor, reason, version=None):
    task = _get_task(task, version)
    if not reason.strip():
        raise ValidationError({"blocked_reason": "A block reason is required."})
    if task.status == "blocked":
        raise ValidationError("Task is already blocked.", code=409)
    if task.status in ("completed", "skipped", "cancelled"):
        raise ValidationError("Task cannot be blocked.")
    if not _task_actor_may_manage(actor, task):
        raise ValidationError("Not authorized to block this task.")
    with transaction.atomic():
        task = lm.LifecycleTask.objects.select_for_update().get(pk=task.pk)
        task = _get_task(task, version)
        previous = task.status
        task.status = "blocked"
        task.blocked_reason = reason
        task.version = task.version + 1
        task.save(update_fields=["status", "blocked_reason", "version", "updated_at"])
        _history(task.case, task, actor, "task_blocked",
                 previous_status=previous, new_status="blocked", detail=reason)
        recalc_progress(task.case)
    return task


def task_unblock(task, actor, version=None):
    task = _get_task(task, version)
    if task.status != "blocked":
        raise ValidationError("Task is not blocked.")
    if not _task_actor_may_manage(actor, task):
        raise ValidationError("Not authorized to unblock this task.")
    with transaction.atomic():
        task = lm.LifecycleTask.objects.select_for_update().get(pk=task.pk)
        task = _get_task(task, version)
        previous = task.status
        task.status = "pending"
        task.blocked_reason = ""
        task.version = task.version + 1
        task.save(update_fields=["status", "blocked_reason", "version", "updated_at"])
        _history(task.case, task, actor, "task_unblocked",
                 previous_status=previous, new_status="pending")
        recalc_progress(task.case)
    return task


def task_assign(task, actor, assigned_to, version=None):
    task = _get_task(task, version)
    if task.is_deleted:
        raise ValidationError("Task is deleted.")
    if not (_is_admin(actor) or _is_manager(actor)):
        raise ValidationError("Only IT Manager or System Admin may assign tasks.")
    if assigned_to is not None:
        if getattr(assigned_to, "is_deleted", False) \
                or not getattr(assigned_to, "is_active", True):
            raise ValidationError("Cannot assign to an inactive/deleted user.")
    with transaction.atomic():
        task = lm.LifecycleTask.objects.select_for_update().get(pk=task.pk)
        task = _get_task(task, version)
        task.assigned_to = assigned_to
        task.version = task.version + 1
        task.save(update_fields=["assigned_to", "version", "updated_at"])
        _history(task.case, task, actor, "task_assigned",
                 detail=f"Assigned to {getattr(assigned_to, 'employee_id', assigned_to)}")
    return task


# ---------------------------------------------------------------------------
# Automation dispatcher (allowlisted)
# ---------------------------------------------------------------------------

ALLOWED_AUTOMATION_TYPES = {
    "none", "create_service_request", "create_ticket", "assign_asset",
    "return_assets", "deactivate_account", "revoke_tokens", "notification",
}


def _run_task_automation(task, actor):
    if task.automation_type not in ALLOWED_AUTOMATION_TYPES:
        lm.LifecycleTask.objects.filter(pk=task.pk).update(
            automation_status="not_applicable",
            automation_error_summary="",
            updated_at=timezone.now())
        return
    task.automation_status = "running"
    task.automation_error_summary = ""
    task.save(update_fields=["automation_status", "automation_error_summary", "updated_at"])
    _history(task.case, task, actor, "automation_started",
             new_status="running", detail=f"Automation: {task.automation_type}")
    try:
        handler = _automation_handler(task.automation_type)
        handler(task, actor)
        if task.automation_status not in ("failed", "manual_review"):
            task.automation_status = "succeeded"
            _history(task.case, task, actor, "automation_succeeded",
                     new_status="succeeded")
    except Exception as exc:  # noqa: BLE001
        task.automation_status = "failed"
        task.automation_error_summary = f"{type(exc).__name__}: {exc}"
        _history(task.case, task, actor, "automation_failed",
                 new_status="failed",
                 detail=task.automation_error_summary)
        logger.warning("Lifecycle automation failed: %s", type(exc).__name__)
    task.save(update_fields=["automation_status", "automation_error_summary", "updated_at"])


def _automation_handler(automation_type):
    return {
        "create_service_request": _automation_create_service_request,
        "create_ticket": _automation_create_ticket,
        "assign_asset": _automation_assign_asset,
        "return_assets": _automation_return_assets,
        "deactivate_account": _automation_deactivate_account,
        "revoke_tokens": _automation_revoke_tokens,
        "notification": _automation_notification,
    }[automation_type]


def _automation_create_service_request(task, actor):
    """Auto-create a ServiceRequest from the task's automation configuration.

    The task's ``automation_config`` supplies the catalogue item
    (``catalogue_item_id``) and optional request attributes (``employee_id``,
    ``answers``, ``description``, ``priority``). The employee defaults to the
    lifecycle case's employee. When the catalogue item is missing or the
    referenced employee/catalogue item is not usable, the task stays in
    ``manual_review`` for human handling.
    """
    config = task.automation_config or {}
    catalogue_item_id = config.get("catalogue_item_id")
    employee_id = config.get("employee_id") or task.case.employee_id
    if not catalogue_item_id:
        task.automation_status = "manual_review"
        task.automation_error_summary = (
            "Service Request automation requires catalogue_item_id in "
            "automation_config; manual review required.")
        task.save(update_fields=["automation_status", "automation_error_summary",
                                 "updated_at"])
        _history(task.case, task, actor, "automation_failed",
                 new_status="manual_review",
                 detail="Service Request automation pending catalogue item.")
        return

    from services.models import ServiceCatalogueItem, ServiceRequest

    catalogue_item = (ServiceCatalogueItem.objects
                      .filter(pk=catalogue_item_id, is_deleted=False)
                      .first())
    employee = (User.objects.filter(pk=employee_id, is_deleted=False,
                                    is_active=True).first())
    if not catalogue_item or not employee:
        task.automation_status = "manual_review"
        task.automation_error_summary = (
            "Service Request automation references unknown catalogue item "
            "or employee; manual review required.")
        task.save(update_fields=["automation_status", "automation_error_summary",
                                 "updated_at"])
        _history(task.case, task, actor, "automation_failed",
                 new_status="manual_review",
                 detail="Service Request automation pending valid references.")
        return

    today = timezone.now().strftime("%Y%m%d")
    seq = ServiceRequest.objects.filter(
        request_number__startswith=f"SR-{today}-").count() + 1

    service_request = ServiceRequest.objects.create(
        request_number=f"SR-{today}-{seq:04d}",
        requester=employee,
        department=employee.home_department,
        catalogue_item=catalogue_item,
        answers=config.get("answers") or {},
        description=(config.get("description") or "").strip(),
        priority=config.get("priority") or "medium",
        status="submitted",
    )
    task.related_service_request = service_request
    task.save(update_fields=[
        "related_service_request", "automation_status",
        "automation_error_summary", "updated_at"])


def _automation_create_ticket(task, actor):
    """Auto-create a Ticket from a Service Request via the task link.

    The task may reference the Service Request it should fulfil either through
    the task's own ``related_service_request`` FK or through
    ``automation_config["service_request_id"]``. When a live, non-deleted
    request is resolved, the ticket is created through the existing transactional
    service (``services.service_ticketing.ensure_ticket_for_service_request``)
    and linked back via ``task.related_ticket``. The dispatcher marks the task
    ``succeeded`` on a clean return; unresolvable configurations stay in
    ``manual_review`` for human handling.
    """
    from services.service_ticketing import ensure_ticket_for_service_request

    from services.models import ServiceRequest as _ServiceRequest
    sr = task.related_service_request
    if sr is None:
        sr_id = (task.automation_config or {}).get("service_request_id")
        sr = _ServiceRequest.objects.filter(pk=sr_id).first() if sr_id else None
    if sr is None or sr.is_deleted:
        task.automation_status = "manual_review"
        task.automation_error_summary = (
            "Ticket automation is not implemented; manual review required.")
        task.save(update_fields=["automation_status", "automation_error_summary",
                                 "updated_at"])
        _history(task.case, task, actor, "automation_failed",
                 new_status="manual_review",
                 detail="Ticket automation is not implemented.")
        return

    ticket, created = ensure_ticket_for_service_request(sr, actor)
    task.related_ticket = ticket
    task.save(update_fields=[
        "related_ticket", "automation_status", "automation_error_summary",
        "updated_at"])


def _automation_assign_asset(task, actor):
    asset_id = (task.automation_config or {}).get("asset_id")
    if not asset_id:
        raise ValidationError("assign_asset requires asset_id in automation_config")
    assign_asset_to_case_employee(task.case, int(asset_id), actor,
                                  note="Automated assignment")


def _automation_return_assets(task, actor):
    case = task.case
    resolutions = case.asset_resolutions.filter(
        is_deleted=False, resolution="pending")
    for res in resolutions:
        _resolve_asset(case, res.asset, "returned", actor, res,
                       note="Automated return")


def _automation_deactivate_account(task, actor):
    deactivate_account(task.case.employee, actor)


def _automation_revoke_tokens(task, actor):
    revoke_user_tokens(task.case.employee, actor)


def _automation_notification(task, actor):
    message = ""
    if isinstance(task.automation_config, dict):
        message = task.automation_config.get("message", "")
    _notify(task.case.employee, actor,
            f"Lifecycle notification: {task.case.case_number}",
            message, case=task.case)


# ---------------------------------------------------------------------------
# Asset assignment & recovery (reuse existing workflow rules)
# ---------------------------------------------------------------------------

def assign_asset_to_case_employee(case, asset_id, actor, note="",
                                  assign_to=None):
    """Assign an Asset using existing asset rules.

    ``assign_to`` defaults to the case employee; used by transfer resolution
    to re-asset to a different employee.
    """
    if assign_to is None:
        assign_to = case.employee
    try:
        asset = Asset.objects.select_related("assigned_to").get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError({"detail": "Asset not found."})
    employee = assign_to
    old = {"assigned_to": asset.assigned_to_id, "status": asset.status}
    if asset.assigned_to_id is not None:
        raise ValidationError(
            {"detail": "Asset is already assigned; return it first."})
    if asset.status != "available":
        raise ValidationError(
            {"detail": f"Asset status is '{asset.status}'; only 'available' "
                       "assets can be assigned."})
    if getattr(asset, "has_open_maintenance", False):
        m = asset.upcoming_maintenance
        raise ValidationError(
            {"detail": f"Asset is undergoing maintenance ({m.title}).",
             "maintenance_id": m.pk})
    with transaction.atomic():
        asset = Asset.objects.select_for_update().get(pk=asset_id)
        if asset.assigned_to_id is not None or asset.status != "available":
            raise ValidationError(
                {"detail": "Asset was assigned concurrently."})
        assignment = Assignment.objects.create(
            asset=asset, assigned_to=employee, assigned_by=actor,
            note=note)
        asset.assigned_to = employee
        asset.status = "assigned"
        asset.save(update_fields=["assigned_to", "status"])
        AssetHistory.objects.create(
            asset=asset, actor=actor, action="assigned",
            old_values=old,
            new_values={"assigned_to": employee.pk, "status": "assigned",
                        "assignment_id": assignment.pk},
            note=note)
        log_action(actor=actor, action="assignment", instance=asset,
                   details={"assigned_to": employee.pk})
        transaction.on_commit(lambda: _notify(employee, actor,
            f"Asset {asset.asset_tag} assigned", f"{asset.name}", case=case))
    return asset


def _resolve_asset(case, asset, resolution, actor, related_task=None, note=""):
    try:
        with transaction.atomic():
            res, created = lm.LifecycleAssetResolution.objects.get_or_create(
                case=case, asset=asset,
                defaults={"status": "pending", "resolution": resolution,
                          "notes": note, "resolved_by": actor,
                          "resolved_at": timezone.now() if resolution != "pending" else None,
                          "related_task": related_task})
            if not created:
                if res.resolution != "pending":
                    raise ValidationError(
                        {"detail": f"Asset {asset.asset_tag} already resolved as "
                                   f"{res.resolution}."})
                res.resolution = resolution
                res.notes = note
                res.resolved_by = actor
                res.resolved_at = timezone.now() if resolution != "pending" else None
                res.related_task = related_task
                res.save(update_fields=["resolution", "notes", "resolved_by",
                                        "resolved_at", "related_task", "updated_at"])
            _history(case, related_task, actor, "asset_returned",
                     new_status=resolution, detail=note or resolution)
            if resolution in ("returned", "transferred"):
                _return_asset_via_workflow(asset, actor)
            recalc_progress(case)
    except IntegrityError:
        res = lm.LifecycleAssetResolution.objects.get(case=case, asset=asset)
        if res.resolution != "pending":
            raise ValidationError(
                {"detail": f"Asset {asset.asset_tag} already resolved as "
                           f"{res.resolution}."})
        with transaction.atomic():
            res.resolution = resolution
            res.notes = note
            res.resolved_by = actor
            res.resolved_at = timezone.now() if resolution != "pending" else None
            res.related_task = related_task
            res.save(update_fields=["resolution", "notes", "resolved_by",
                                    "resolved_at", "related_task", "updated_at"])
            _history(case, related_task, actor, "asset_returned",
                     new_status=resolution, detail=note or resolution)
            if resolution in ("returned", "transferred"):
                _return_asset_via_workflow(asset, actor)
            recalc_progress(case)
    return res


def _return_asset_via_workflow(asset, actor):
    from django.utils import timezone as _tz
    with transaction.atomic():
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        last = asset.assignments.filter(returned_at__isnull=True).last()
        if last:
            last.returned_at = _tz.now()
            last.save(update_fields=["returned_at"])
        asset.assigned_to = None
        asset.status = "available"
        asset.save(update_fields=["assigned_to", "status"])
        AssetHistory.objects.create(
            asset=asset, actor=actor, action="returned",
            old_values={"assigned_to": asset.assigned_to_id},
            new_values={"assigned_to": None})
        log_action(actor=actor, action="assignment", instance=asset,
                   details={"returned": True})


def resolve_asset_return(case, asset_id, actor, related_task=None, note=""):
    try:
        asset = Asset.objects.get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError({"detail": "Asset not found."})
    return _resolve_asset(case, asset, "returned", actor, related_task, note)


def resolve_asset_lost(case, asset_id, actor, related_task=None, note=""):
    try:
        asset = Asset.objects.get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError({"detail": "Asset not found."})
    if not note.strip():
        raise ValidationError({"detail": "A reason is required to mark an asset lost."})
    return _resolve_asset(case, asset, "lost", actor, related_task, note)


def resolve_asset_damaged(case, asset_id, actor, related_task=None, note=""):
    try:
        asset = Asset.objects.get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError({"detail": "Asset not found."})
    return _resolve_asset(case, asset, "damaged", actor, related_task, note)


def resolve_asset_transfer(case, asset_id, actor, new_assignee, related_task=None, note=""):
    try:
        asset = Asset.objects.get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError({"detail": "Asset not found."})
    if new_assignee is None or getattr(new_assignee, "is_deleted", False) \
            or not getattr(new_assignee, "is_active", True):
        raise ValidationError({"detail": "A valid active assignee is required."})
    res = _resolve_asset(case, asset, "transferred", actor, related_task,
                         note=f"Transferred to {new_assignee.employee_id}. {note}")
    assign_asset_to_case_employee(case, asset.id, actor, note=note,
                                  assign_to=new_assignee)
    return res


def resolve_asset_exception(case, asset_id, actor, reason, related_task=None):
    is_admin = _is_admin(actor)
    is_manager = _is_manager(actor)
    if not is_manager:
        raise ValidationError(
            "Only IT Manager or System Admin may approve an asset exception.")
    if not reason.strip():
        raise ValidationError({"detail": "A reason is required for an exception."})
    try:
        asset = Asset.objects.get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError({"detail": "Asset not found."})
    return _resolve_asset(case, asset, "approved_exception", actor, related_task,
                          note=reason)


def list_assigned_assets(case):
    employee = case.employee
    assets = Asset.objects.filter(assigned_to=employee, is_deleted=False)
    resolutions = {
        r.asset_id: r for r in case.asset_resolutions.filter(is_deleted=False)
    }
    out = []
    for a in assets:
        r = resolutions.get(a.pk)
        out.append({
            "id": a.pk, "asset_tag": a.asset_tag, "name": a.name,
            "category": getattr(a.category, "name", None) if a.category else None,
            "status": a.status, "location": a.location,
            "resolution": r.resolution if r else "pending",
            "resolved_at": r.resolved_at if r else None,
        })
    return out


# ---------------------------------------------------------------------------
# Account deactivation & token revocation
# ---------------------------------------------------------------------------

def revoke_user_tokens(user, actor):
    """Blacklist all refresh tokens for a user (existing simplejwt mechanism)."""
    try:
        from token_blacklist.models import OutstandingToken, BlacklistedToken
    except Exception:
        logger.warning("token_blacklist app not available")
        return 0
    count = 0
    for ot in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=ot)
        if created:
            count += 1
    return count


def deactivate_account(user, actor):
    """Deactivate an account with safeguards.

    - System Admin or authorized lifecycle service only (caller enforces).
    - Last active System Admin cannot be deactivated.
    - Self-lockout protection.
    - Tokens revoked via existing mechanism.
    - Idempotent.
    """
    if not _is_admin(actor):
        raise ValidationError("Only System Admin may deactivate accounts.")
    if user.pk == actor.pk:
        raise ValidationError("Self-lockout is not permitted.")
    if (getattr(user, "role", "") == "system_admin"
            or getattr(user, "is_superuser", False)):
        active_admins = User.objects.filter(
            is_active=True, is_deleted=False).filter(
            Q(role="system_admin") | Q(is_superuser=True))
        if active_admins.count() <= 1:
            raise ValidationError(
                "Cannot deactivate the last active System Admin.")
    if not user.is_active:
        return user  # idempotent
    with transaction.atomic():
        user.is_active = False
        user.save(update_fields=["is_active"])
        revoke_user_tokens(user, actor)
        # Reclaim the offboarding employee's active software license
        # allocations so a deactivated employee does not keep seats assigned.
        # `revoke_allocations_for_offboarding` is defensive per-allocation and
        # never raises for a single bad allocation, so a licensing hiccup
        # cannot block account deactivation. The result is captured and surfaced
        # in logs + audit so failed reclamation is observable and recoverable.
        reclamation = {
            "revoked_count": 0,
            "total_active": 0,
            "results": [],
        }
        try:
            from licensing.services import (
                revoke_allocations_for_offboarding as _revoke_for_offboarding)
            reclamation = _revoke_for_offboarding(
                user=user, actor=actor,
                reason="Account deactivated during offboarding")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "License reclamation raised while deactivating user %s (%s): %s",
                user.pk, getattr(user, "employee_id", ""), exc,
                exc_info=True)
        if reclamation.get("total_active"):
            logger.info(
                "License reclamation for deactivated user %s (%s): %s of %s "
                "allocation(s) revoked.",
                user.pk, getattr(user, "employee_id", ""),
                reclamation.get("revoked_count"),
                reclamation.get("total_active"),
            )
        log_action(actor=actor, action="deactivate", instance=user,
                   reason="Lifecycle offboarding",
                   details={"license_reclamation": reclamation})
    return user


# ---------------------------------------------------------------------------
# Transfer department change
# ---------------------------------------------------------------------------

def apply_department_change(case, actor, new_department, version=None):
    if version is not None and case.version != version:
        raise ValidationError({"version": "Stale version."}, code=409)
    if case.case_type != "transfer":
        raise ValidationError("Only transfer cases may apply a department change.")
    if not _is_manager(actor):
        raise ValidationError("Only IT Manager or System Admin may apply a department change.")
    if new_department is None or getattr(new_department, "is_deleted", False):
        raise ValidationError({"detail": "A valid department is required."})
    employee = case.employee
    if employee.home_department_id == new_department.pk:
        raise ValidationError({"detail": "Target department equals current department."})
    previous_department = employee.home_department
    with transaction.atomic():
        case = lm.LifecycleCase.objects.select_for_update().get(pk=case.pk)
        if version is not None and case.version != version:
            raise ValidationError({"version": "Stale version."}, code=409)
        employee.home_department = new_department
        employee.save(update_fields=["home_department"])
        case.previous_department = previous_department
        case.new_department = new_department
        case.status = "access_updated"
        case.version = case.version + 1
        case.save(update_fields=["status", "previous_department", "new_department",
                                 "version", "updated_at"])
        _history(case, None, actor, "case_updated",
                 previous_status="in_progress", new_status="access_updated",
                 detail=f"Department changed {previous_department} → {new_department}")
        recalc_progress(case)
    return case
