"""Read-only Approval Center API.

Aggregates pending approvals across modules. Write/dispatch (approve/reject)
stays in the original domain ViewSets; this layer only reads existing approval
records and surfaces normalized, safe summaries and links back to the domain
endpoints.

Endpoints:
- GET /api/approvals/           -> paginated, filterable approval list
- GET /api/approvals/summary/   -> role-scoped pending-approval counts
- GET /api/approvals/<type>/<id>/ -> normalized detail for one item
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound

from .services import (
    REGISTRY,
    filter_and_sort,
    get_approval_counts,
    get_pending_approvals,
    _is_due_soon,
    _is_overdue,
)


class ApprovalCenterViewSet(viewsets.ViewSet):
    """
    Read-only API to list, summarize, and detail pending approvals across the
    system. Write/dispatch actions live in their respective modules
    (services, workflow, assets/disposal, procurement) and are surfaced here
    for navigation only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        user = request.user
        if not self._user_may_view(user):
            raise PermissionDenied(
                "Approval Center is restricted to IT staff and admins.")

        items = get_pending_approvals(user)
        page_items, total = filter_and_sort(items, user, request.query_params)

        return Response({
            "total": total,
            "page_size": len(page_items),
            "approvals": page_items,
        })

    @action(detail=False, methods=["get"])
    def counts(self, request):
        """Role-scoped pending-approval counts (summary dashboard)."""
        user = request.user
        if not self._user_may_view(user):
            raise PermissionDenied(
                "Approval Center is restricted to IT staff and admins.")

        items = get_pending_approvals(user)
        counts = get_approval_counts(user)

        urgent_priorities = {"urgent", "high", "critical"}
        overdue = sum(1 for it in items if _is_overdue(it))
        due_soon = sum(1 for it in items if _is_due_soon(it))
        urgent = sum(
            1 for it in items
            if (it.get("priority") or "").lower() in urgent_priorities)

        # Map provider keys to the public summary names.
        by_type = {k: v for k, v in counts.items() if k != "total"}
        procurement = by_type.get("purchase_request", 0) + by_type.get(
            "purchase_order", 0)

        return Response({
            "total_pending": int(counts.get("total", 0)),
            "service_requests": int(by_type.get("service_request", 0)),
            "disposals": int(by_type.get("disposal", 0)),
            "workflow": int(by_type.get("workflow_approval", 0)),
            "knowledge_base": int(by_type.get("knowledge_base", 0)),
            "procurement": int(procurement),
            "overdue": int(overdue),
            "urgent": int(urgent),
            "due_soon": int(due_soon),
            "by_type": {k: int(v) for k, v in by_type.items()},
        })

    def retrieve(self, request, approval_type=None, object_id=None):
        """Normalized detail for one pending approval item."""
        user = request.user
        if not self._user_may_view(user):
            raise PermissionDenied(
                "Approval Center is restricted to IT staff and admins.")

        if not approval_type or not object_id:
            raise NotFound("Invalid approval item reference.")

        provider = self._provider_for(approval_type)
        if provider is None:
            raise NotFound("Unknown approval type: %s" % approval_type)

        try:
            item = provider.get_queryset(user).get(pk=object_id)
        except provider.get_queryset(user).model.DoesNotExist:
            raise NotFound("Approval item not found.")
        except Exception:
            raise NotFound("Approval item not found.")

        if not provider.can_view(user):
            raise PermissionDenied(
                "You do not have permission to view this approval item.")

        return Response(provider.serialize(item, user))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _user_may_view(self, user):
        if user is None or not getattr(user, "pk", None) \
                or not user.is_authenticated:
            return False
        role = getattr(user, "role", "")
        return role in ("system_admin", "it_manager", "it_support") or \
            getattr(user, "is_superuser", False)

    def _provider_for(self, key):
        for provider in REGISTRY:
            if provider.key == key:
                return provider
        return None

