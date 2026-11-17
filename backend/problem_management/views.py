"""PM1 API views (Gate 1).

Status movement only through action endpoints wired to services; ordinary
PATCH cannot touch status/number/counters/milestones/summaries. Scoped
querysets + permission classes enforce the role matrix (§36) before object
retrieval (employee/inactive → 403; no enumeration).
"""
from rest_framework import status as drf_status
from rest_framework.pagination import PageNumberPagination
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import (
    Problem,
    ProblemAssetLink,
    ProblemConfigurationItemLink,
    ProblemHistory,
    ProblemServiceLink,
    ProblemSoftwareProductLink,
    ProblemTask,
    ProblemTicketLink,
)
from .permissions import (
    ProblemManagementPermission,
    can_create_problem,
    is_it_manager,
)
from .serializers import (
    AcceptProblemSerializer,
    CancelProblemSerializer,
    ProblemAssetLinkSerializer,
    ProblemConfigurationItemLinkSerializer,
    ProblemCreateSerializer,
    ProblemDetailSerializer,
    ProblemHistorySerializer,
    ProblemListSerializer,
    ProblemServiceLinkSerializer,
    ProblemSoftwareProductLinkSerializer,
    ProblemTaskSerializer,
    ProblemTicketLinkSerializer,
    ProblemUpdateSerializer,
    ReopenProblemSerializer,
    RejectProblemSerializer,
    StartInvestigationSerializer,
    SubmitProblemSerializer,
)

GOVERNANCE_UPDATE_FIELDS = {
    "owner", "problem_manager", "target_resolution_date", "next_review_at",
}


