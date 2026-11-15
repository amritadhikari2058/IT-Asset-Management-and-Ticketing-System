"""Privacy-erasure service layer.

Encapsulates the two-person-approval lifecycle, dependency/retention
analysis and the (transactional, idempotent) execution of an approved
erasure request. Intentionally free of Celery so it can be exercised by
tests without a broker; Celery tasks are thin wrappers around these
functions and re-verify authorization before acting.
"""
from django.db import transaction
from django.utils import timezone

from common.models import AuditLog, PrivacyErasureRequest

INVALID_TRANSITION = "Invalid state transition."
NOT_FOUND = "Target not found."

# Records that must never be touched by an automated erasure / retention
# flow, purely because they exist, are preserved for accountability.
PROTECTED_CATEGORIES = ("audit_logs", "security_events")


def _target_user(entity_type, object_id):
    """Fetch the erasure target (accounts.User only, incl. soft-deleted)."""
    if entity_type != "accounts.User":
        return None, [NOT_FOUND]
    from accounts.models import User
    try:
        return User.objects.with_deleted().get(pk=object_id), []
    except (User.DoesNotExist, ValueError):
        return None, [NOT_FOUND]


def analyze_dependencies(entity_type, object_id):
    """Reusable dependency / retention analysis for an erasure target.

    Returns a dict with counts, a per-category assessment and retention
    notes. Never exposes personal data - IDs and counts only.
    """
    notes = [
        "Audit logs and security-event history are retained (never erased).",
        "Ticket/assignment/history rows are preserved and de-identified; "
        "hard deletion is NOT performed.",
    ]

    # Only accounts.User is automated; every other entity type requires
    # manual review. We cannot confirm an arbitrary object_id for a
    # non-user model without querying it, so we report the target as
    # "existing" conceptually: callers distinguish "not found" (404, only
    # possible for accounts.User) from "not supported" (400).
    if entity_type != "accounts.User":
        return {
            "exists": True,
            "is_deleted": False,
            "entity_type": entity_type,
            "object_id": str(object_id),
            "related": {},
            "assessment": [{
                "category": entity_type,
                "action": "manual_review",
                "reason": "Only accounts.User erasure is automated; this "
                          "entity type requires manual review before any "
                          "data is touched.",
            }],
            "can_proceed": False,
            "requires_manual_review": True,
            "retention": notes + [
                f"No automated erasure handler for '{entity_type}'.",
            ],
        }, []

    from accounts.models import User
    try:
        user = User.objects.with_deleted().get(pk=object_id)
    except (User.DoesNotExist, ValueError):
        return {"exists": False, "errors": ["Target not found."]}, [
            "Target not found."]

    related = {}
    assessment = []
    related = {
        "tickets_requested": user.tickets_requested.count(),
        "tickets_assigned": user.tickets_assigned.count(),
        "asset_assignments_received": user.assignments_received.count(),
        "asset_assignments_given": user.assignments_given.count(),
        "ticket_notes_authored": user.ticket_notes.count(),
        "ticket_history_entries": user.ticket_history_entries.count(),
        "asset_history_entries": user.asset_history_entries.count(),
        "kb_articles_authored": user.kb_articles_authored.count(),
        "kb_articles_reviewed": user.kb_articles_reviewed.count(),
        "kb_feedback": user.kb_feedback.count(),
        "notifications": user.notifications.count(),
        "audit_log_entries": user.audit_actions.count(),
    }

    def assess(category, action, reason):
        assessment.append({
            "category": category,
            "action": action,
            "reason": reason,
        })

    if related["tickets_requested"] or related["tickets_assigned"]:
        assess("tickets", "retain",
               "Tickets remain associated with the anonymized account "
               "for accountability; requester/assignee references are "
               "kept (de-identified).")
    if related["asset_assignments_received"] or related["asset_assignments_given"]:
        assess("asset_assignments", "retain",
               "Assignment history remains; assignee reference kept "
               "(de-identified).")
    if related["ticket_notes_authored"]:
        assess("ticket_notes", "anonymize",
               "Note text retained; author reference nulled where the "
               "FK allows.")
    if related["notifications"]:
        assess("notifications", "soft_delete",
               "User notifications may be soft-deleted (no history "
               "impact).")
    if any(related.values()):
        notes.append(
            "Target has linked operational records: they are kept but "
            "de-identified; hard deletion is NOT performed.")

    return {
        "exists": True,
        "is_deleted": getattr(user, "is_deleted", False),
        "entity_type": entity_type,
        "object_id": str(object_id),
        "related": related,
        "assessment": assessment,
        "can_proceed": True,
        "requires_manual_review": False,
        "retention": notes,
    }, []


