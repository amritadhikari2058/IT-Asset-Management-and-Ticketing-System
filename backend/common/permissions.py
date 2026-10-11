"""DRF permission helpers. All deletion/hard-delete gates live here + views."""
from rest_framework.permissions import BasePermission


def is_system_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "role", "") == "system_admin" or user.is_superuser)
    )


class IsSystemAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_system_admin(request.user)


class IsITStaff(BasePermission):
    """IT Manager, IT Support, or System Admin."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", "") in
            ("system_admin", "it_manager", "it_support")
            or getattr(request.user, "is_superuser", False)
        )
