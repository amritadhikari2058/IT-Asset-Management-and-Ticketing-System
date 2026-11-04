"""Privacy erasure endpoints (System Admin only).

Dual-approval workflow (additive to the original):

    create  -> pending_review
    approve (reviewer != requester) -> approved
    reject  (reviewer != requester) -> rejected
    execute (approved + confirmation) -> executing -> completed / failed
    cancel  -> cancelled

The requester can never approve/reject their own request. Execution requires
an *approved* decision and is protected by a database row lock against
concurrent execution. The impact assessment is recalculated immediately
before execution; a material change after approval invalidates the approval.

AuditLog rows record IDs + scope only, never the erased personal data.
"""
import logging
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from common.audit import log_action
from common.models import AuditLog, PrivacyErasureRequest
from common.permissions import IsSystemAdmin
from common.serializers import AuditLogSerializer

logger = logging.getLogger("privacy.erasure")

# Fields that, if they change materially between approval and execution,
# invalidate the approval and require a new review. The impact assessment
# snapshot captures related counts and retention notes; a change in the
# target's identity or scope is captured by re-running dependency_check.


def _snapshot_assessment(check):
    """Return a PII-free snapshot of the dependency/retention check."""
    if not check:
        return {}
    return {
        "exists": check.get("exists"),
        "is_deleted": check.get("is_deleted"),
        "related": check.get("related", {}),
        "retention": list(check.get("retention", [])),
    }


def _assessment_changed(a, b):
    """True if two assessment snapshots differ materially."""
    if a == b:
        return False
    for k in ("exists", "is_deleted", "retention"):
        if a.get(k) != b.get(k):
            return True
    if a.get("related") != b.get("related"):
        return True
    return True


def dependency_check(entity_type, object_id):
    """Counts + retention notes without exposing personal data."""
    notes = ["Audit logs are retained without personal data.",
             "Ticket/assignment history rows are preserved (de-identified)."]
    related = {}
    try:
        u = User.objects.with_deleted().get(pk=object_id)
    except (User.DoesNotExist, ValueError):
        return None, ["Target not found."]
    related = {"tickets_requested": u.tickets_requested.count(),
               "tickets_assigned": u.tickets_assigned.count(),
               "assignments_received": u.assignments_received.count(),
               "audit_actions": u.audit_actions.count(),
               "ticket_notes": u.ticket_notes.count()}
    if any(related.values()):
        notes.append("User has linked records: they are kept but "
                     "de-identified; hard deletion is NOT performed.")
    return {"exists": True, "is_deleted": u.is_deleted,
            "related": related, "retention": notes}, []


