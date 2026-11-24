"""Change management permissions."""

from rest_framework.permissions import BasePermission


def _is_system_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "role", "") == "system_admin" or getattr(user, "is_superuser", False))
    )


def _is_it_manager(user):
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "role", "") == "it_manager" or getattr(user, "is_superuser", False))
    )


def _is_staff(user):
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
        or getattr(user, "is_superuser", False)
    )


def _can_manage(user):
    """System Admin or IT Manager can manage templates, windows, approve critical changes."""
    return _is_system_admin(user) or _is_it_manager(user)


def _can_approve(user):
    """IT Manager or System Admin can approve normal/critical changes."""
    return _can_manage(user)


class IsChangeSystemAdmin(BasePermission):
    def has_permission(self, request, view):
        return _is_system_admin(request.user)


class IsChangeStaff(BasePermission):
    def has_permission(self, request, view):
        return _is_staff(request.user)


class IsChangeManagerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return _can_manage(request.user)


class IsChangeApprover(BasePermission):
    def has_permission(self, request, view):
        return _can_approve(request.user)


class IsChangeCloser(BasePermission):
    def has_permission(self, request, view):
        return _can_manage(request.user)
