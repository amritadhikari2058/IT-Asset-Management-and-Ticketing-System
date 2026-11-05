"""
Centralized Approval Center service layer.

Provider-registry architecture that aggregates pending approvals across
modules without duplicating approval business logic. This layer is read-only
aggregation: approval decisions remain in the original domain ViewSets, and
this module only reads existing approval records and surfaces normalized,
safe summaries.

Design rules (see task workstream K2):
- No GenericForeignKey; each provider queries its own model directly.
- Optional apps (e.g. procurement) are imported lazily inside the provider
  so a missing or misconfigured app never causes a startup failure.
- Role-aware and object-scope-aware: can_approve/can_reject respect
  separation of duties (a requester can never approve their own item).
- Bounded querysets; no unbounded historical rows; no N+1 requester lookups.
"""

from django.utils import timezone

from services.models import ServiceRequest
from assets.models import Disposal
from workflow.models import ApprovalRequest
from assets.models import KnowledgeBaseArticle

# Optional procurement app: imported lazily inside its provider so that a
# missing/misconfigured procurement app never breaks startup of this module.
try:  # pragma: no cover - exercised only when procurement app is installed
    from procurement.models import PurchaseRequest, PurchaseOrder  # noqa: F401
    HAS_PROCUREMENT = True
except Exception:  # pragma: no cover - procurement unavailable
    HAS_PROCUREMENT = False


def _iso(dt):
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _safe_email(user):
    if user is None or not getattr(user, "pk", None):
        return None
    return getattr(user, "email", None) or None


def _safe_name(user):
    if user is None or not getattr(user, "pk", None):
        return None
    return getattr(user, "employee_id", None) or getattr(user, "email", None) or str(user.pk)


def _home_department(user):
    dept = getattr(user, "home_department", None)
    if dept is None:
        return None
    return getattr(dept, "name", None) or getattr(dept, "pk", None)


class ApprovalProvider:
    """Base class for an approval source provider."""

    key = "approval"
    label = "Approval"
    base_path = ""

    # Subclasses override.
    def get_queryset(self, user):
        raise NotImplementedError

    def can_view(self, user):
        """Whether this provider's queue is visible to the user at all."""
        return True

    def can_approve(self, user, item):
        return False

    def can_reject(self, user, item):
        return False

    def serialize(self, item, user):
        raise NotImplementedError

    def get_summary(self, user):
        return {"count": self.get_queryset(user).count()}

    # ---- action paths (read-only descriptors; decisions stay in domain) ----

    def _detail_path(self, item):
        if not self.base_path:
            return None
        return f"{self.base_path}{item.pk}/"

    def _action_paths(self, item):
        if not self.base_path:
            return None, None
        return (
            f"{self.base_path}{item.pk}/approve/",
            f"{self.base_path}{item.pk}/reject/",
        )


class ServiceRequestApprovalProvider(ApprovalProvider):
    key = "service_request"
    label = "Service Request"
    base_path = "/api/services/requests/"

    def can_view(self, user):
        role = getattr(user, "role", "")
        return user.is_authenticated and role in (
            "system_admin", "it_manager", "it_support") or getattr(
                user, "is_superuser", False)

    def get_queryset(self, user):
        return (ServiceRequest.objects
                .filter(status="pending_approval", approval_required=True)
                .select_related("catalogue_item", "requester",
                                "department", "requester__home_department")
                .order_by("submitted_at"))

    def can_approve(self, user, item):
        if not self.can_view(user):
            return False
        role = getattr(user, "role", "")
        if role not in ("system_admin", "it_manager") and not getattr(
                user, "is_superuser", False):
            return False
        # Separation of duties: requester cannot approve their own request.
        return getattr(item, "requester_id", None) != getattr(user, "pk", None)

    def can_reject(self, user, item):
        return self.can_approve(user, item)

    def serialize(self, item, user):
        approve_path, reject_path = self._action_paths(item)
        return {
            "approval_type": self.key,
            "approval_type_label": self.label,
            "object_id": str(item.pk),
            "reference": getattr(item, "request_number", "") or "",
            "title": "Service Request: %s" % getattr(
                item.catalogue_item, "name", "") if getattr(
                    item, "catalogue_item_id", None) else "Service Request",
            "description_summary": (getattr(item, "description", "") or "")[:200],
            "requester": _safe_email(getattr(item, "requester", None)),
            "department": _safe_name(getattr(item, "department", None)),
            "submitted_at": _iso(getattr(item, "submitted_at", None)),
            "due_at": None,
            "priority": getattr(item, "priority", "") or "",
            "status": getattr(item, "status", "") or "",
            "current_approver": _safe_email(getattr(item, "approver", None)),
            "can_approve": self.can_approve(user, item),
            "can_reject": self.can_reject(user, item),
            "detail_path": self._detail_path(item),
            "approve_api_path": approve_path if self.can_approve(user, item) else None,
            "reject_api_path": reject_path if self.can_reject(user, item) else None,
            "metadata": {
                "service": getattr(
                    item.catalogue_item, "name", "") if getattr(
                        item, "catalogue_item_id", None) else None,
                "request_status": item.status,
            },
        }


