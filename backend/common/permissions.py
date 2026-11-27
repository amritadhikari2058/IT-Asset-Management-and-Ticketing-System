"""DRF permission helpers. All deletion/hard-delete gates live here + views."""
from rest_framework.permissions import BasePermission


def is_system_admin(user):
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "is_active", False)
        and (getattr(user, "role", "") == "system_admin" or user.is_superuser)
    )


def is_it_staff(user):
    """True for active System Admin / IT Manager / IT Support (or superuser)."""
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "is_active", False)
        and (
            getattr(user, "role", "") in
            ("system_admin", "it_manager", "it_support")
            or getattr(user, "is_superuser", False)
        )
    )


class IsActiveAuthenticated(BasePermission):
    """Authenticated and active account. Disabled users must be denied."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and getattr(user, "is_active", False))


class IsSystemAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_system_admin(request.user)


class IsITStaff(BasePermission):
    """IT Manager, IT Support, or System Admin."""

    def has_permission(self, request, view):
        return is_it_staff(getattr(request, "user", None))
