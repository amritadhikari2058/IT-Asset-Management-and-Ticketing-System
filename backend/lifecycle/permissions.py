"""Lifecycle permissions.

Backend enforcement (frontend hiding is not security).
"""
from rest_framework.permissions import BasePermission

from accounts.models import User


def _role(user):
    return getattr(user, "role", "")


def is_system_admin(user):
    return bool(
        user and user.is_authenticated
        and (_role(user) == "system_admin" or getattr(user, "is_superuser", False))
    )


def is_it_staff(user):
    """System Admin, IT Manager, or IT Support."""
    return bool(
        user and user.is_authenticated
        and _role(user) in ("system_admin", "it_manager", "it_support")
        or getattr(user, "is_superuser", False)
    )


def is_it_manager_or_admin(user):
    return bool(
        user and user.is_authenticated
        and _role(user) in ("system_admin", "it_manager")
        or getattr(user, "is_superuser", False)
    )


class IsLifecycleStaff(BasePermission):
    """IT staff and above may manage lifecycle cases/tasks."""

    def has_permission(self, request, view):
        return is_it_staff(request.user)


class IsLifecycleManagerOrAdmin(BasePermission):
    """System Admin / IT Manager only."""

    def has_permission(self, request, view):
        return is_it_manager_or_admin(request.user)


class IsLifecycleSystemAdmin(BasePermission):
    """System Admin only."""

    def has_permission(self, request, view):
        return is_system_admin(request.user)


class IsEmployee(BasePermission):
    """Ordinary employee role."""

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and _role(request.user) == "employee"
        )
