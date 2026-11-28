"""Views for MonitoringAutomationPolicy CRUD operations."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import MonitoringAutomationPolicy, MonitoringSource
from common.permissions import IsActiveAuthenticated

from .permissions import SystemAdminPermission
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
    permission_classes = [IsActiveAuthenticated, SystemAdminPermission]

    def get_permissions(self):
        """Require active authentication and enforce role/action access."""

        user = self.request.user
        role = getattr(user, "role", None)

        if role == "system_admin":
            return [IsActiveAuthenticated()]

        if role in ("it_manager", "it_support") and self.action in ("list", "retrieve"):
            return [IsActiveAuthenticated()]

        # Employees, unknown roles, and non-admin write actions are denied.
        return [IsActiveAuthenticated(), SystemAdminPermission()]
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