class DisposalApprovalProvider(ApprovalProvider):
    key = "disposal"
    label = "Asset Disposal"
    base_path = "/api/assets/disposals/"

    def can_view(self, user):
        return ServiceRequestApprovalProvider.can_view(self, user)

    def get_queryset(self, user):
        return (Disposal.objects
                .filter(approval_status="pending")
                .select_related("asset", "created_by")
                .order_by("id"))

    def can_approve(self, user, item):
        if not self.can_view(user):
            return False
        role = getattr(user, "role", "")
        if role not in ("system_admin", "it_manager") and not getattr(
                user, "is_superuser", False):
            return False
        return getattr(item, "created_by_id", None) != getattr(
            user, "pk", None)

    def can_reject(self, user, item):
        return self.can_approve(user, item)

    def serialize(self, item, user):
        approve_path, reject_path = self._action_paths(item)
        asset = getattr(item, "asset", None)
        return {
            "approval_type": self.key,
            "approval_type_label": self.label,
            "object_id": str(item.pk),
            "reference": "Asset %s" % getattr(asset, "asset_tag", "") if asset else "",
            "title": "Disposal: %s" % getattr(asset, "name", "") if asset else "Disposal",
            "description_summary": (getattr(item, "disposal_reason", "") or "")[:200],
            "requester": _safe_email(getattr(item, "created_by", None)),
            "department": None,
            "submitted_at": _iso(getattr(item, "created_at", None)),
            "due_at": None,
            "priority": "",
            "status": getattr(item, "approval_status", "") or "",
            "current_approver": _safe_email(getattr(item, "approver", None)),
            "can_approve": self.can_approve(user, item),
            "can_reject": self.can_reject(user, item),
            "detail_path": self._detail_path(item),
            "approve_api_path": approve_path if self.can_approve(user, item) else None,
            "reject_api_path": reject_path if self.can_reject(user, item) else None,
            "metadata": {
                "asset_tag": getattr(asset, "asset_tag", None) if asset else None,
                "asset_name": getattr(asset, "name", None) if asset else None,
                "disposal_method": getattr(item, "disposal_method", "") or "",
            },
        }


class WorkflowApprovalProvider(ApprovalProvider):
    key = "workflow_approval"
    label = "Workflow Approval"
    base_path = "/api/workflow/approval-requests/"

    def can_view(self, user):
        return ServiceRequestApprovalProvider.can_view(self, user)

    def get_queryset(self, user):
        return (ApprovalRequest.objects
                .filter(status="pending")
                .select_related("ticket", "requested_by")
                .order_by("id"))

    def can_approve(self, user, item):
        if not self.can_view(user):
            return False
        role = getattr(user, "role", "")
        if role not in ("system_admin", "it_manager") and not getattr(
                user, "is_superuser", False):
            return False
        # Requester cannot decide their own approval request.
        return getattr(item, "requested_by_id", None) != getattr(
            user, "pk", None)

    def can_reject(self, user, item):
        return self.can_approve(user, item)

    def serialize(self, item, user):
        approve_path, reject_path = self._action_paths(item)
        return {
            "approval_type": self.key,
            "approval_type_label": self.label,
            "object_id": str(item.pk),
            "reference": "Workflow #%s" % item.pk,
            "title": "Approval: %s" % (
                getattr(item, "operation_display", None)
                or getattr(item, "operation", "") or ""),
            "description_summary": "",
            "requester": _safe_email(getattr(item, "requested_by", None)),
            "department": None,
            "submitted_at": _iso(getattr(item, "created_at", None)),
            "due_at": None,
            "priority": "",
            "status": getattr(item, "status", "") or "",
            "current_approver": _safe_email(getattr(item, "approver", None)),
            "can_approve": self.can_approve(user, item),
            "can_reject": self.can_reject(user, item),
            "detail_path": self._detail_path(item),
            "approve_api_path": approve_path if self.can_approve(user, item) else None,
            "reject_api_path": reject_path if self.can_reject(user, item) else None,
            "metadata": {
                "operation": getattr(item, "operation", "") or "",
                "ticket_number": getattr(item, "ticket_id", None),
            },
        }