def _snapshot_assessment(check):
    """PII-free projection of a dependency/retention check.

    Only exists/is_deleted/related/retention are projected; names, emails
    and other personal data are never included.
    """
    if not check:
        return {}
    return {
        "exists": check.get("exists"),
        "is_deleted": check.get("is_deleted"),
        "related": check.get("related", {}),
        "retention": list(check.get("retention", [])),
    }


def _assessment_changed(a, b):
    """True if two PII-free assessment snapshots differ materially."""
    if a == b:
        return False
    for k in ("exists", "is_deleted", "retention"):
        if a.get(k) != b.get(k):
            return True
    if a.get("related") != b.get("related"):
        return True
    return True


def _system_admin(user):
    """True only for an authenticated, active system administrator
    or an active superuser."""
    return bool(
        user and user.is_authenticated and getattr(user, "is_active", False)
        and (getattr(user, "role", "") == "system_admin"
             or getattr(user, "is_superuser", False))
    )


def validate_transition(req, new_status, user):
    """Validate a requested lifecycle transition. Returns (ok, error)."""
    current = req.status
    if new_status == current:
        return False, f"Request is already {current}."
    if req.is_terminal() and new_status not in ("cancelled",):
        return False, f"Cannot transition from terminal state {current}."

    if new_status == "approved":
        if current != "pending_review":
            return False, "Only a pending-review request can be approved."
        if not _system_admin(user):
            return False, "Only an active system administrator may approve."
        if not req.can_be_reviewed_by(user):
            return False, (
                "Independent review required: the requester cannot approve "
                "their own request and the reviewer must be an active "
                "system administrator.")
        return True, ""
    if new_status == "rejected":
        if current != "pending_review":
            return False, "Only a pending-review request can be rejected."
        if not _system_admin(user):
            return False, "Only an active system administrator may reject."
        if not req.can_be_reviewed_by(user):
            return False, (
                "Independent review required: the requester cannot reject "
                "their own request and the reviewer must be an active "
                "system administrator.")
        return True, ""
    if new_status in ("execution_pending", "executing", "completed", "failed"):
        if current != "approved":
            return False, "Execution requires an independently approved request."
        if not _system_admin(user):
            return False, "Only a system administrator may authorize execution."
        return True, ""
    if new_status == "cancelled":
        if current in ("completed", "failed", "rejected"):
            return False, f"Cannot cancel a {current} request."
        if current == "approved":
            if not _system_admin(user):
                return False, "Only a system administrator may cancel an approved request."
        return True, ""
    return False, INVALID_TRANSITION


@transaction.atomic
def approve_erasure(req, reviewer, decision_reason=""):
    """Independently approve a pending-review request."""
    fresh = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)
    ok, error = validate_transition(fresh, "approved", reviewer)
    if not ok:
        req.refresh_from_db()
        return False, error
    fresh.reviewed_by = reviewer
    fresh.reviewed_at = timezone.now()
    fresh.review_decision = "approved"
    fresh.review_reason = decision_reason or ""
    fresh.status = "approved"
    fresh.decided_at = timezone.now()
    fresh.save(update_fields=[
        "reviewed_by", "reviewed_at", "review_decision", "review_reason",
        "status", "decided_at",
    ])
    AuditLog.objects.create(
        actor=reviewer, action="update",
        entity_type="common.PrivacyErasureRequest",
        object_id=str(fresh.pk),
        object_repr=f"erasure approved {fresh.pk}",
        reason="Independent review approved.",
        details={"target": f"{fresh.entity_type}:{fresh.object_id}",
                 "scope": fresh.scope, "reviewer": reviewer.pk})
    req.refresh_from_db()
    return True, ""


