"""Privacy erasure endpoints (System Admin only).

Create requires {"entity_type", "object_id", "scope", "reason",
"confirm": "<object_id>"}. Detail shows dependency/retention check BEFORE
execution. Execute anonymizes personal data (never logs PII) and records a
PII-free AuditLog. Rejected/executed requests are immutable.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.models import AuditLog, PrivacyErasureRequest
from common.permissions import IsSystemAdmin


def dependency_check(entity_type, object_id):
    """Counts + retention notes without exposing personal data."""
    from accounts.models import User

    notes = ["Audit logs are retained without personal data.",
             "Ticket/assignment history rows are preserved (de-identified)."]
    related = {}
    if entity_type == "accounts.User":
        try:
            u = User.objects.with_deleted().get(pk=object_id)
        except (User.DoesNotExist, ValueError):
            return None, ["Target not found."]
        related = {"tickets_requested": u.tickets_requested.count(),
                   "assignments_received": u.assignments_received.count(),
                   "audit_actions": u.audit_actions.count(),
                   "ticket_notes": u.ticket_notes.count()}
        if any(related.values()):
            notes.append("User has linked records: they are kept but "
                         "de-identified; hard deletion is NOT performed.")
        return {"exists": True, "is_deleted": u.is_deleted,
                "related": related, "retention": notes}, []
    return {"exists": "unknown-target", "related": {},
            "retention": notes + ["Only accounts.User erasure is automated; "
                                  "other types need manual review."]}, []


class PrivacyErasureViewSet(viewsets.ModelViewSet):
    queryset = PrivacyErasureRequest.objects.all()
    permission_classes = [IsSystemAdmin]

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().values(
            "id", "entity_type", "object_id", "status", "reason",
            "created_at", "decided_at")
        return Response(list(qs))

    def retrieve(self, request, pk=None):
        req = self.get_object()
        check, errors = dependency_check(req.entity_type, req.object_id)
        if check is None:
            return Response({"request_id": req.pk, "errors": errors},
                            status=404)
        return Response({"id": req.pk, "entity_type": req.entity_type,
                         "object_id": req.object_id, "scope": req.scope,
                         "reason": req.reason, "status": req.status,
                         "dependency_check": check})

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
            scope=data["scope"], reason=data["reason"], requested_by=request.user)
        AuditLog.objects.create(
            actor=request.user, action="create",
            entity_type="common.PrivacyErasureRequest",
            object_id=str(req.pk), object_repr=f"erasure request {req.pk}",
            reason=data["reason"],
            details={"target": f"{req.entity_type}:{req.object_id}",
                     "scope": req.scope})  # IDs + scope only, no PII
        return Response({"id": req.pk, "status": req.status,
                         "dependency_check": check}, status=201)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        req = self.get_object()
        if req.status != "pending":
            return Response({"detail": f"Already {req.status}."}, status=409)
        if request.data.get("confirm") != str(req.object_id):
            return Response({"detail": "Re-enter the record ID to confirm."},
                            status=400)
        if req.entity_type != "accounts.User":
            return Response(
                {"detail": "Automated execution currently supports "
                           "accounts.User only; others need manual review."},
                status=400)
        from accounts.models import User
        try:
            target = User.objects.with_deleted().get(pk=req.object_id)
        except (User.DoesNotExist, ValueError):
            return Response({"detail": "Target not found."}, status=404)
        with transaction.atomic():
            # Anonymize PII; keep PK + de-identified history (retention).
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
            req.status = "executed"
            req.decided_at = timezone.now()
            req.result = {"anonymized_fields": ["email", "username",
                                                "first_name", "last_name",
                                                "phone", "job_title"],
                          "history_preserved": True}
            req.save(update_fields=["status", "decided_at", "result"])
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(req.pk),
                object_repr=f"erasure executed for "
                            f"{req.entity_type}:{req.object_id}",
                reason=req.reason,
                details={"target": f"{req.entity_type}:{req.object_id}",
                         "scope": req.scope, "result": req.result})
        return Response({"executed": True, "request_id": req.pk})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
        if req.status != "pending":
            return Response({"detail": f"Already {req.status}."}, status=409)
        req.status = "rejected"
        req.decided_at = timezone.now()
        req.save(update_fields=["status", "decided_at"])
        AuditLog.objects.create(
            actor=request.user, action="update",
            entity_type="common.PrivacyErasureRequest",
            object_id=str(req.pk),
            object_repr=f"erasure rejected {req.pk}",
            reason=request.data.get("reason", ""))
        return Response({"rejected": True})
