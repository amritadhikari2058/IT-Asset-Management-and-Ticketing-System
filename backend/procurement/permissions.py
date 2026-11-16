from rest_framework.permissions import BasePermission


def procurement_role(user):
    return getattr(user, "role", "") if getattr(user, "is_authenticated", False) else ""


def can_view_procurement(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            procurement_role(user) in ("system_admin", "it_manager", "it_support")
            or getattr(user, "is_superuser", False)
        )
    )


def is_manager_or_admin(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            procurement_role(user) in ("system_admin", "it_manager")
            or getattr(user, "is_superuser", False)
        )
    )


def is_system_admin(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (procurement_role(user) == "system_admin" or getattr(user, "is_superuser", False))
    )


class CanViewProcurement(BasePermission):
    def has_permission(self, request, view):
        return can_view_procurement(request.user)


class CanManageProcurementFinance(BasePermission):
    """IT Manager / System Admin for financial approval actions."""

    def has_permission(self, request, view):
        return is_manager_or_admin(request.user)