@transaction.atomic
def reject_erasure(req, reviewer, reason):
    """Independently reject a pending-review request (reason required)."""
    fresh = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)
    ok, error = validate_transition(fresh, "rejected", reviewer)
    if not ok:
        req.refresh_from_db()
        return False, error
    if not reason or not reason.strip():
        req.refresh_from_db()
        return False, "Rejection requires a reason."
    fresh.reviewed_by = reviewer
    fresh.reviewed_at = timezone.now()
    fresh.review_decision = "rejected"
    fresh.review_reason = reason.strip()
    fresh.status = "rejected"
    fresh.decided_at = timezone.now()
    fresh.save(update_fields=[
        "reviewed_by", "reviewed_at", "review_decision", "review_reason",
        "status", "decided_at",
    ])
    AuditLog.objects.create(
        actor=reviewer, action="update",
        entity_type="common.PrivacyErasureRequest",
        object_id=str(fresh.pk),
        object_repr=f"erasure rejected {fresh.pk}",
        reason="Independent review rejected.",
        details={"target": f"{fresh.entity_type}:{fresh.object_id}",
                 "scope": fresh.scope, "reviewer": reviewer.pk})
    req.refresh_from_db()
    return True, ""


def _anonymize_user(user):
    """Anonymize PII on a user, preserving PK and de-identified history.

    Idempotent at the field level: re-running on an already-anonymized
    account is a no-op for the personal-data fields.
    """
    already = user.email.startswith("erased_") and user.email.endswith("@erased.local")
    if not already:
        user.email = f"erased_{user.pk}@erased.local"
        user.username = f"erased_{user.pk}"
        user.first_name = ""
        user.last_name = ""
        user.phone = ""
        user.job_title = ""
        user.set_unusable_password()
        user.is_active = False
        user.email_verified = False
        user.save()
    if not user.is_deleted:
        user.soft_delete(by_user=None, reason="privacy erasure")
    return already


