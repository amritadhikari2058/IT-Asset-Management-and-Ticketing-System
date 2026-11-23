"""Advanced ticket operations viewsets.

Kept separate from tickets/views.py to avoid colliding with concurrent work.
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Department, User
from common.audit import log_action
from common.permissions import IsActiveAuthenticated, IsITStaff, IsSystemAdmin
from tickets.models import (
    Ticket, TicketQueue, TicketQueueMembership, TicketWatcher,
    CannedResponse, TicketTemplate, TicketRelation, TicketResolutionCode,
    TicketSatisfactionSurvey, SavedTicketView, TicketMergeRecord,
)
from tickets.advanced_serializers import (
    TicketQueueSerializer, TicketQueueCreateUpdateSerializer,
    TicketQueueMembershipSerializer, TicketQueueMembershipCreateSerializer,
    TicketWatcherSerializer, TicketWatcherCreateSerializer,
    CannedResponseSerializer, CannedResponseCreateSerializer,
    CannedResponseApplySerializer, TicketTemplateSerializer,
    TicketTemplateCreateSerializer, TicketFromTemplateSerializer,
    TicketRelationSerializer, TicketRelationCreateSerializer,
    TicketChildCreateSerializer, DuplicateCheckSerializer,
    DuplicateSuggestionSerializer, TicketMergeSerializer,
    TicketMergeRecordSerializer, TicketResolutionCodeSerializer,
    ResolveTicketSerializer, CloseTicketSerializer, ReopenTicketSerializer,
    RequestInformationSerializer, SatisfactionSubmitSerializer,
    SavedTicketViewSerializer, SavedTicketViewCreateSerializer,
)
from tickets import queue_services, collaboration_services, template_services
from tickets import merge_services, resolution_services, satisfaction_services
from tickets import metrics_services, duplicate_services


def _is_admin_or_manager(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager")
             or getattr(user, "is_superuser", False))
    )

class TicketQueueViewSet(viewsets.ModelViewSet):
    queryset = TicketQueue.objects.filter(is_deleted=False)
    serializer_class = TicketQueueSerializer
    permission_classes = [IsAuthenticated, IsITStaff]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update",
                           "deactivate", "hard_delete", "auto_assign"):
            from rest_framework.permissions import BasePermission

            class _ManagerPlus(BasePermission):
                def has_permission(self, request, view):
                    user = request.user
                    return bool(
                        user and user.is_authenticated
                        and getattr(user, "is_active", False)
                        and (getattr(user, "role", "") in ("system_admin", "it_manager")
                             or getattr(user, "is_superuser", False))
                    )

            return [IsActiveAuthenticated(), _ManagerPlus()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TicketQueueCreateUpdateSerializer
        return TicketQueueSerializer

    def get_queryset(self):
        user = self.request.user
        qs = TicketQueue.objects.filter(is_deleted=False)
        role = getattr(user, "role", "")
        if not (_is_admin_or_manager(user) or role == "it_support"):
            return qs.none()
        return qs.filter(is_active=True)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from tickets.queue_services import create_queue
        queue = create_queue(serializer.validated_data, request.user)
        headers = self.get_success_headers(TicketQueueSerializer(queue).data)
        return Response(
            TicketQueueSerializer(queue).data,
            status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data,
                                         partial=partial)
        serializer.is_valid(raise_exception=True)
        from tickets.queue_services import update_queue
        queue = update_queue(instance, serializer.validated_data,
                             request.user)
        return Response(TicketQueueSerializer(queue).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        from tickets.queue_services import deactivate_queue
        queue = self.get_object()
        deactivate_queue(queue, request.user)
        return Response({"detail": "Queue deactivated."})

    @action(detail=True, methods=["post"])
    def hard_delete(self, request, pk=None):
        from tickets.queue_services import delete_queue
        queue = self.get_object()
        delete_queue(queue, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="tickets")
    def queue_tickets(self, request, pk=None):
        from tickets.views import _ticket_visible_qs
        from tickets.serializers import TicketSerializer
        queue = self.get_object()
        qs = _ticket_visible_qs(request.user).filter(
            queue=queue, is_deleted=False)
        return Response(TicketSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"])
    def workload(self, request, pk=None):
        from tickets.metrics_services import queue_metrics
        queue = self.get_object()
        filters = {
            "date_from": request.query_params.get("date_from"),
            "date_to": request.query_params.get("date_to"),
        }
        try:
            data = queue_metrics(queue.pk, filters, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(data)

    @action(detail=True, methods=["get"])
    def metrics(self, request, pk=None):
        from tickets.metrics_services import queue_metrics
        queue = self.get_object()
        filters = {
            "date_from": request.query_params.get("date_from"),
            "date_to": request.query_params.get("date_to"),
        }
        try:
            data = queue_metrics(queue.pk, filters, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(data)

    @action(detail=True, methods=["post"], url_path="auto-assign")
    def auto_assign(self, request, pk=None):
        from tickets.queue_services import auto_assign_queue
        queue = self.get_object()
        try:
            assigned = auto_assign_queue(queue, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response({"assigned": assigned})



class TicketQueueMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = TicketQueueMembershipSerializer
    permission_classes = [IsAuthenticated, IsITStaff]

    def get_permissions(self):
        # Queue membership administration is manager/admin-only.
        from rest_framework.permissions import BasePermission

        class _ManagerPlus(BasePermission):
            def has_permission(self, request, view):
                user = request.user
                return bool(
                    user and user.is_authenticated
                    and getattr(user, "is_active", False)
                    and (getattr(user, "role", "") in ("system_admin", "it_manager")
                         or getattr(user, "is_superuser", False))
                )

        return [IsActiveAuthenticated(), _ManagerPlus()]

    def get_queryset(self):
        user = self.request.user
        if not _is_admin_or_manager(user):
            return TicketQueueMembership.objects.none()
        qs = TicketQueueMembership.objects.filter(is_deleted=False)
        queue_id = self.request.query_params.get("queue")
        if queue_id:
            qs = qs.filter(queue_id=queue_id)
        return qs.select_related("user", "queue")

    def get_serializer_class(self):
        if self.action == "create":
            return TicketQueueMembershipCreateSerializer
        return TicketQueueMembershipSerializer

    def create(self, request, *args, **kwargs):
        queue_id = request.data.get("queue") or request.query_params.get("queue")
        if not queue_id:
            return Response({"detail": "queue is required."}, status=400)
        try:
            queue = TicketQueue.objects.get(pk=queue_id, is_deleted=False)
        except TicketQueue.DoesNotExist:
            return Response({"detail": "Queue not found."}, status=404)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from tickets.queue_services import add_membership
        try:
            membership = add_membership(queue, serializer.validated_data, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            return Response({"detail": str(exc)}, status=400)
        return Response(
            TicketQueueMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        from tickets.queue_services import update_membership
        try:
            update_membership(instance, serializer.validated_data, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketQueueMembershipSerializer(instance).data)

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        from tickets.queue_services import remove_membership
        membership = self.get_object()
        try:
            remove_membership(membership, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            return Response({"detail": str(exc)}, status=400)
        return Response({"detail": "Membership removed."})


class CannedResponseViewSet(viewsets.ModelViewSet):
    serializer_class = CannedResponseSerializer
    permission_classes = [IsAuthenticated, IsITStaff]

    def get_queryset(self):
        user = self.request.user
        qs = CannedResponse.objects.filter(is_deleted=False)
        if not _is_admin_or_manager(user):
            qs = qs.filter(is_active=True)
        # IT support sees shared + own
        if getattr(user, "role", "") == "it_support":
            qs = qs.filter(Q(is_shared=True) | Q(owner=user))
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return CannedResponseCreateSerializer
        return CannedResponseSerializer

    def create(self, request, *args, **kwargs):
        from tickets.template_services import create_canned_response
        ser = CannedResponseCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            obj = create_canned_response(ser.validated_data, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(CannedResponseSerializer(obj).data,
                       status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        from tickets.template_services import update_canned_response
        instance = self.get_object()
        ser = CannedResponseCreateSerializer(instance, data=request.data,
                                            partial=True)
        ser.is_valid(raise_exception=True)
        try:
            obj = update_canned_response(instance, ser.validated_data,
                                         request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(CannedResponseSerializer(obj).data)

    def destroy(self, request, *args, **kwargs):
        from tickets.template_services import delete_canned_response
        instance = self.get_object()
        try:
            delete_canned_response(instance, request.user)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TicketTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = TicketTemplateSerializer
    permission_classes = [IsAuthenticated, IsITStaff]

    def get_queryset(self):
        user = self.request.user
        qs = TicketTemplate.objects.filter(is_deleted=False)
        if not _is_admin_or_manager(user):
            qs = qs.filter(is_active=True)
        if getattr(user, "role", "") == "it_support":
            qs = qs.filter(Q(is_shared=True) | Q(owner=user))
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return TicketTemplateCreateSerializer
        return TicketTemplateSerializer

    def create(self, request, *args, **kwargs):
        from tickets.template_services import create_template
        ser = TicketTemplateCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            obj = create_template(ser.validated_data, request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketTemplateSerializer(obj).data,
                       status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        from tickets.template_services import update_template
        instance = self.get_object()
        ser = TicketTemplateCreateSerializer(instance, data=request.data,
                                            partial=kwargs.pop("partial", False))
        ser.is_valid(raise_exception=True)
        try:
            obj = update_template(instance, ser.validated_data, request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketTemplateSerializer(obj).data)

    def destroy(self, request, *args, **kwargs):
        from tickets.template_services import delete_template
        instance = self.get_object()
        try:
            delete_template(instance, request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except Exception as exc:
            if exc.__class__.__name__ == "PermissionDenied":
                return Response({"detail": str(exc)}, status=403)
            if exc.__class__.__name__ in ("ConflictError",):
                return Response({"detail": str(exc)}, status=409)
            return Response({"detail": str(exc)}, status=400)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TicketResolutionCodeViewSet(viewsets.ModelViewSet):
    queryset = TicketResolutionCode.objects.filter(is_deleted=False)
    serializer_class = TicketResolutionCodeSerializer
    permission_classes = [IsAuthenticated, IsITStaff]

    def get_queryset(self):
        user = self.request.user
        qs = TicketResolutionCode.objects.filter(is_deleted=False)
        if not _is_admin_or_manager(user):
            qs = qs.filter(is_active=True)
        return qs

    def create(self, request, *args, **kwargs):
        if not _is_admin_or_manager(request.user):
            return Response({"detail": "Forbidden."}, status=403)
        ser = TicketResolutionCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        obj = ser.save(created_by=request.user)
        return Response(TicketResolutionCodeSerializer(obj).data,
                       status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if not _is_admin_or_manager(request.user):
            return Response({"detail": "Forbidden."}, status=403)
        instance = self.get_object()
        ser = TicketResolutionCodeSerializer(instance, data=request.data,
                                            partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(TicketResolutionCodeSerializer(instance).data)


class SavedTicketViewViewSet(viewsets.ModelViewSet):
    serializer_class = SavedTicketViewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = SavedTicketView.objects.filter(is_deleted=False)
        if _is_admin_or_manager(user):
            return qs
        return qs.filter(Q(owner=user) | Q(is_shared=True))

    def get_serializer_class(self):
        if self.action == "create":
            return SavedTicketViewCreateSerializer
        return SavedTicketViewSerializer

    def _assert_can_modify(self, view):
        """Shared views are readable/duplicable, not writable by others.

        ``is_shared`` is a sharing capability: any authenticated user may
        retrieve and duplicate a shared view, but only the owner (or an admin
        / IT manager, who can already see every view) may change or delete it.
        This mirrors ``set_default``, which is owner-only.
        """
        user = self.request.user
        if _is_admin_or_manager(user) or view.owner_id == user.pk:
            return
        raise PermissionDenied(
            "You can only modify or delete your own saved views.")

    def perform_update(self, serializer):
        view = self.get_object()
        self._assert_can_modify(view)
        obj = serializer.save()
        if obj.is_default:
            SavedTicketView.objects.filter(
                owner=obj.owner, is_deleted=False, is_default=True).exclude(
                pk=obj.pk).update(is_default=False)

    def perform_destroy(self, instance):
        self._assert_can_modify(instance)
        instance.delete()

    def create(self, request, *args, **kwargs):
        ser = SavedTicketViewCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        obj = SavedTicketView.objects.create(
            owner=request.user, **ser.validated_data)
        if obj.is_default:
            SavedTicketView.objects.filter(
                owner=request.user, is_deleted=False, is_default=True).exclude(
                pk=obj.pk).update(is_default=False)
        return Response(SavedTicketViewSerializer(obj).data,
                       status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        view = self.get_object()
        from tickets.views import _ticket_visible_qs
        from tickets.serializers import TicketSerializer

        qs = _ticket_visible_qs(request.user).filter(is_deleted=False)

        allowed_filters = {
            "status", "priority", "category", "department", "queue",
            "assignee", "requester",
        }
        raw_filters = view.filters if isinstance(view.filters, dict) else {}
        for key, val in raw_filters.items():
            if key not in allowed_filters:
                continue
            # Only allow simple scalar IDs/strings; reject operator objects/lists
            # to prevent arbitrary ORM lookups from stored JSON.
            if isinstance(val, bool) or not isinstance(val, (str, int)):
                continue
            if isinstance(val, str) and val == "":
                continue
            try:
                qs = qs.filter(**{key: val})
            except Exception:
                continue

        allowed_ordering = {
            "created_at", "updated_at", "priority", "sla_due_at",
            "resolved_at", "queue", "assignee",
        }
        ordering = view.ordering if isinstance(view.ordering, str) else ""
        order_field = ordering.lstrip("-")
        if order_field not in allowed_ordering:
            ordering = "-created_at"
        try:
            qs = qs.order_by(ordering, "-id")
        except Exception:
            qs = qs.order_by("-created_at", "-id")

        try:
            page = max(1, int(request.query_params.get("page", 1) or 1))
        except Exception:
            page = 1
        try:
            size = min(100, max(1, int(request.query_params.get("page_size", 20) or 20)))
        except Exception:
            size = 20
        start = (page - 1) * size
        end = start + size
        return Response({
            "results": TicketSerializer(qs[start:end], many=True).data,
            "count": qs.count(),
        })

    @action(detail=True, methods=["post"])
    def set_default(self, request, pk=None):
        view = self.get_object()
        if view.owner_id != request.user.pk:
            return Response({"detail": "Forbidden."}, status=403)
        SavedTicketView.objects.filter(
            owner=request.user, is_deleted=False, is_default=True).update(
            is_default=False)
        view.is_default = True
        view.save(update_fields=["is_default", "updated_at"])
        return Response({"detail": "Set as default."})

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        view = self.get_object()
        from tickets.advanced_serializers import SAVED_VIEW_ALLOWED_COLUMNS
        raw_cols = view.columns if isinstance(view.columns, list) else []
        safe_cols = [c for c in raw_cols if isinstance(c, str) and c in SAVED_VIEW_ALLOWED_COLUMNS]
        new_view = SavedTicketView.objects.create(
            owner=request.user, name=f"{view.name} (copy)",
            description=view.description, filters=dict(view.filters or {}),
            ordering=view.ordering, columns=safe_cols,
            is_shared=False, is_default=False)
        return Response(SavedTicketViewSerializer(new_view).data,
                       status=status.HTTP_201_CREATED)


class TicketMergeRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TicketMergeRecord.objects.filter(is_deleted=False)
    serializer_class = TicketMergeRecordSerializer
    permission_classes = [IsAuthenticated, IsITStaff]

    def get_permissions(self):
        # Merge is a manager/admin-only operation (merge_services enforces this).
        # Keep record visibility consistent with that policy.
        if self.action in ("list", "retrieve"):
            from rest_framework.permissions import BasePermission

            class _ManagerPlus(BasePermission):
                def has_permission(self, request, view):
                    user = request.user
                    return bool(
                        user and user.is_authenticated
                        and getattr(user, "is_active", False)
                        and (getattr(user, "role", "") in ("system_admin", "it_manager")
                             or getattr(user, "is_superuser", False))
                    )

            return [IsActiveAuthenticated(), _ManagerPlus()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if not _is_admin_or_manager(user):
            return TicketMergeRecord.objects.none()
        return TicketMergeRecord.objects.filter(is_deleted=False)

