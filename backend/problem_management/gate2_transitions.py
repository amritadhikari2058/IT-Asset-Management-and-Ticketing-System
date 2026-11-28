"""Gate 2 lifecycle transitions: one governed endpoint per service action."""
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .gate2_common import assert_version, guarded
from .gate2_serializers import (
    ProblemActionSerializer, ProblemEvidenceSerializer, ProblemExceptionSerializer,
    ProblemValidationSerializer, ProblemWorkaroundSerializer,
    RootCauseAnalysisSerializer,
)
from .models import (
    ProblemAction, ProblemEvidence, ProblemException, ProblemValidation,
    ProblemWorkaround, RootCauseAnalysis,
)
from .permissions import ProblemManagementPermission

# Action services re-check the version against a freshly locked row. Other
# resources keep the transport-level check below.
SERVICE_VERSIONED_RESOURCE = "actions"

TRANSITIONS = {
    "root-cause-analyses": (RootCauseAnalysis, RootCauseAnalysisSerializer, "analysis", {
        "submit": services.submit_root_cause_analysis,
        "approve": services.approve_root_cause_analysis,
        "reject": services.reject_root_cause_analysis,
        "supersede": services.supersede_root_cause_analysis,
    }),
    "evidence": (ProblemEvidence, ProblemEvidenceSerializer, "evidence", {
        "archive": services.archive_problem_evidence,
    }),
    "actions": (ProblemAction, ProblemActionSerializer, "action", {
        "approve": services.approve_problem_action,
        "start": services.start_problem_action,
        "complete": services.complete_problem_action,
        "validate": services.validate_problem_action,
        "ineffective": services.mark_problem_action_ineffective,
        "cancel": services.cancel_problem_action,
    }),
    "workarounds": (ProblemWorkaround, ProblemWorkaroundSerializer, "workaround", {
        "submit": services.submit_problem_workaround,
        "approve": services.approve_problem_workaround,
        "publish": services.publish_problem_workaround,
        "expire": services.expire_problem_workaround,
        "retire": services.retire_problem_workaround,
    }),
    "validations": (ProblemValidation, ProblemValidationSerializer, "validation", {
        "start": services.start_problem_validation,
        "pass": services.pass_problem_validation,
        "fail": services.fail_problem_validation,
        "inconclusive": services.mark_problem_validation_inconclusive,
        "cancel": services.cancel_problem_validation,
    }),
    "exceptions": (ProblemException, ProblemExceptionSerializer, "exception", {
        "submit": services.submit_problem_exception,
        "approve": services.approve_problem_exception,
        "reject": services.reject_problem_exception,
        "revoke": services.revoke_problem_exception,
        "expire": services.expire_problem_exception,
    }),
}


class TransitionView(APIView):
    permission_classes = [ProblemManagementPermission]
    http_method_names = ["post", "options"]

    def post(self, request, resource, pk, transition):
        entry = TRANSITIONS.get(resource)
        if entry is None:
            raise NotFound("Unknown transition resource.")
        model, serializer_class, kwarg, mapping = entry
        service = mapping.get(transition)
        if service is None:
            raise NotFound("Unknown transition.")
        manager = model.all_objects if resource == "evidence" else model.objects
        obj = manager.filter(pk=pk).first()
        if obj is None:
            raise NotFound("Record not found.")
        # Archived evidence stays addressable so the service can answer 400.
        if getattr(obj, "is_deleted", False) and resource != "evidence":
            raise NotFound("Record not found.")
        # Evidence has no version column; Action services check the token
        # against their locked row instead of this pre-lock object.
        if resource != SERVICE_VERSIONED_RESOURCE:
            assert_version(obj, request.data.get("expected_record_version"), label=resource)
        payload = {}
        if "reason" in request.data:
            payload["reason"] = request.data.get("reason") or ""
        if (resource == SERVICE_VERSIONED_RESOURCE
                and "expected_record_version" in request.data):
            payload["expected_record_version"] = request.data.get(
                "expected_record_version")
        result = guarded(service, actor=request.user, **{kwarg: obj}, **payload)
        return Response(serializer_class(result).data)
