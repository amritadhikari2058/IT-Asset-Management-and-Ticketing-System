from rest_framework.permissions import BasePermission
from accounts.models import User

def is_system_admin(user):
    return bool(user and (getattr(user, "is_superuser", False) or getattr(user, "role", "") == "system_admin"))
def is_it_manager(user):
    return bool(user and getattr(user, "role", "") == "it_manager")
def is_it_support(user):
    return bool(user and getattr(user, "role", "") == "it_support")
def is_staff(user):
    return bool(user and (is_system_admin(user) or is_it_manager(user) or is_it_support(user)))
def is_employee(user):
    return bool(user and getattr(user, "role", "") == "employee")

class CMDBPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if is_employee(user):
            return False
        return is_staff(user)
    def has_object_permission(self, request, view, obj):
        return is_staff(request.user)
