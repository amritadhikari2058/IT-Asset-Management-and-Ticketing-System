"""Gate 2 nested write collections (create under one Problem)."""
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from . import services
from .gate2_common import guarded, problem_or_404
from .gate2_serializers import (
    ProblemActionSerializer, ProblemExceptionSerializer, ProblemValidationSerializer,
    ProblemWorkaroundSerializer, RootCauseFactorSerializer, RootCauseWhySerializer,
)
from .gate2_views import ProblemCollectionView
from .models import (
    ProblemAction, ProblemException, ProblemValidation, ProblemWorkaround,
    RootCauseFactor, RootCauseWhy,
)


class WriteCollection(ProblemCollectionView):
    create_service = None
    create_map = {}

    def post(self, request, problem_id):
        problem = problem_or_404(problem_id)
        serializer = self.serializer_class(
            data={**request.data, "problem": problem.pk})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("expected_record_version", None)
        for source, target in self.create_map.items():
            if source in data:
                data[target] = data.pop(source)
        data.pop("problem", None)
        obj = guarded(self.create_service, actor=request.user,
                      problem=problem, **data)
        return Response(self.serializer_class(obj).data, status=201)


class WhyCollection(WriteCollection):
    model = RootCauseWhy
    serializer_class = RootCauseWhySerializer
    ordering = ["question_number"]

    def rows(self, problem):
        return RootCauseWhy.objects.filter(
            analysis__problem=problem, is_deleted=False).order_by("question_number")

    def post(self, request, problem_id):
        problem_or_404(problem_id)
        serializer = RootCauseWhySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("expected_record_version", None)
        analysis = data.pop("analysis")
        if analysis.problem_id != int(problem_id):
            raise DRFValidationError({"analysis": "RCA belongs to a different problem."})
        why = guarded(services.create_root_cause_why, actor=request.user,
                      analysis=analysis, **data)
        return Response(RootCauseWhySerializer(why).data, status=201)


class FactorCollection(WriteCollection):
    model = RootCauseFactor
    serializer_class = RootCauseFactorSerializer

    def rows(self, problem):
        return RootCauseFactor.objects.filter(
            analysis__problem=problem, is_deleted=False).order_by("factor")

    def post(self, request, problem_id):
        problem_or_404(problem_id)
        serializer = RootCauseFactorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("expected_record_version", None)
        analysis = data.pop("analysis")
        if analysis.problem_id != int(problem_id):
            raise DRFValidationError({"analysis": "RCA belongs to a different problem."})
        factor = guarded(services.create_root_cause_factor, actor=request.user,
                         analysis=analysis, **data)
        return Response(RootCauseFactorSerializer(factor).data, status=201)


class ActionCollection(WriteCollection):
    model = ProblemAction
    serializer_class = ProblemActionSerializer
    create_service = staticmethod(services.create_problem_action)
    create_map = {"due_at": "due_date"}


class WorkaroundCollection(WriteCollection):
    model = ProblemWorkaround
    serializer_class = ProblemWorkaroundSerializer
    create_service = staticmethod(services.create_problem_workaround)


class ValidationCollection(WriteCollection):
    model = ProblemValidation
    serializer_class = ProblemValidationSerializer
    create_service = staticmethod(services.create_problem_validation)


class ExceptionCollection(WriteCollection):
    model = ProblemException
    serializer_class = ProblemExceptionSerializer
    create_service = staticmethod(services.create_problem_exception)

    def post(self, request, problem_id):
        problem = problem_or_404(problem_id)
        serializer = self.serializer_class(
            data={**request.data, "problem": problem.pk})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("expected_record_version", None)
        data.pop("problem", None)
        detail = {key: data.pop(key) for key in ("expires_at", "reason", "conditions")
                  if key in data}
        exception = guarded(services.create_problem_exception, actor=request.user,
                            problem=problem, **data)
        if detail:
            for key, value in detail.items():
                setattr(exception, key, value)
            exception.save(update_fields=list(detail))
        return Response(ProblemExceptionSerializer(exception).data, status=201)
