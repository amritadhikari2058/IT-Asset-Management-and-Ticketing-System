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


def _is_it_support(user):
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "role", "") == "it_support"
    )


def _is_employee(user):
    return bool(user and user.is_authenticated and getattr(user, "role", "") == "employee")


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


def _can_approve_emergency(user):
    """IT Manager or System Admin can authorize emergency changes."""
    return _can_manage(user)


def _can_schedule(user):
    """IT Manager or System Admin can finalize scheduling."""
    return _can_manage(user)


def _can_implement(user):
    """IT staff can implement assigned changes."""
    return _is_staff(user)


def _can_close(user):
    """IT Manager or System Admin can close changes."""
    return _can_manage(user)


def _can_waive_pir(user):
    """System Admin only can waive PIR."""
    return _is_system_admin(user)


def _can_override_conflict(user):
    """IT Manager or System Admin can override high/critical conflicts."""
    return _can_manage(user)


class IsChangeSystemAdmin(BasePermission):
    def has_permission(self, request, view):
        return _is_system_admin(request.user)


class IsChangeManager(BasePermission):
    def has_permission(self, request, view):
        return _is_it_manager(request.user)


class IsChangeStaff(BasePermission):
    def has_permission(self, request, view):
        return _is_staff(request.user)


class IsChangeManagerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return _can_manage(request.user)


class IsChangeApprover(BasePermission):
    def has_permission(self, request, view):
        return _can_approve(request.user)


class IsChangeScheduling(BasePermission):
    def has_permission(self, request, view):
        return _can_schedule(request.user)


class IsChangeImplementer(BasePermission):
    def has_permission(self, request, view):
        return _can_implement(request.user)


class IsChangeCloser(BasePermission):
    def has_permission(self, request, view):
        return _can_close(request.user)


class IsChangePIRWaiver(BasePermission):
    def has_permission(self, request, view):
        return _can_waive_pir(request.user)


class IsChangeConflictOverride(BasePermission):
    def has_permission(self, request, view):
        return _can_override_conflict(request.user)
