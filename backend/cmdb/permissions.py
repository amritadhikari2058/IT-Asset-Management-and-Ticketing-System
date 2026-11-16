"""CMDB role-based permissions (spec section 26).

Matrix (active, authenticated users only):
- Employee / unknown role / inactive  -> denied everywhere (403).
- IT Support  -> read-most; create manual/draft CIs; update operational
  fields; verify CIs; create proposed relationships; acknowledge drift;
  no retirement, no baseline approval, no CI Type schema management.
- IT Manager  -> everything except baseline self-approval and accepting
  critical drift (system admin only for critical accept per policy).
- System Admin -> full access; sole acceptor of critical drift.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

# CI Type schema/definition management
TYPE_MANAGE_ROLES = ("system_admin", "it_manager")
# CI retirement, relationship activation, baseline create/approve,
# drift resolve/false-positive
ELEVATED_ROLES = ("system_admin", "it_manager")
# Critical drift acceptance
CRITICAL_ACCEPT_ROLES = ("system_admin",)

# Fields IT Support may not modify on an existing CI.
SUPPORT_READONLY_FIELDS = frozenset({
    "ci_type", "asset", "software_product", "source", "source_identifier",
    "external_reference", "created_by",
})

# Statuses support must not set (retirement is an elevated action).
SUPPORT_FORBIDDEN_STATUSES = frozenset({"retired", "disposed"})


def get_user_role(user):
    """Safely extract user role, respecting superusers and active flags."""
    if not user or not user.is_authenticated or not user.is_active:
        return ""
    if getattr(user, "is_superuser", False):
        return "system_admin"
    return getattr(user, "role", "") or ""


def is_system_admin(user):
    return get_user_role(user) == "system_admin"


def is_it_manager(user):
    return get_user_role(user) == "system_admin" or get_user_role(user) == "it_manager"


def is_it_support(user):
    return get_user_role(user) in ("system_admin", "it_manager", "it_support")


def is_staff(user):
    return get_user_role(user) in ("system_admin", "it_manager", "it_support")


def is_employee(user):
    return get_user_role(user) == "employee"


def _authenticated_active(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    )


class CMDBPermission(BasePermission):
    """Baseline CMDB access: staff only, employees denied."""

    def has_permission(self, request, view):
        if not _authenticated_active(request.user):
            return False
        if is_employee(request.user):
            return False
        return is_staff(request.user)

    def has_object_permission(self, request, view, obj):
        if not _authenticated_active(request.user):
            return False
        if is_employee(request.user):
            return False
        return is_staff(request.user)


class CMDBReadOnlyPermission(CMDBPermission):
    """Staff may read; writes require elevated roles."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_it_manager(request.user)


class CITypePermission(CMDBPermission):
    """CI Type management: system admin and IT manager only."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return get_user_role(request.user) in TYPE_MANAGE_ROLES

    def has_object_permission(self, request, view, obj):
        if not super().has_object_permission(request, view, obj):
            return False
        if request.method in SAFE_METHODS:
            return True
        return get_user_role(request.user) in TYPE_MANAGE_ROLES


class CIPermission(CMDBPermission):
    """CI CRUD with field-level support limits handled in serializers.

    Support may read everything and attempt creates/updates; the serializer
    enforces operational-field limits and blocks retirement-like statuses.
    Retirement itself is gated in the retire action.
    """

    def has_permission(self, request, view):
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        return super().has_object_permission(request, view, obj)


class RelationshipPermission(CMDBPermission):
    """Relationships: support may create proposed links only.

    Activation/deactivation/confirmation requires manager/admin.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        role = get_user_role(request.user)
        if role in ELEVATED_ROLES:
            return True
        if role == "it_support" and request.method == "POST":
            return True  # serializer/view restricts support to status=proposed
        return False

    def has_object_permission(self, request, view, obj):
        if not super().has_object_permission(request, view, obj):
            return False
        if request.method in SAFE_METHODS:
            return True
        role = get_user_role(request.user)
        if role in ELEVATED_ROLES:
            return True
        # Support may PATCH proposed relationships they could create, but
        # never activate them; enforced in the view action checks too.
        return role == "it_support" and request.method == "PATCH"


class BaselinePermission(CMDBPermission):
    """Baseline create/edit/approve: manager/admin; support read-only."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_it_manager(request.user)

    def has_object_permission(self, request, view, obj):
        if not super().has_object_permission(request, view, obj):
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_it_manager(request.user)


class DriftPermission(CMDBPermission):
    """Drift findings: staff read; support may acknowledge; elevated resolve.

    Accepting a critical-severity finding is restricted to system admin
    (checked in the action itself because it depends on object severity).
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        role = get_user_role(request.user)
        if role in ELEVATED_ROLES:
            return True
        # Support must reach actions/views for 405/403 action-gating as
        # specified (e.g. unsupported methods -> 405 when access exists).
        if role == "it_support":
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if not super().has_object_permission(request, view, obj):
            return False
        if request.method in SAFE_METHODS:
            return True
        role = get_user_role(request.user)
        if role in ELEVATED_ROLES:
            return True
        # Support has object access (acknowledge); unsupported methods must
        # reach the view so DRF/viewset can return 405 instead of 403.
        return role == "it_support"


class HistoryPermission(CMDBPermission):
    """History is strictly read-only for all staff."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.method in SAFE_METHODS
