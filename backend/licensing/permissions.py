"""Role-Based Access Control and Object-Level Permissions for Licensing.

Enforces strict separation of duties:
- System Admin: Full administrative privileges, secret revelation, high-cost renewal approval,
  agreement termination, and compliance resolution.
- IT Manager: Product/agreement management, allocation/revocation, document management,
  ordinary renewal reviews (under threshold), financial visibility.
- IT Support: Operational allocations, installation tracking, verification, basic document uploads.
  No secret revelation, no renewal approvals, no contract terminations.
- Employee: View approved software catalog and own allocations only. Denied all financial,
  secret, and compliance management views.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


def get_user_role(user) -> str:
    """Safely extract user role, respecting superusers and active flags."""
    if not user or not user.is_authenticated or not user.is_active:
        return ""
    if getattr(user, "is_superuser", False):
        return "system_admin"
    return getattr(user, "role", "")


def is_system_admin(user) -> bool:
    return get_user_role(user) == "system_admin"


def is_it_manager(user) -> bool:
    return get_user_role(user) in ("system_admin", "it_manager")


def is_it_staff(user) -> bool:
    return get_user_role(user) in ("system_admin", "it_manager", "it_support")


def is_employee(user) -> bool:
    return get_user_role(user) == "employee"


class IsSystemAdminOnly(BasePermission):
    """Exclusive access for System Administrators."""

    def has_permission(self, request, view):
        return is_system_admin(request.user)

    def has_object_permission(self, request, view, obj):
        return is_system_admin(request.user)


class IsITManagerOrAdmin(BasePermission):
    """Access for IT Managers and System Administrators."""

    def has_permission(self, request, view):
        return is_it_manager(request.user)

    def has_object_permission(self, request, view, obj):
        return is_it_manager(request.user)


class IsITStaffUser(BasePermission):
    """Operational access for IT Support, IT Managers, and System Admins."""

    def has_permission(self, request, view):
        return is_it_staff(request.user)

    def has_object_permission(self, request, view, obj):
        return is_it_staff(request.user)


class SoftwareProductPermission(BasePermission):
    """Permission policy for Software Products catalog.

    - Authenticated Employees can view approved products (SAFE_METHODS).
    - IT Staff can view all active products.
    - IT Managers and System Admins can create/edit products.
    - Only System Admins can prohibit or retire products.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated or not request.user.is_active:
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_it_manager(request.user)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated or not request.user.is_active:
            return False
        if request.method in SAFE_METHODS:
            if is_it_staff(request.user):
                return True
            # Regular employee may only see non-deleted, approved or restricted products
            return not obj.is_deleted and obj.approved_status in ("approved", "restricted")
        return is_it_manager(request.user)


class LicenseAgreementPermission(BasePermission):
    """Permission policy for License Agreements.

    - IT Staff may read.
    - IT Managers and System Admins may create and modify.
    - Only System Admins may terminate agreements.
    - Employees are strictly denied.
    """

    def has_permission(self, request, view):
        return is_it_staff(request.user)

    def has_object_permission(self, request, view, obj):
        return is_it_staff(request.user)


class LicenseSecretPermission(BasePermission):
    """Permission policy for License Secrets.

    - Secret list/detail (metadata only): IT Managers and System Admins.
    - Secret creation / rotation / revocation: IT Managers and System Admins.
    - Plaintext reveal: Strictly System Admin only.
    - Employees & IT Support: Denied.
    """

    def has_permission(self, request, view):
        if view.action == "reveal":
            return is_system_admin(request.user)
        return is_it_manager(request.user)

    def has_object_permission(self, request, view, obj):
        if view.action == "reveal":
            return is_system_admin(request.user)
        return is_it_manager(request.user)


class LicenseAllocationPermission(BasePermission):
    """Permission policy for License Allocations.

    - Employees can only view their own active allocations.
    - IT Staff can view, create, activate, suspend, and revoke allocations.
    - Employees cannot allocate licenses.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated or not request.user.is_active:
            return False
        if is_it_staff(request.user):
            return True
        # Employee may read own allocations
        return request.method in SAFE_METHODS

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated or not request.user.is_active:
            return False
        if is_it_staff(request.user):
            return True
        # Employee object-level scoping
        return (
            request.method in SAFE_METHODS
            and obj.allocation_type == "user"
            and obj.assigned_user_id == request.user.pk
        )


class SoftwareInstallationPermission(BasePermission):
    """Permission policy for Software Installations.

    - IT Staff can view and manage installations.
    - Employees are denied.
    """

    def has_permission(self, request, view):
        return is_it_staff(request.user)

    def has_object_permission(self, request, view, obj):
        return is_it_staff(request.user)


class LicenseRenewalPermission(BasePermission):
    """Permission policy for Renewal requests.

    - IT Staff can view and draft renewals.
    - Approval requires IT Manager (ordinary) or System Admin (above threshold).
    - Requester cannot approve their own renewal (separation of duties).
    """

    def has_permission(self, request, view):
        return is_it_staff(request.user)

    def has_object_permission(self, request, view, obj):
        if view.action == "approve":
            # Requester cannot approve own renewal
            if obj.requested_by_id == request.user.pk:
                return False
            return is_it_manager(request.user)
        return is_it_staff(request.user)


class LicenseCompliancePermission(BasePermission):
    """Permission policy for Compliance findings.

    - IT Staff can view findings.
    - Acknowledgment: IT Support, IT Manager, System Admin.
    - Remediation / Resolution / False Positive: IT Manager, System Admin.
    - Employees: Denied.

    Manager-only actions are rejected here, before the view body runs, so direct
    API calls cannot reach the service and receive a misleading 400.
    """

    MANAGER_ACTIONS = ("remediate", "resolve", "false_positive")

    def has_permission(self, request, view):
        return is_it_staff(request.user)

    def has_object_permission(self, request, view, obj):
        if view.action in self.MANAGER_ACTIONS:
            return is_it_manager(request.user)
        return is_it_staff(request.user)


class LicenseDocumentPermission(BasePermission):
    """Permission policy for License Documents.

    - IT Staff can view and download.
    - IT Managers and System Admins can upload and delete.
    - Employees: Denied.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return is_it_staff(request.user)
        return is_it_manager(request.user)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return is_it_staff(request.user)
        return is_it_manager(request.user)
