"""Source write view mixins for monitoring module.

Provides MonitoringSourceCreateMixin and MonitoringSourceUpdateMixin so the
existing MonitoringSourceViewSet can gain create and partial_update support
without duplicating the complete ViewSet. The integration owner imports these
mixins and wires them into the existing ViewSet plus URL router.
"""

from rest_framework import status
from rest_framework.response import Response

from .source_serializers import MonitoringSourceWriteSerializer


class MonitoringSourceCreateMixin:
    """Mixin to add create (POST) support to MonitoringSourceViewSet.

    Returns the generated plaintext secret exactly once in the create
    response. The secret is never returned from list, retrieve, or update.
    """

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        response_data = serializer.data
        plaintext = getattr(instance, "_plaintext_secret", None)
        if plaintext:
            response_data["secret"] = plaintext
        return Response(response_data, status=status.HTTP_201_CREATED)


class MonitoringSourceUpdateMixin:
    """Mixin to add partial_update (PATCH) support to MonitoringSourceViewSet.

    Only safe mutable metadata may be updated. Server-controlled fields
    (secret, is_active, health, timestamps) are rejected by the serializer.
    Activation/deactivation continue through the dedicated enable/disable
    actions; rotation through rotate-secret.
    """

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