class KnowledgeBaseReviewProvider(ApprovalProvider):
    key = "knowledge_base"
    label = "Knowledge Base Review"
    base_path = "/api/assets/knowledge-base/"

    def can_view(self, user):
        return ServiceRequestApprovalProvider.can_view(self, user)

    def get_queryset(self, user):
        return (KnowledgeBaseArticle.objects
                .filter(status="pending_review")
                .select_related("category", "author")
                .order_by("id"))

    def can_approve(self, user, item):
        if not self.can_view(user):
            return False
        role = getattr(user, "role", "")
        if role not in ("system_admin", "it_manager") and not getattr(
                user, "is_superuser", False):
            return False
        # Self-review is prohibited: submitter cannot approve their own article.
        return getattr(item, "author_id", None) != getattr(
            user, "pk", None)

    def can_reject(self, user, item):
        return self.can_approve(user, item)

    def serialize(self, item, user):
        # Knowledge Base governance actions live in the domain ViewSet; the
        # center surfaces read-only links only.
        return {
            "approval_type": self.key,
            "approval_type_label": self.label,
            "object_id": str(item.pk),
            "reference": "KB #%s" % item.pk,
            "title": "Review: %s" % (getattr(item, "title", "") or ""),
            "description_summary": (getattr(item, "summary", "") or "")[:200],
            "requester": _safe_email(getattr(item, "author", None)),
            "department": None,
            "submitted_at": _iso(getattr(item, "submitted_at", None)
                                   or getattr(item, "created_at", None)),
            "due_at": None,
            "priority": "",
            "status": getattr(item, "status", "") or "",
            "current_approver": _safe_email(getattr(item, "reviewed_by", None)),
            "can_approve": False,
            "can_reject": False,
            "detail_path": self._detail_path(item),
            "approve_api_path": None,
            "reject_api_path": None,
            "metadata": {
                "article_category": getattr(
                    item.category, "name", None) if getattr(
                        item, "category_id", None) else None,
                "revision_number": getattr(item, "revision_number", None),
            },
        }


class PurchaseRequestApprovalProvider(ApprovalProvider):
    key = "purchase_request"
    label = "Purchase Request"
    base_path = "/api/procurement/purchase-requests/"

    def can_view(self, user):
        return ServiceRequestApprovalProvider.can_view(self, user)

    def get_queryset(self, user):
        if not HAS_PROCUREMENT:
            return PurchaseRequest.objects.none()  # type: ignore[name-defined]
        return (PurchaseRequest.objects
                .filter(status="pending_approval", approver__isnull=True)
                .select_related("requester", "department")
                .order_by("id"))

    def can_approve(self, user, item):
        if not self.can_view(user):
            return False
        role = getattr(user, "role", "")
        if role == "system_admin" or getattr(user, "is_superuser", False):
            return getattr(item, "requester_id", None) != getattr(
                user, "pk", None)
        if role == "it_manager":
            # IT Manager cannot approve items requiring System Admin approval.
            if getattr(item, "requires_system_admin_approval", False):
                return False
            return getattr(item, "requester_id", None) != getattr(
                user, "pk", None)
        return False

    def can_reject(self, user, item):
        return self.can_approve(user, item)

    def serialize(self, item, user):
        approve_path, reject_path = self._action_paths(item)
        return {
            "approval_type": self.key,
            "approval_type_label": self.label,
            "object_id": str(item.pk),
            "reference": getattr(item, "pr_number", "") or "",
            "title": "Purchase Request: %s" % (
                (getattr(item, "reason", "") or "")[:50] or "Unnamed"),
            "description_summary": (getattr(item, "notes", "") or "")[:200],
            "requester": _safe_email(getattr(item, "requester", None)),
            "department": _safe_name(getattr(item, "department", None)),
            "submitted_at": _iso(getattr(item, "created_at", None)),
            "due_at": None,
            "priority": "",
            "status": getattr(item, "status", "") or "",
            "current_approver": _safe_email(getattr(item, "approver", None)),
            "can_approve": self.can_approve(user, item),
            "can_reject": self.can_reject(user, item),
            "detail_path": self._detail_path(item),
            "approve_api_path": approve_path if self.can_approve(user, item) else None,
            "reject_api_path": reject_path if self.can_reject(user, item) else None,
            "metadata": {
                "estimated_total": str(
                    getattr(item, "estimated_total", 0) or 0),
                "requires_system_admin_approval": bool(
                    getattr(item, "requires_system_admin_approval", False)),
            },
        }


