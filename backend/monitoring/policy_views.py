"""Views for MonitoringAutomationPolicy CRUD operations."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import MonitoringAutomationPolicy, MonitoringSource
from .permissions import SystemAdminPermission, ITSupportPermission, ITManagerPermission
from .policy_serializers import MonitoringAutomationPolicySerializer


class MonitoringAutomationPolicyViewSet(viewsets.ModelViewSet):
    """ViewSet for MonitoringAutomationPolicy CRUD.

    Supports: list, create, retrieve, partial_update, destroy (governed deactivation).

    Uses existing Monitoring permission conventions.
    Stable ordering: -is_active, name, id
    Collection uses existing project pagination.
    Delete behavior: prefer deactivation over deletion when policy has historical use.
    """

    queryset = MonitoringAutomationPolicy.objects.all().order_by("-is_active", "name", "pk")
    serializer_class = MonitoringAutomationPolicySerializer
    authentication_classes = []
    permission_classes = [SystemAdminPermission]

    def get_permissions(self):
        """Role-based permission control per action.

        - System Admin: full CRUD
        - IT Manager: read-only unless existing governance permits writes
        - IT Support: read-only or denied according to existing policy
        - Employee: denied
        - Inactive user: denied
        - Unknown role: denied
        - Anonymous user: denied
        """
        role = getattr(self.request.user, "role", None)
        user = self.request.user

        # Deny inactive and anonymous users
        if not getattr(user, "is_active", False):
            return [SystemAdminPermission()]

        if not user.is_authenticated:
            return [SystemAdminPermission()]

        if role == "system_admin":
            # Full CRUD for system admins
            return []  # No additional permissions
        elif role == "it_manager":
            # IT Manager: read-only (list, retrieve)
            if self.action in ("list", "retrieve"):
                return []
            # Deny write actions
            return [SystemAdminPermission()]
        elif role == "it_support":
            # IT Support: read-only
            if self.action in ("list", "retrieve"):
                return []
            return [SystemAdminPermission()]  # Denied for writes
        elif role == "employee":
            # Employee: denied entirely
            return [SystemAdminPermission()]
        else:
            # Unknown role: denied
            return [SystemAdminPermission()]

    def destroy(self, request, *args, **kwargs):
        """Governed delete: deactivate instead of hard delete.

        If the policy has historical use (linked alerts/tickets), deactivate it
        instead of deleting. Return a clear response indicating the action taken.
        """
        instance = self.get_object()

        # Check if policy has historical use via linked alerts
        from monitoring.models import MonitoringAlert

        linked_alerts = MonitoringAlert.objects.filter(policy=instance).exists()

        if linked_alerts:
            # Governed deactivation: mark as inactive instead of deleting
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])
            return Response(
                {
                    "detail": "Policy deactivated. It has historical use via linked alerts and "
                    "cannot be permanently deleted to preserve attribution.",
                    "action": "deactivated",
                    "policy_id": instance.pk,
                    "policy_name": instance.name,
                },
                status=status.HTTP_200_OK,
            )
        else:
            # No historical use: perform hard delete
            self.perform_destroy(instance)
            return Response(
                {
                    "detail": "Policy deleted successfully.",
                    "action": "deleted",
                    "policy_id": instance.pk,
                    "policy_name": instance.name,
                },
                status=status.HTTP_200_OK,
            )