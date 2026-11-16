"""Permissions for monitoring module."""

from rest_framework import permissions


class SystemAdminPermission(permissions.BasePermission):
    """Permission for System Admin only."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "role", "") == "system_admin")


class ITManagerPermission(permissions.BasePermission):
    """Permission for IT Manager and above."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", "")
            in ("system_admin", "it_manager")
        )


class ITSupportPermission(permissions.BasePermission):
    """Permission for IT Support and above."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", "")
            in ("system_admin", "it_manager", "it_support")
        )