class PurchaseOrderApprovalProvider(ApprovalProvider):
    key = "purchase_order"
    label = "Purchase Order"
    base_path = "/api/procurement/purchase-orders/"

    def can_view(self, user):
        return ServiceRequestApprovalProvider.can_view(self, user)

    def get_queryset(self, user):
        if not HAS_PROCUREMENT:
            return PurchaseOrder.objects.none()  # type: ignore[name-defined]
        return (PurchaseOrder.objects
                .filter(status="pending_approval", approver__isnull=True)
                .select_related("vendor", "created_by")
                .order_by("id"))

    def can_approve(self, user, item):
        if not self.can_view(user):
            return False
        role = getattr(user, "role", "")
        if role == "system_admin" or getattr(user, "is_superuser", False):
            return getattr(item, "created_by_id", None) != getattr(
                user, "pk", None)
        if role == "it_manager":
            if getattr(item, "requires_system_admin_approval", False):
                return False
            return getattr(item, "created_by_id", None) != getattr(
                user, "pk", None)
        return False

    def can_reject(self, user, item):
        return self.can_approve(user, item)

    def serialize(self, item, user):
        approve_path, reject_path = self._action_paths(item)
        vendor = getattr(item, "vendor", None)
        return {
            "approval_type": self.key,
            "approval_type_label": self.label,
            "object_id": str(item.pk),
            "reference": getattr(item, "po_number", "") or "",
            "title": "Purchase Order: %s" % (
                getattr(vendor, "name", "") if vendor else ""),
            "description_summary": "Total: %s" % (
                getattr(item, "total", None) or 0),
            "requester": _safe_email(getattr(item, "created_by", None)),
            "department": None,
            "submitted_at": _iso(getattr(item, "created_at", None)),
            "due_at": None,
            "priority": "",
            "status": getattr(item, "status", "") or "",
            "current_approver": _safe_email(getattr(item, "approver", None)),
            "can_approve": self.can_approve(user, item),
            "can_reject": self.can_reject(user, item),
            "detail_path": self._detail_path(item),
            "approve_api_path": approve_path if self.can_approve(user, item) else None,
            "reject_api_path": reject_path if self.can_reject(user, item) else None,
            "metadata": {
                "vendor": getattr(vendor, "name", None) if vendor else None,
                "currency": getattr(item, "currency", "") or "",
            },
        }


# Ordered registry of providers. Optional providers (procurement) are included
# but degrade gracefully when the app is unavailable.
REGISTRY = [
    ServiceRequestApprovalProvider(),
    DisposalApprovalProvider(),
    WorkflowApprovalProvider(),
    KnowledgeBaseReviewProvider(),
    PurchaseRequestApprovalProvider(),
    PurchaseOrderApprovalProvider(),
]

# Maximum rows fetched per provider when aggregating (bounded aggregation).
PER_PROVIDER_LIMIT = 200

# Due-soon window (days). Configurable-ish constant; not a user setting.
DUE_SOON_DAYS = 3


def _collect(user, limit_per_provider):
    """Fetch, normalize, and return items from every enabled provider."""
    items = []
    for provider in REGISTRY:
        if not provider.can_view(user):
            continue
        try:
            qs = provider.get_queryset(user)[:limit_per_provider]
        except Exception:
            # A provider must never break the aggregation.
            continue
        for item in qs:
            try:
                items.append(provider.serialize(item, user))
            except Exception:
                continue
    return items


