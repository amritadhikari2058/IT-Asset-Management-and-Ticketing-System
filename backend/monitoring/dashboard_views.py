"""API View for monitoring dashboard aggregates.

Calls the dashboard aggregation service and returns the safe response shape.
Permission scoping: System Admin, IT Manager, IT Support allowed; Employee,
inactive, unknown role, and anonymous users are denied.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .permissions import SystemAdminPermission, ITManagerPermission, ITSupportPermission
from .dashboard_service import get_aggregated_metrics


class DashboardPermission:
    """Combined permission check for dashboard access.

    Allows System Admin, IT Manager, and IT Support roles.
    Denies Employee, inactive, anonymous, and unknown roles.
    """

    def has_permission(self, request, view):
        user = request.user

        # Anonymous users denied
        if not user or not user.is_authenticated:
            return False

        # Inactive users denied
        if not user.is_active:
            return False

        role = getattr(user, "role", None)

        # System Admin allowed
        if role == "system_admin":
            return True

        # IT Manager allowed
        if role == "it_manager":
            return True

        # IT Support allowed
        if role == "it_support":
            return True

        # All other roles (employee, unknown, etc.) denied
        return False


class MonitoringDashboardView(APIView):
    """API View for monitoring dashboard aggregates.

    Calls the dashboard aggregation service and returns the safe response shape.
    Permission scoping applied via DashboardPermission.
    """

    permission_classes = [DashboardPermission]

    def get(self, request):
        """Return dashboard aggregates payload.

        System Admin: allowed
        IT Manager: allowed
        IT Support: allowed when existing policy permits
        Employee: denied
        Inactive user: denied
        Unknown role: denied
        Anonymous user: denied

        Returns 200 with the aggregate payload.
        """
        # Permission check handled by DashboardPermission on the class
        metrics = get_aggregated_metrics()
        return Response(metrics, status=status.HTTP_200_OK)