@transaction.atomic
def execute_erasure(req, executor):
    """Execute an approved erasure request (transactional, idempotent).

    Returns (ok, error, result). Repeated calls on a completed request are
    treated as idempotent successes.
    """
    # Reload fresh state with a row lock so lifecycle decisions are made
    # against the current database row, not a potentially stale caller
    # supplied object.
    fresh = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)

    # Idempotency: an already-completed request is a success, not an error.
    if fresh.status == "completed":
        req.refresh_from_db()
        return True, "", {"already_completed": True, "request_id": fresh.pk}

    # Execution is only valid from the approved state.
    if fresh.status != "approved":
        if fresh.status in ("failed", "rejected", "cancelled"):
            return False, f"Cannot execute a {fresh.status} request.", None
        return False, "Execution requires an independently approved request.", None

    # Authorization: only an active system administrator may execute.
    if not _system_admin(executor):
        return False, "Only an active system administrator may authorize execution.", None

    # Concurrency: an in-flight execution blocks concurrent attempts.
    if fresh.execution_lock:
        return False, "An execution is already in progress.", None

    # Approval revalidation: rerun the dependency analysis and compare the
    # live assessment against the saved PII-free impact-assessment snapshot.
    check, _errors = analyze_dependencies(fresh.entity_type, fresh.object_id)
    live_assessment = _snapshot_assessment(check)
    saved_assessment = fresh.impact_assessment or {}
    if _assessment_changed(saved_assessment, live_assessment):
        # Invalidate the approval and return the request to pending review.
        fresh.status = "pending_review"
        fresh.reviewed_by = None
        fresh.reviewed_at = None
        fresh.review_decision = ""
        fresh.review_reason = ""
        fresh.decided_at = None
        fresh.execution_lock = False
        fresh.execution_started_at = None
        fresh.execution_outcome = ""
        fresh.execution_error = ""
        fresh.impact_assessment = live_assessment
        fresh.impact_assessed_at = timezone.now()
        fresh.save(update_fields=[
            "status", "reviewed_by", "reviewed_at", "review_decision",
            "review_reason", "decided_at", "execution_lock",
            "execution_started_at", "execution_outcome", "execution_error",
            "impact_assessment", "impact_assessed_at",
        ])
        AuditLog.objects.create(
            actor=executor, action="update",
            entity_type="common.PrivacyErasureRequest",
            object_id=str(fresh.pk),
            object_repr=f"erasure approval invalidated {fresh.pk}",
            reason="Impact assessment changed after approval; "
                   "re-review required.",
            details={"target": f"{fresh.entity_type}:{fresh.object_id}"})
        req.refresh_from_db()
        return False, (
            "Impact assessment changed since approval; "
            "re-review required before execution."), None

    # Mark execution in flight.
    fresh.execution_lock = True
    fresh.execution_started_at = timezone.now()
    fresh.status = "executing"
    fresh.execution_outcome = ""
    fresh.execution_error = ""
    fresh.executed_by = executor
    fresh.save(update_fields=[
        "execution_lock", "execution_started_at", "status",
        "execution_outcome", "execution_error", "executed_by",
    ])
    AuditLog.objects.create(
        actor=executor, action="status_change",
        entity_type="common.PrivacyErasureRequest",
        object_id=str(fresh.pk),
        object_repr=f"erasure executing {fresh.pk}",
        reason="Execution started.",
        details={"target": f"{fresh.entity_type}:{fresh.object_id}"})

    try:
        target, errors = _target_user(fresh.entity_type, fresh.object_id)
        if target is None:
            fresh.status = "failed"
            fresh.execution_lock = False
            fresh.execution_outcome = "failed"
            fresh.execution_error = "target_not_found"
            fresh.save(update_fields=[
                "status", "execution_lock", "execution_outcome",
                "execution_error",
            ])
            AuditLog.objects.create(
                actor=executor, action="update",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(fresh.pk),
                object_repr=f"erasure failed {fresh.pk}",
                reason="Execution failed.",
                details={"target": f"{fresh.entity_type}:{fresh.object_id}",
                         "error": "target_not_found"})
            req.refresh_from_db()
            return False, "Target not found.", {"target_not_found": True}

        anonymization_was_noop = _anonymize_user(target)

        fresh.status = "completed"
        fresh.execution_lock = False
        fresh.execution_outcome = "completed"
        fresh.execution_error = ""
        fresh.decided_at = timezone.now()
        fresh.result = {
            "anonymized_fields": ["email", "username", "first_name", "last_name",
                                  "phone", "job_title"],
            "history_preserved": True,
            "anonymization_was_noop": anonymization_was_noop,
            "target": f"{fresh.entity_type}:{fresh.object_id}",
        }
        fresh.save(update_fields=[
            "status", "execution_lock", "execution_outcome",
            "execution_error", "decided_at", "result",
        ])
        AuditLog.objects.create(
            actor=executor, action="hard_delete",
            entity_type="common.PrivacyErasureRequest",
            object_id=str(fresh.pk),
            object_repr=f"erasure executed for {fresh.entity_type}:{fresh.object_id}",
            reason="Erasure executed.",
            details={"target": f"{fresh.entity_type}:{fresh.object_id}",
                     "scope": fresh.scope, "result": fresh.result})
        req.refresh_from_db()
        return True, "", fresh.result
    except Exception:
        # Sanitized failure: never record raw exception messages, which may
        # contain personal information, in audit records.
        fresh.status = "failed"
        fresh.execution_lock = False
        fresh.execution_outcome = "failed"
        fresh.execution_error = "execution_failed"
        fresh.save(update_fields=[
            "status", "execution_lock", "execution_outcome", "execution_error",
        ])
        AuditLog.objects.create(
            actor=executor, action="update",
            entity_type="common.PrivacyErasureRequest",
            object_id=str(fresh.pk),
            object_repr=f"erasure failed {fresh.pk}",
            reason="Execution failed.",
            details={"target": f"{fresh.entity_type}:{fresh.object_id}",
                     "error": "execution_failed"})
        req.refresh_from_db()
        return False, "Execution failed.", {"execution_failed": True}


@transaction.atomic
def cancel_erasure(req, user, reason=""):
    """Cancel a non-terminal request."""
    fresh = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)
    ok, error = validate_transition(fresh, "cancelled", user)
    if not ok:
        req.refresh_from_db()
        return False, error
    fresh.status = "cancelled"
    fresh.decided_at = timezone.now()
    fresh.cancellation_reason = reason or ""
    fresh.save(update_fields=["status", "decided_at", "cancellation_reason"])
    AuditLog.objects.create(
        actor=user, action="update",
        entity_type="common.PrivacyErasureRequest",
        object_id=str(fresh.pk),
        object_repr=f"erasure cancelled {fresh.pk}",
        reason="Request cancelled.",
        details={"target": f"{fresh.entity_type}:{fresh.object_id}",
                 "scope": fresh.scope})
    req.refresh_from_db()
    return True, ""