def get_pending_approvals(user, limit=100):
    """
    Returns a unified list of approval items awaiting action, normalized
    across providers. Sorted oldest-first (by submitted_at). Bounded.
    """
    if user is None or not getattr(user, "pk", None) or not user.is_authenticated:
        return []
    # Fetch enough from each provider to fill a page after filtering/sorting.
    fetch = max(limit, 25) * len(REGISTRY) + PER_PROVIDER_LIMIT
    items = _collect(user, fetch)
    items.sort(key=lambda it: it.get("submitted_at") or "")
    return items[:limit]


def get_approval_counts(user):
    """Role-scoped counts of pending approvals by type, suitable for badges."""
    keys = [p.key for p in REGISTRY]
    counts = {key: 0 for key in keys}
    counts["total"] = 0
    if user is None or not getattr(user, "pk", None) or not user.is_authenticated:
        return counts
    for provider in REGISTRY:
        if not provider.can_view(user):
            continue
        try:
            summary = provider.get_summary(user)
        except Exception:
            continue
        count = int(summary.get("count", 0) or 0)
        counts[provider.key] = count
        counts["total"] += count
    return counts


def _parse_bool(val):
    if val is None:
        return None
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _is_overdue(item):
    due = item.get("due_at")
    if not due:
        return False
    try:
        return due < timezone.now().isoformat()
    except Exception:
        return False


def _is_due_soon(item):
    due = item.get("due_at")
    if not due:
        return False
    try:
        from datetime import timedelta
        soon = timezone.now() + timedelta(days=DUE_SOON_DAYS)
        return timezone.now().isoformat() <= due <= soon.isoformat()
    except Exception:
        return False


def filter_and_sort(items, user, filters):
    """Apply search, filters, ordering, and pagination to aggregated items.

    Returns (page_items, total_count).
    """
    q = (filters.get("q") or "").strip().lower()
    approval_type = (filters.get("approval_type") or "").strip()
    department = (filters.get("department") or "").strip()
    priority = (filters.get("priority") or "").strip()
    requester = (filters.get("requester") or "").strip().lower()
    date_from = (filters.get("date_from") or "").strip()
    date_to = (filters.get("date_to") or "").strip()
    overdue_only = _parse_bool(filters.get("overdue"))
    due_soon_only = _parse_bool(filters.get("due_soon"))

    home_dept = _home_department(user)
    is_sys_admin = getattr(user, "is_superuser", False) or getattr(
        user, "role", "") == "system_admin"

    out = []
    for it in items:
        if approval_type and it.get("approval_type") != approval_type:
            continue
        if priority and it.get("priority") != priority:
            continue
        if requester:
            req = (it.get("requester") or "").lower()
            if requester not in req:
                continue
        # Department scope: non-system admins may only see their own department.
        dept = it.get("department") or ""
        if department:
            if not is_sys_admin and department != home_dept:
                continue
            if dept != department:
                continue
        else:
            if not is_sys_admin and dept and dept != home_dept:
                continue
        if q:
            haystack = " ".join([
                str(it.get("title", "")), str(it.get("reference", "")),
                str(it.get("requester", "")),
            ]).lower()
            if q not in haystack:
                continue
        if date_from and it.get("submitted_at", "") < date_from:
            continue
        if date_to and it.get("submitted_at", "") > date_to:
            continue
        if overdue_only and not _is_overdue(it):
            continue
        if due_soon_only and not _is_due_soon(it):
            continue
        out.append(it)

    ordering = (filters.get("ordering") or "submitted_at").strip()
    reverse = ordering.startswith("-")
    key = ordering.lstrip("-")

    def sort_key(it):
        return it.get(key) or ""

    out.sort(key=sort_key, reverse=reverse)

    total = len(out)
    page_size = filters.get("page_size")
    try:
        page_size = int(page_size) if page_size is not None else 20
    except (TypeError, ValueError):
        page_size = 20
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100
    page = filters.get("page")
    try:
        page = int(page) if page is not None else 1
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    start = (page - 1) * page_size
    return out[start:start + page_size], total