class ProblemViewSet(viewsets.ModelViewSet):
    permission_classes = [ProblemManagementPermission]
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        # Staff-scoped (all active staff may view operationally); employees
        # and unknown roles never reach here (403 at permission check).
        queryset = Problem.objects.select_related(
            "owner", "problem_manager", "department", "service", "category",
            "created_by",
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("priority"):
            queryset = queryset.filter(priority=params["priority"])
        if params.get("problem_type"):
            queryset = queryset.filter(problem_type=params["problem_type"])
        if params.get("owner"):
            queryset = queryset.filter(owner_id=params["owner"])
        if params.get("service"):
            queryset = queryset.filter(service_id=params["service"])
        if params.get("department"):
            queryset = queryset.filter(department_id=params["department"])
        if params.get("is_open") == "true":
            queryset = queryset.exclude(
                status__in=["closed", "rejected", "cancelled"],
            )
        elif params.get("is_open") == "false":
            queryset = queryset.filter(
                status__in=["closed", "rejected", "cancelled"],
            )
        search = params.get("search")
        if search:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(problem_number__icontains=search) | Q(title__icontains=search),
            )
        ordering = params.get("ordering", "-created_at")
        allowlist = {
            "created_at", "-created_at", "updated_at", "-updated_at",
            "priority", "-priority", "severity", "-severity",
            "target_resolution_date", "-target_resolution_date",
            "next_review_at", "-next_review_at", "recurrence_count",
            "-recurrence_count", "problem_number", "-problem_number",
            "status", "-status",
        }
        return queryset.order_by(ordering if ordering in allowlist else "-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return ProblemCreateSerializer
        if self.action in ("update", "partial_update"):
            return ProblemUpdateSerializer
        if self.action == "list":
            return ProblemListSerializer
        return ProblemDetailSerializer

    def create(self, request, *args, **kwargs):
        if not can_create_problem(request.user):
            return Response(
                {"detail": "Problem creation is limited to IT staff."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        problem = services.create_problem(
            actor=request.user,
            title=serializer.validated_data.get("title", ""),
            description=serializer.validated_data.get("description", ""),
            problem_type=serializer.validated_data.get("problem_type", "reactive"),
            source=serializer.validated_data.get("source", "manual"),
            **{
                k: v for k, v in serializer.validated_data.items()
                if k not in {"title", "description", "problem_type", "source"}
            },
        )
        out = ProblemDetailSerializer(problem, context=self.get_serializer_context())
        return Response(out.data, status=drf_status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if not is_it_manager(request.user):
            for field in GOVERNANCE_UPDATE_FIELDS:
                data.pop(field, None)
        updated = services.update_problem_fields(
            actor=request.user, problem=instance, fields=data,
        )
        out = ProblemDetailSerializer(updated, context=self.get_serializer_context())
        return Response(out.data)

    def perform_destroy(self, instance):
        services.soft_delete_problem(
            actor=self.request.user, problem=instance,
            reason=self.request.query_params.get("reason", ""),
        )

    # --- governed transitions ------------------------------------------- #

    def _act(self, request, service_fn, serializer_cls):
        problem = self.get_object()
        serializer = serializer_cls(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        expected = data.pop("expected_record_version", None)
        updated = service_fn(
            actor=request.user, problem=problem, expected=expected, **data,
        )
        return Response(ProblemDetailSerializer(updated).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._act(request, services.submit_problem, SubmitProblemSerializer)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._act(request, services.accept_problem, AcceptProblemSerializer)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._act(request, services.reject_problem, RejectProblemSerializer)

    @action(detail=True, methods=["post"], url_path="start-investigation")
    def start_investigation(self, request, pk=None):
        return self._act(
            request, services.start_investigation,
            StartInvestigationSerializer,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._act(request, services.cancel_problem, CancelProblemSerializer)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        return self._act(request, services.reopen_problem, ReopenProblemSerializer)

    # --- read actions (Gate 1: history) --------------------------------- #

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        problem = self.get_object()
        events = problem.history_records.select_related("actor", "task")
        page = self.paginate_queryset(events)
        serializer = ProblemHistorySerializer(
            page if page is not None else events, many=True,
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class _LinkViewSet(viewsets.ModelViewSet):
    permission_classes = [ProblemManagementPermission]
    target_field = None
    creator_field = "created_by"
    service_remove = staticmethod(services.remove_link)
    history_detail = "Object link removed."

    def get_queryset(self):
        qs = self.queryset_class.objects.select_related(
            "problem", self.target_field,
        ).filter(is_deleted=False)
        problem_id = self.request.query_params.get("problem")
        if problem_id:
            qs = qs.filter(problem_id=problem_id)
        return qs

    def perform_create(self, serializer):
        link = serializer.save(**{self.creator_field: self.request.user})
        if isinstance(link, ProblemTicketLink):
            services.refresh_problem_counts(link.problem)
            services.record_history(
                link.problem, "ticket_linked", self.request.user,
                detail=f"Ticket #{link.ticket_id} linked as "
                       f"{link.relationship_type} ({link.relevance}).",
                changed_fields=["ticket"],
            )
        else:
            services.record_history(
                link.problem, "linked", self.request.user,
                detail=f"{link._meta.model_name} linked.",
                changed_fields=[self.target_field],
            )

    def perform_update(self, serializer):
        link = serializer.save()
        if isinstance(link, ProblemTicketLink):
            services.refresh_problem_counts(link.problem)

    def perform_destroy(self, instance):
        if isinstance(instance, ProblemTicketLink):
            services.unlink_ticket_link(actor=self.request.user, link=instance)
        else:
            self.service_remove(
                actor=self.request.user, link=instance,
                event_detail=self.history_detail,
            )


class ProblemTicketLinkViewSet(_LinkViewSet):
    queryset_class = ProblemTicketLink
    queryset = ProblemTicketLink.objects.all()
    target_field = "ticket"
    creator_field = "linked_by"
    serializer_class = ProblemTicketLinkSerializer

    def get_queryset(self):
        qs = ProblemTicketLink.objects.select_related(
            "problem", "ticket", "linked_by",
        ).filter(is_deleted=False)
        problem_id = self.request.query_params.get("problem")
        if problem_id:
            qs = qs.filter(problem_id=problem_id)
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs


class ProblemConfigurationItemLinkViewSet(_LinkViewSet):
    queryset_class = ProblemConfigurationItemLink
    queryset = ProblemConfigurationItemLink.objects.all()
    target_field = "configuration_item"
    serializer_class = ProblemConfigurationItemLinkSerializer


class ProblemServiceLinkViewSet(_LinkViewSet):
    queryset_class = ProblemServiceLink
    queryset = ProblemServiceLink.objects.all()
    target_field = "service"
    serializer_class = ProblemServiceLinkSerializer


class ProblemAssetLinkViewSet(_LinkViewSet):
    queryset_class = ProblemAssetLink
    queryset = ProblemAssetLink.objects.all()
    target_field = "asset"
    serializer_class = ProblemAssetLinkSerializer


class ProblemSoftwareProductLinkViewSet(_LinkViewSet):
    queryset_class = ProblemSoftwareProductLink
    queryset = ProblemSoftwareProductLink.objects.all()
    target_field = "software_product"
    serializer_class = ProblemSoftwareProductLinkSerializer


class ProblemTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [ProblemManagementPermission]
    serializer_class = ProblemTaskSerializer
    queryset = ProblemTask.objects.select_related(
        "problem", "assigned_to", "completed_by", "created_by",
    )
    lookup_value_regex = r"\d+"
    pagination_class = PageNumberPagination

    def get_queryset(self):
        qs = super().get_queryset().filter(is_deleted=False)
        problem_id = self.request.query_params.get("problem")
        if problem_id:
            qs = qs.filter(problem_id=problem_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        problem = data.pop("problem")
        task = services.create_problem_task(
            actor=self.request.user, problem=problem,
            **data,
        )
        serializer.instance = task

    def perform_update(self, serializer):
        # Status/sequence/completion fields are read-only in the serializer;
        # ordinary PATCH only updates operational fields.
        serializer.save()

    def perform_destroy(self, instance):
        instance.soft_delete(by_user=self.request.user)
        services.record_history(
            instance.problem, "task_completed", self.request.user,
            task=instance, detail=f"Task #{instance.sequence} removed.",
            changed_fields=["task"],
        )


class ProblemHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [ProblemManagementPermission]
    queryset = ProblemHistory.objects.select_related("actor", "task")
    serializer_class = ProblemHistorySerializer
    lookup_value_regex = r"\d+"
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        problem_id = self.request.query_params.get("problem")
        if problem_id:
            qs = qs.filter(problem_id=problem_id)
        event_type = self.request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)
        return qs
