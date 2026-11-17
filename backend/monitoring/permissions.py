"""Permissions for monitoring module."""

from rest_framework import permissions

from .models import MonitoringSource


class IsMonitoringSource(permissions.BasePermission):
    """Permission for authenticated MonitoringSource principals."""

    def has_permission(self, request, view):
        return isinstance(request.user, MonitoringSource) and request.user.is_active


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
