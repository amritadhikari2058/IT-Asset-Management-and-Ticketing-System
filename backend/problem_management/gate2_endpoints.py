"""Gate 2 governed viewsets for list/retrieve/create/edit (services authoritative)."""
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from . import services
from .gate2_common import guarded, problem_or_404
from .gate2_serializers import (
    ProblemActionSerializer, ProblemEvidenceSerializer, ProblemExceptionSerializer,
    ProblemTimelineEventSerializer, ProblemValidationSerializer,
    ProblemWorkaroundSerializer, RootCauseAnalysisSerializer, basename,
)
from .gate2_views import Gate2ModelViewSet
from .models import (
    ProblemAction, ProblemEvidence, ProblemException, ProblemTimelineEvent,
    ProblemValidation, ProblemWorkaround, RootCauseAnalysis,
)


def make_viewset(name, model, serializer_class, create_service, **attrs):
    meta = {
        "model": model,
        "serializer_class": serializer_class,
        "create_service": staticmethod(create_service),
    }
    meta.update(attrs)
    return type(name, (Gate2ModelViewSet,), meta)


RootCauseAnalysisViewSet = make_viewset(
    "RootCauseAnalysisViewSet", RootCauseAnalysis, RootCauseAnalysisSerializer,
    services.create_root_cause_analysis,
    create_map={"analysis_method": "analysis_type"},
    locked_statuses=frozenset({"approved", "rejected", "superseded"}),
)
ActionViewSet = make_viewset(
    "ActionViewSet", ProblemAction, ProblemActionSerializer,
    services.create_problem_action, create_map={"due_at": "due_date"},
    locked_statuses=frozenset({"verified", "closed"}),
)
WorkaroundViewSet = make_viewset(
    "WorkaroundViewSet", ProblemWorkaround, ProblemWorkaroundSerializer,
    services.create_problem_workaround,
    locked_statuses=frozenset({"expired", "retired"}),
)
ValidationViewSet = make_viewset(
    "ValidationViewSet", ProblemValidation, ProblemValidationSerializer,
    services.create_problem_validation,
    locked_statuses=frozenset({"verified", "failed", "cancelled"}),
)
ExceptionViewSet = make_viewset(
    "ExceptionViewSet", ProblemException, ProblemExceptionSerializer,
    services.create_problem_exception,
    locked_statuses=frozenset({"rejected", "revoked", "expired"}),
)


class TimelineViewSet(Gate2ModelViewSet):
    model = ProblemTimelineEvent
    serializer_class = ProblemTimelineEventSerializer
    create_service = staticmethod(services.create_problem_timeline_event)
    http_method_names = ["get", "post", "head", "options"]


class EvidenceViewSet(Gate2ModelViewSet):
    model = ProblemEvidence
    serializer_class = ProblemEvidenceSerializer
    create_service = staticmethod(services.create_problem_evidence)
    http_method_names = ["get", "post", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        evidence = self.get_object()
        guarded(services.archive_problem_evidence, actor=request.user,
                evidence=evidence)
        return Response(status=204)

    def create(self, request, *args, **kwargs):
        problem = problem_or_404(request.data.get("problem"))
        upload = request.FILES.get("file")
        if upload is None:
            raise DRFValidationError({"file": "A file upload is required."})
        title = (request.data.get("title") or "").strip() or basename(upload.name) or "Evidence"
        evidence = guarded(services.create_problem_evidence, actor=request.user,
                           problem=problem, title=title,
                           evidence_type=request.data.get("evidence_type") or "other",
                           description=request.data.get("description") or "",
                           file=upload)
        return Response(ProblemEvidenceSerializer(evidence).data, status=201)
