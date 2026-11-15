"""Privacy erasure endpoints (System Admin only).

Two-person-approval lifecycle:

  create (pending_review) -> independent review (approved / rejected)
  -> execution (execution_pending / executing -> completed / failed)
  -> optionally cancelled before completion.

Create requires {"entity_type", "object_id", "scope", "reason", "confirm": "<object_id>}. Detail shows the dependency/retention check.
Execute requires independent reviewer approval + explicit confirm and runs
in a transaction; it is idempotent. PII is never logged.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from common.permissions import IsSystemAdmin
from common.privacy_service import (
    approve_erasure, analyze_dependencies, cancel_erasure, execute_erasure,
    reject_erasure, validate_transition)
from common.retention_service import execute_retention, preview_retention
from common.serializers import (AuditLogSerializer,
                                DataRetentionExecutionSerializer,
                                DataRetentionPolicySerializer,
                                PrivacyErasureCreateSerializer,
                                PrivacyErasureExecuteSerializer,
                                PrivacyErasureRequestSerializer,
                                PrivacyErasureReviewSerializer)
from common.models import (AuditLog, DataRetentionExecution,
                           DataRetentionPolicy, PrivacyErasureRequest)


class SmallPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _snapshot_assessment(check):
    """PII-free projection of the dependency/retention check.

    Only exists/is_deleted/related/retention are stored; names, emails and
    other personal data are never persisted in the snapshot.
    """
    if not check:
        return {}
    return {
        "exists": check.get("exists"),
        "is_deleted": check.get("is_deleted"),
        "related": check.get("related", {}),
        "retention": list(check.get("retention", [])),
    }


class PrivacyErasureViewSet(viewsets.ModelViewSet):
    queryset = PrivacyErasureRequest.objects.all()
    serializer_class = PrivacyErasureRequestSerializer
    permission_classes = [IsSystemAdmin]
    pagination_class = SmallPagination
    lookup_field = "pk"

    def get_queryset(self):
        qs = (PrivacyErasureRequest.objects.all()
              .select_related("requested_by", "reviewed_by", "executed_by")
              .order_by("-created_at"))
        p = self.request.query_params
        status_val = p.get("status")
        if status_val:
            qs = qs.filter(status=status_val)
        entity_type = p.get("entity_type")
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        for param, field in (("requested_by", "requested_by_id"),
                             ("reviewed_by", "reviewed_by_id")):
            raw = p.get(param)
            if raw:
                qs = qs.filter(**{field: raw})
        date_from = p.get("date_from")
        date_to = p.get("date_to")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        q = p.get("q")
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(reason__icontains=q) | Q(scope__icontains=q)
                | Q(entity_type__icontains=q) | Q(object_id__icontains=q))
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = PrivacyErasureCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        check, errors = analyze_dependencies(data["entity_type"],
                                             data["object_id"])
        if not check.get("exists"):
            return Response({"detail": "Target not found.", "errors": errors},
                            status=404)
        if not check.get("can_proceed"):
            return Response({"detail": "Entity type not supported for automated erasure.",
                             "dependency_check": check}, status=400)
        snapshot = _snapshot_assessment(check)
        with transaction.atomic():
            req = PrivacyErasureRequest.objects.create(
                entity_type=data["entity_type"], object_id=str(data["object_id"]),
                scope=data["scope"], reason=data["reason"],
                requested_by=request.user,
                impact_assessment=snapshot,
                impact_assessed_at=timezone.now())
            AuditLog.objects.create(
                actor=request.user, action="create",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(req.pk), object_repr=f"erasure request {req.pk}",
                reason="Privacy erasure request created.",
                details={"target": f"{req.entity_type}:{req.object_id}",
                         "scope": req.scope})  # IDs + scope only, no PII
        out = PrivacyErasureRequestSerializer(req, context={"request": request})
        return Response({"id": req.pk, "status": req.status,
                         "dependency_check": check,
                         "impact_assessment": snapshot,
                         "request": out.data},
                        status=201)

    def retrieve(self, request, pk=None):
        req = self.get_object()
        check, errors = analyze_dependencies(req.entity_type, req.object_id)
        audit = (AuditLog.objects.filter(
            entity_type="common.PrivacyErasureRequest",
            object_id=str(req.pk)).order_by("-timestamp")[:50])
        from common.serializers import AuditLogSerializer
        return Response({"id": req.pk, "entity_type": req.entity_type,
                         "object_id": req.object_id, "scope": req.scope,
                         "reason": req.reason, "status": req.status,
                         "requested_by": {"id": req.requested_by_id,
                                          "email": getattr(req.requested_by, "email", None),
                                          "employee_id": getattr(req.requested_by, "employee_id", None)},
                         "reviewer": {"id": req.reviewed_by_id,
                                      "email": getattr(req.reviewed_by, "email", None),
                                      "employee_id": getattr(req.reviewed_by, "employee_id", None)},
                         "reviewed_at": req.reviewed_at,
                         "review_decision": req.review_decision,
                         "review_reason": req.review_reason,
                         "executed_by": {"id": req.executed_by_id,
                                         "email": getattr(req.executed_by, "email", None)},
                         "executed_at": req.executed_at,
                         "cancellation_reason": req.cancellation_reason,
                         "created_at": req.created_at,
                         "decided_at": req.decided_at,
                         "result": req.result,
                         "dependency_check": check,
                         "audit_history": AuditLogSerializer(audit, many=True).data})

    def _partial_update(self, request, pk=None):
        """Scope/reason edits only while pending review.

        Changing scope/reason on an approved request invalidates the
        independent approval (back to pending review, reviewer cleared) so
        the request must be re-approved before execution.
        """
        req = self.get_object()
        scope_fields = ("scope", "reason")
        update_data = {k: v for k, v in request.data.items()
                       if k in scope_fields}
        if not update_data:
            return Response({"detail": "Only scope and reason may be updated here."},
                            status=400)
        with transaction.atomic():
            req = (PrivacyErasureRequest.objects
                   .select_for_update().get(pk=req.pk))
            if req.status in ("executing", "completed", "failed"):
                return Response({"detail": f"Cannot modify a {req.status} request."},
                                status=409)
            if req.status == "approved":
                # Invalidate the independent approval: scope/reason changed.
                req.status = "pending_review"
                req.reviewed_by = None
                req.reviewed_at = None
                req.review_decision = ""
                req.review_reason = ""
                req.decided_at = None
                req.save(update_fields=[
                    "status", "reviewed_by", "reviewed_at", "review_decision",
                    "review_reason", "decided_at",
                ])
                AuditLog.objects.create(
                    actor=request.user, action="update",
                    entity_type="common.PrivacyErasureRequest",
                    object_id=str(req.pk),
                    object_repr=f"erasure approval invalidated {req.pk}",
                    reason="Scope/reason changed after approval; re-review required.",
                    details={"target": f"{req.entity_type}:{req.object_id}"})
            for k, v in update_data.items():
                setattr(req, k, v)
            req.save(update_fields=list(update_data))
            AuditLog.objects.create(
                actor=request.user, action="update",
                entity_type="common.PrivacyErasureRequest",
                object_id=str(req.pk),
                object_repr=f"erasure request updated {req.pk}",
                reason="Scope/reason updated.",
                details={"target": f"{req.entity_type}:{req.object_id}",
                         "changes": list(update_data)})
        return Response({"updated": True, "request_id": req.pk,
                         "status": req.status})

    def update(self, request, pk=None):
        return self._partial_update(request, pk)

    def partial_update(self, request, pk=None):
        return self._partial_update(request, pk)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        req = self.get_object()
        serializer = PrivacyErasureReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("decision") != "approve":
            return Response({"detail": "The approve endpoint requires decision='approve'."},
                            status=400)
        ok, error = approve_erasure(req, request.user,
                                    serializer.validated_data.get("reason", ""))
        if not ok:
            return Response({"detail": error}, status=409)
        return Response({"approved": True, "request_id": req.pk,
                         "status": req.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
        serializer = PrivacyErasureReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("decision") != "reject":
            return Response({"detail": "The reject endpoint requires decision='reject'."},
                            status=400)
        ok, error = reject_erasure(req, request.user,
                                   serializer.validated_data.get("reason", ""))
        if not ok:
            return Response({"detail": error}, status=409)
        return Response({"rejected": True, "request_id": req.pk,
                         "status": req.status})

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        req = self.get_object()
        serializer = PrivacyErasureExecuteSerializer(
            data=request.data, context={"view": self, "object_id": req.object_id})
        serializer.is_valid(raise_exception=True)
        ok, error, result = execute_erasure(req, request.user)
        if not ok:
            return Response({"detail": error}, status=409)
        return Response({"executed": True, "request_id": req.pk,
                         "status": req.status, "result": result})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        reason = request.data.get("reason", "")
        ok, error = cancel_erasure(req, request.user, reason)
        if not ok:
            return Response({"detail": error}, status=409)
        return Response({"cancelled": True, "request_id": req.pk,
                         "status": req.status})

    @action(detail=True, methods=["get"])
    def dependency_preview(self, request, pk=None):
        req = self.get_object()
        check, errors = analyze_dependencies(req.entity_type, req.object_id)
        return Response({"request_id": req.pk, "status": req.status,
                         "dependency_check": check})

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        self.get_object()  # enforce existence / object permissions
        qs = (AuditLog.objects
              .filter(entity_type="common.PrivacyErasureRequest",
                      object_id=str(pk))
              .order_by("-timestamp"))
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = AuditLogSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = AuditLogSerializer(qs, many=True)
        return Response(ser.data)


class DataRetentionPolicyViewSet(viewsets.ModelViewSet):
    queryset = DataRetentionPolicy.objects.all().order_by("-created_at")
    serializer_class = DataRetentionPolicySerializer
    permission_classes = [IsSystemAdmin]

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        policy = self.get_object()
        return Response(preview_retention(policy))

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        policy = self.get_object()
        ok, error, summary = execute_retention(policy, request.user)
        if not ok:
            return Response({"detail": error, **summary}, status=409)
        return Response({"executed": True, **summary})


class DataRetentionExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (DataRetentionExecution.objects.all()
                .select_related("policy")
                .order_by("-started_at"))
    serializer_class = DataRetentionExecutionSerializer
    permission_classes = [IsSystemAdmin]