"""PM1 role matrix (§36) and scoped-access helpers.

Employee / unknown / inactive users are denied Problem Management APIs at
the permission-class level (no enumeration). Scoped object querysets give
404 for cross-scope access where existence is hidden.
"""
from rest_framework.permissions import BasePermission

STAFF_ROLES = {"system_admin", "it_manager", "it_support"}
GOVERNANCE_ROLES = {"system_admin", "it_manager"}


def _role(user):
    return getattr(user, "role", "") or ""


def is_system_admin(user):
    return bool(user and user.is_authenticated and user.is_active and _role(user) == "system_admin")


def is_it_manager(user):
    """True for IT Manager and System Admin (governance tier)."""
    return bool(
        user and user.is_authenticated and user.is_active
        and _role(user) in GOVERNANCE_ROLES
    )


def is_it_support(user):
    return bool(
        user and user.is_authenticated and user.is_active
        and _role(user) == "it_support"
    )


def is_staff_role(user):
    return bool(
        user and user.is_authenticated and user.is_active
        and _role(user) in STAFF_ROLES
    )


def can_manage_problems(user):
    """Create/manage/accept/reject/approve: manager + system admin."""
    return is_it_manager(user)


def can_create_problem(user):
    """Staff may create Draft Problems (support operational visibility)."""
    return is_staff_role(user)


def can_review_candidates(user):
    """Support may review where policy permits; acceptance is governance."""
    return is_staff_role(user)


def can_accept_candidate(user):
    return is_it_manager(user)


class ProblemManagementPermission(BasePermission):
    """Any authenticated, active staff role. Employees/unknown denied."""

    def has_permission(self, request, view):
        return is_staff_role(request.user)


class IsProblemGovernance(BasePermission):
    """Manager/System-Admin tier for governance actions."""

    def has_permission(self, request, view):
        return is_it_manager(request.user)


class IsSystemAdminOnly(BasePermission):
    def has_permission(self, request, view):
        return is_system_admin(request.user)
