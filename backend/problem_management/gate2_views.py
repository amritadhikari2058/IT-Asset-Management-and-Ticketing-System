"""Gate 2 base views and read endpoints (transport only, no logic duplication)."""
from django.db import transaction
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, ValidationError as DRFValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .gate2_common import assert_version, guarded, problem_or_404
from .gate2_serializers import (
    ProblemEvidenceSerializer, ProblemTimelineEventSerializer,
    RootCauseAnalysisSerializer, basename,
)
from .models import (
    ProblemAssetLink, ProblemConfigurationItemLink, ProblemEvidence,
    ProblemKbArticleLink, ProblemServiceLink, ProblemSoftwareProductLink,
    ProblemTask, ProblemTimelineEvent, ProblemTicketLink, RootCauseAnalysis,
)
from .permissions import ProblemManagementPermission
from .serializers import (
    ProblemAssetLinkSerializer, ProblemConfigurationItemLinkSerializer,
    ProblemKbArticleLinkSerializer, ProblemServiceLinkSerializer,
    ProblemSoftwareProductLinkSerializer, ProblemTaskSerializer,
    ProblemTicketLinkSerializer,
)


class Gate2ModelViewSet(viewsets.ModelViewSet):
    """List/retrieve/create plus a locked-state, version-checked PATCH."""

    permission_classes = [ProblemManagementPermission]
    lookup_value_regex = r"\d+"
    pagination_class = PageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]
    model = None
    create_service = None
    parent_field = None
    create_map = {}
    locked_statuses = frozenset()
    # Maps field names to the validation message returned when a PATCH tries
    # to change a server-owned/transition-managed field. Viewsets opt in.
    immutable_fields = {}
    protected_fields = {}

    def _reject_protected_patch_fields(self, data):
        errors = {}
        for fields in (self.immutable_fields, self.protected_fields):
            for field, message in fields.items():
                if field in data:
                    errors[field] = message
        if errors:
            raise DRFValidationError(errors)

    def get_queryset(self):
        qs = self.model.objects.filter(is_deleted=False)
        problem_id = self.request.query_params.get("problem")
        if problem_id:
            qs = qs.filter(problem_id=problem_id)
        return qs.order_by(*(self.model._meta.ordering or ["-id"]))

    def _create_kwargs(self, data):
        problem = data.pop("problem", None)
        if self.parent_field:
            parent = data.pop(self.parent_field)
            return {self.parent_field: parent}, data
        if problem is None:
            raise DRFValidationError({"problem": "This field is required."})
        return {"problem": problem}, data

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("expected_record_version", None)
        for source, target in self.create_map.items():
            if source in data:
                data[target] = data.pop(source)
        base_kwargs, data = self._create_kwargs(data)
        obj = guarded(self.create_service, actor=request.user, **base_kwargs, **data)
        return Response(self.get_serializer(obj).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        self._reject_protected_patch_fields(request.data)
        if instance.status in self.locked_statuses:
            raise DRFValidationError(
                {"detail": f"A {instance.status} record can no longer be edited."})
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        expected = serializer.validated_data.pop("expected_record_version", None)
        assert_version(instance, expected)
        serializer.validated_data.pop("status", None)
        guarded(services.validate_record_references,
                problem=instance.problem, data=serializer.validated_data)

        def save_in_transaction():
            with transaction.atomic():
                return serializer.save()

        updated = guarded(save_in_transaction)
        return Response(self.get_serializer(updated).data)


class ProblemCollectionView(APIView):
    permission_classes = [ProblemManagementPermission]
    model = None
    serializer_class = None
    ordering = None

    def rows(self, problem):
        return self.model.objects.filter(problem=problem, is_deleted=False).order_by(
            *(self.ordering or self.model._meta.ordering or ["-id"]))

    def get(self, request, problem_id):
        problem = problem_or_404(problem_id)
        return Response(self.serializer_class(self.rows(problem), many=True).data)


class EvidenceCollection(ProblemCollectionView):
    model = ProblemEvidence
    serializer_class = ProblemEvidenceSerializer

    def post(self, request, problem_id):
        problem = problem_or_404(problem_id)
        upload = request.FILES.get("file")
        if upload is None:
            raise DRFValidationError({"file": "A file upload is required."})
        title = (request.data.get("title") or "").strip() or basename(upload.name) or "Evidence"
        evidence = guarded(
            services.create_problem_evidence, actor=request.user, problem=problem,
            title=title, evidence_type=request.data.get("evidence_type") or "other",
            description=request.data.get("description") or "", file=upload)
        return Response(ProblemEvidenceSerializer(evidence).data, status=201)


class TimelineCollection(ProblemCollectionView):
    model = ProblemTimelineEvent
    serializer_class = ProblemTimelineEventSerializer

    def post(self, request, problem_id):
        problem = problem_or_404(problem_id)
        serializer = ProblemTimelineEventSerializer(
            data={**request.data, "problem": problem.pk})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("problem", None)
        event = guarded(services.create_problem_timeline_event,
                        actor=request.user, problem=problem, **data)
        return Response(ProblemTimelineEventSerializer(event).data, status=201)


class ProblemTaskCollection(ProblemCollectionView):
    model = ProblemTask
    serializer_class = ProblemTaskSerializer


class ProblemRootCauseAnalysisView(APIView):
    permission_classes = [ProblemManagementPermission]

    def get(self, request, problem_id):
        problem = problem_or_404(problem_id)
        analysis = RootCauseAnalysis.objects.filter(
            problem=problem, is_deleted=False).order_by("-created_at", "-id").first()
        if analysis is None:
            raise NotFound("No root-cause analysis for this problem.")
        return Response(RootCauseAnalysisSerializer(analysis).data)


class ProblemReadinessView(APIView):
    permission_classes = [ProblemManagementPermission]

    def get(self, request, problem_id):
        problem = problem_or_404(problem_id)
        # Read-only by contract: no history, audit or notification side effects.
        return Response(services.evaluate_problem_readiness(problem))


class LinkedTicketsView(ProblemCollectionView):
    model = ProblemTicketLink
    serializer_class = ProblemTicketLinkSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_related(
            "problem", "ticket", "ticket__category", "linked_by",
        ).order_by("-linked_at", "-id")


class LinkedCIsView(ProblemCollectionView):
    model = ProblemConfigurationItemLink
    serializer_class = ProblemConfigurationItemLinkSerializer


class LinkedAssetsView(ProblemCollectionView):
    model = ProblemAssetLink
    serializer_class = ProblemAssetLinkSerializer


class LinkedServicesView(ProblemCollectionView):
    model = ProblemServiceLink
    serializer_class = ProblemServiceLinkSerializer


class LinkedProductsView(ProblemCollectionView):
    model = ProblemSoftwareProductLink
    serializer_class = ProblemSoftwareProductLinkSerializer


class LinkedKBsView(ProblemCollectionView):
    model = ProblemKbArticleLink
    serializer_class = ProblemKbArticleLinkSerializer