class PrivacyErasureViewSet(viewsets.ModelViewSet):
    queryset = PrivacyErasureRequest.objects.all()
    permission_classes = [IsSystemAdmin]
    serializer_class = None  # custom responses below

    # ---------------- list ----------------
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        rows = qs.values(
            "id", "entity_type", "object_id", "status", "reason", "scope",
            "created_at", "decided_at", "reviewed_by", "reviewed_at",
            "execution_outcome", "requested_by")
        return Response(list(rows))

    # ---------------- create ----------------
    def create(self, request, *args, **kwargs):
        data = request.data
        if data.get("confirm") != str(data.get("object_id")):
            return Response(
                {"detail": "Confirmation required: re-enter the record ID.",
                 "hint": '{"confirm": "<object_id>"}'}, status=400)
        if not data.get("reason") or not data.get("scope"):
            return Response(
                {"detail": "Both 'reason' and 'scope' are required."},
                status=400)
        check, errors = dependency_check(data.get("entity_type", ""),
                                         data.get("object_id", ""))
        if check is None:
            return Response({"detail": "Target not found.",
                             "errors": errors}, status=404)
        req = PrivacyErasureRequest.objects.create(
            entity_type=data["entity_type"], object_id=str(data["object_id"]),
            scope=data["scope"], reason=data["reason"],
            requested_by=request.user, status="pending_review")
        assessment = _snapshot_assessment(check)
        req.impact_assessment = assessment
        req.impact_assessed_at = timezone.now()
        req.save(update_fields=["impact_assessment", "impact_assessed_at"])
        AuditLog.objects.create(
            actor=request.user, action="create",
            entity_type="common.PrivacyErasureRequest",
            object_id=str(req.pk), object_repr=f"erasure request {req.pk}",
            reason=data["reason"],
            details={"target": f"{req.entity_type}:{req.object_id}",
                     "scope": req.scope,
                     "impact_assessment": assessment})  # IDs/counts only
        return Response({"id": req.pk, "status": req.status,
                         "dependency_check": check,
                         "impact_assessment": assessment}, status=201)

    # ---------------- retrieve ----------------
    def retrieve(self, request, pk=None):
        req = self.get_object()
        check, errors = dependency_check(req.entity_type, req.object_id)
        data = {"id": req.pk, "entity_type": req.entity_type,
                "object_id": req.object_id, "scope": req.scope,
                "reason": req.reason, "status": req.status,
                "requested_by": req.requested_by_id,
                "reviewed_by": req.reviewed_by_id,
                "review_decision": req.review_decision,
                "reviewed_at": req.reviewed_at,
                "review_reason": req.review_reason,
                "impact_assessment": req.impact_assessment,
                "impact_assessed_at": req.impact_assessed_at,
                "execution_started_at": req.execution_started_at,
                "executed_at": req.executed_at,
                "execution_outcome": req.execution_outcome,
                "execution_error": req.execution_error,
                "created_at": req.created_at, "decided_at": req.decided_at,
                "result": req.result}
        if check is None:
            data["errors"] = ["Target not found."]
        else:
            data["dependency_check"] = check
            data["impact_assessment"] = _snapshot_assessment(check)
        return Response(data)

    # ---------------- approve ----------------
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        req = self.get_object()
        if req.status not in ("pending_review",):
            return Response(
                {"detail": f"Cannot approve a {req.status} request."},
                status=409)
        if request.user.pk == req.requested_by_id:
            return Response(
                {"detail": "The requester cannot approve their own request."},
                status=403)
        decision = request.data.get("decision")
        if decision != "approved":
            return Response(
                {"detail": "Decision must be 'approved'."}, status=400)
        review_reason = request.data.get("reason", "").strip()
        if not review_reason:
            return Response(
                {"detail": "A review reason is required."}, status=400)
        check, _ = dependency_check(req.entity_type, req.object_id)
        assessment = _snapshot_assessment(check)
        with transaction.atomic():
            req = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)
            if req.status != "pending_review":
                return Response(
                    {"detail": f"Request is now {req.status}."}, status=409)
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.review_decision = "approved"
            req.review_reason = review_reason
            req.decided_at = timezone.now()
            req.status = "approved"
            req.impact_assessment = assessment
            req.impact_assessed_at = timezone.now()
            req.save(update_fields=[
                "reviewed_by", "reviewed_at", "review_decision", "review_reason",
                "decided_at", "status", "impact_assessment",
                "impact_assessed_at"])
            AuditLog.objects.create(
                actor=request.user, action="update",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(req.pk),
                object_repr=f"erasure approved {req.pk}",
                reason=review_reason,
                details={"target": f"{req.entity_type}:{req.object_id}",
                         "scope": req.scope,
                         "impact_assessment": assessment,
                         "review_decision": "approved"})
        return Response({"approved": True, "request_id": req.pk,
                         "status": req.status,
                         "impact_assessment": assessment})

    # ---------------- reject ----------------
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
        if req.status not in ("pending_review",):
            return Response(
                {"detail": f"Cannot reject a {req.status} request."},
                status=409)
        if request.user.pk == req.requested_by_id:
            return Response(
                {"detail": "The requester cannot reject their own request."},
                status=403)
        decision = request.data.get("decision")
        if decision != "rejected":
            return Response(
                {"detail": "Decision must be 'rejected'."}, status=400)
        review_reason = request.data.get("reason", "").strip()
        if not review_reason:
            return Response(
                {"detail": "A review reason is required."}, status=400)
        with transaction.atomic():
            req = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)
            if req.status != "pending_review":
                return Response(
                    {"detail": f"Request is now {req.status}."}, status=409)
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.review_decision = "rejected"
            req.review_reason = review_reason
            req.decided_at = timezone.now()
            req.status = "rejected"
            req.save(update_fields=[
                "reviewed_by", "reviewed_at", "review_decision", "review_reason",
                "decided_at", "status"])
            AuditLog.objects.create(
                actor=request.user, action="update",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(req.pk),
                object_repr=f"erasure rejected {req.pk}",
                reason=review_reason,
                details={"target": f"{req.entity_type}:{req.object_id}",
                         "scope": req.scope,
                         "review_decision": "rejected"})
        return Response({"rejected": True, "request_id": req.pk,
                         "status": req.status})

    # ---------------- cancel ----------------
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        if req.status in ("completed", "failed", "cancelled", "rejected"):
            return Response(
                {"detail": f"Cannot cancel a {req.status} request."}, status=409)
        review_reason = request.data.get("reason", "").strip()
        with transaction.atomic():
            req = PrivacyErasureRequest.objects.select_for_update().get(pk=req.pk)
            if req.status in ("completed", "failed", "cancelled", "rejected"):
                return Response(
                    {"detail": f"Cannot cancel a {req.status} request."},
                    status=409)
            req.status = "cancelled"
            req.review_decision = "cancelled"
            req.review_reason = review_reason or "Cancelled."
            req.decided_at = timezone.now()
            req.save(update_fields=["status", "review_decision",
                                    "review_reason", "decided_at"])
            AuditLog.objects.create(
                actor=request.user, action="update",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(req.pk),
                object_repr=f"erasure cancelled {req.pk}",
                reason=review_reason or "",
                details={"target": f"{req.entity_type}:{req.object_id}",
                         "scope": req.scope,
                         "review_decision": "cancelled"})
        return Response({"cancelled": True, "request_id": req.pk,
                         "status": req.status})

    # ---------------- execute ----------------
    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        req = self.get_object()
        if request.data.get("confirm") != str(req.object_id):
            return Response({"detail": "Re-enter the record ID to confirm."},
                            status=400)
        if req.status != "approved":
            return Response(
                {"detail": f"Execution requires an approved request "
                           f"(current: {req.status})."}, status=409)
        if req.entity_type != "accounts.User":
            return Response(
                {"detail": "Automated execution currently supports "
                           "accounts.User only; others need manual review."},
                status=400)
        # Prevent concurrent execution via row lock + execution_lock flag.
        try:
            with transaction.atomic():
                req = (PrivacyErasureRequest.objects
                       .select_for_update().get(pk=req.pk))
                if req.status != "approved":
                    return Response(
                        {"detail": f"Request is now {req.status}."}, status=409)
                if req.execution_lock:
                    return Response(
                        {"detail": "An execution is already in progress."},
                        status=409)
                # Recalculate impact assessment immediately before execution.
                check, _ = dependency_check(req.entity_type, req.object_id)
                live_assessment = _snapshot_assessment(check)
                # Invalidate approval if material fields changed since approval.
                # Compare the stored impact-assessment snapshot against the
                # live recalculation.
                if _assessment_changed(req.impact_assessment or {},
                                       live_assessment):
                    req.status = "pending_review"
                    req.review_decision = ""
                    req.reviewed_by = None
                    req.reviewed_at = None
                    req.decided_at = None
                    req.impact_assessment = live_assessment
                    req.impact_assessed_at = timezone.now()
                    req.save(update_fields=[
                        "status", "review_decision", "reviewed_by",
                        "reviewed_at", "decided_at", "impact_assessment",
                        "impact_assessed_at"])
                    AuditLog.objects.create(
                        actor=request.user, action="update",
                        entity_type="common.PrivacyErasureRequest",
                        object_id=str(req.pk),
                        object_repr=f"approval invalidated {req.pk}",
                        reason="Impact assessment changed after approval",
                        details={"target": f"{req.entity_type}:{req.object_id}",
                                 "scope": req.scope,
                                 "impact_assessment": live_assessment})
                    return Response(
                        {"detail": "Impact assessment changed since approval. "
                                   "Request returned to pending_review for "
                                   "re-review before execution.",
                         "status": "pending_review"}, status=409)
                # Mark execution in flight.
                req.execution_lock = True
                req.execution_started_at = timezone.now()
                req.status = "executing"
                req.execution_outcome = ""
                req.execution_error = ""
                req.save(update_fields=[
                    "execution_lock", "execution_started_at", "status",
                    "execution_outcome", "execution_error"])
                AuditLog.objects.create(
                    actor=request.user, action="status_change",
                    entity_type="common.PrivacyErasureRequest",
                    object_id=str(req.pk),
                    object_repr=f"erasure executing {req.pk}",
                    reason="Execution started",
                    details={"target": f"{req.entity_type}:{req.object_id}",
                             "scope": req.scope})
        except PrivacyErasureRequest.DoesNotExist:
            return Response({"detail": "Request not found."}, status=404)

        # Perform the anonymization outside the lock-holding transaction but
        # inside its own transaction so partial failure is retry-safe.
        try:
            target = User.objects.with_deleted().get(pk=req.object_id)
        except (User.DoesNotExist, ValueError):
            self._mark_failed(req.pk, "Target not found.", request.user)
            return Response({"detail": "Target not found."}, status=404)

        try:
            with transaction.atomic():
                target.email = f"erased_{target.pk}@erased.local"
                target.username = f"erased_{target.pk}"
                target.first_name = ""
                target.last_name = ""
                target.phone = ""
                target.job_title = ""
                target.set_unusable_password()
                target.is_active = False
                target.email_verified = False
                target.save()
                if not target.is_deleted:
                    target.soft_delete(by_user=request.user,
                                       reason=f"privacy erasure #{req.pk}")
                req = PrivacyErasureRequest.objects.get(pk=req.pk)
                req.execution_lock = False
                req.status = "completed"
                req.execution_outcome = "completed"
                req.executed_at = timezone.now()
                req.result = {"anonymized_fields": [
                    "email", "username", "first_name", "last_name",
                    "phone", "job_title"], "history_preserved": True}
                req.save(update_fields=[
                    "execution_lock", "status", "execution_outcome",
                    "executed_at", "result"])
                AuditLog.objects.create(
                    actor=request.user, action="hard_delete",
                    entity_type="common.PrivacyErasureRequest",
                    object_id=str(req.pk),
                    object_repr=f"erasure executed for "
                                f"{req.entity_type}:{req.object_id}",
                    reason=req.reason,
                    details={"target": f"{req.entity_type}:{req.object_id}",
                             "scope": req.scope,
                             "result": req.result})
        except Exception as exc:  # noqa: BLE001 - sanitize and record failure
            sanitized = str(exc)[:200]
            self._mark_failed(req.pk, sanitized, request.user)
            logger.exception("Privacy erasure execution failed for request %s",
                             req.pk)
            return Response(
                {"detail": "Execution failed. See execution_error.",
                 "request_id": req.pk}, status=500)

        return Response({"executed": True, "request_id": req.pk,
                         "status": "completed"})

    def _mark_failed(self, pk, error_text, actor):
        try:
            req = PrivacyErasureRequest.objects.get(pk=pk)
            req.execution_lock = False
            req.status = "failed"
            req.execution_outcome = "failed"
            req.execution_error = error_text
            req.save(update_fields=[
                "execution_lock", "status", "execution_outcome",
                "execution_error"])
            AuditLog.objects.create(
                actor=actor, action="status_change",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(pk),
                object_repr=f"erasure failed {pk}",
                reason="Execution failed",
                details={"error": error_text})
        except PrivacyErasureRequest.DoesNotExist:
            pass

    # ---------------- history ----------------
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        self.get_object()  # enforce existence/permission
        qs = (AuditLog.objects
              .filter(entity_type="common.PrivacyErasureRequest",
                      object_id=str(pk))
              .order_by("timestamp"))
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = AuditLogSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = AuditLogSerializer(qs, many=True)
        return Response(ser.data)
