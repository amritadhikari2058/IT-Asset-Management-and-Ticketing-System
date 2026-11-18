"""Gate 2 API serializers.

Server-owned fields (status, version, actors, timestamps, workflow outputs)
are read-only. Mutations accept business inputs plus the write-only
``expected_record_version`` token. Evidence never serializes its storage path.
"""
from django.utils import timezone
from rest_framework import serializers

from .models import (
    ProblemAction, ProblemEvidence, ProblemException, ProblemTimelineEvent,
    ProblemValidation, ProblemWorkaround, RootCauseAnalysis, RootCauseFactor,
    RootCauseWhy,
)


def basename(path):
    return (path or "").replace("\\", "/").split("/")[-1]


class ExpectedVersionMixin(serializers.Serializer):
    """Adds a write-only optimistic-concurrency token to a serializer."""

    def get_fields(self):
        fields = super().get_fields()
        fields["expected_record_version"] = serializers.IntegerField(
            required=False, write_only=True, min_value=1,
        )
        return fields


class VersionedModelSerializer(ExpectedVersionMixin, serializers.ModelSerializer):
    """Business-input serializer: workflow fields stay server-controlled."""


def model_serializer(model, fields, read_only, declared=None):
    attrs = {
        "Meta": type("Meta", (), {
            "model": model, "fields": fields, "read_only_fields": read_only,
        }),
    }
    attrs.update(declared or {})
    return type(f"{model.__name__}Serializer", (VersionedModelSerializer,), attrs)


def _future_only(value):
    if value is not None and value <= timezone.now():
        raise serializers.ValidationError("expires_at must be in the future.")
    return value


RootCauseAnalysisSerializer = model_serializer(
    RootCauseAnalysis,
    ["id", "problem", "title", "description", "analysis_method", "findings",
     "concluded_at", "status", "version", "approved_by", "approved_by_username",
     "approved_at", "rejection_reason", "created_by", "created_by_username",
     "created_at"],
    ["id", "status", "version", "approved_by", "approved_at", "rejection_reason",
     "created_by", "created_at"],
    {
        "approved_by_username": serializers.CharField(
            source="approved_by.username", read_only=True),
        "created_by_username": serializers.CharField(
            source="created_by.username", read_only=True),
    },
)

RootCauseWhySerializer = model_serializer(
    RootCauseWhy,
    ["id", "analysis", "question_number", "question_text", "answer",
     "answered_by", "answered_by_username", "answered_at"],
    ["id", "answered_by", "answered_at"],
    {
        "question_number": serializers.IntegerField(min_value=1),
        "answered_by_username": serializers.CharField(
            source="answered_by.username", read_only=True),
    },
)

RootCauseFactorSerializer = model_serializer(
    RootCauseFactor,
    ["id", "analysis", "category", "factor", "contribution",
     "identified_by", "identified_by_username", "identified_at"],
    ["id", "identified_by", "identified_at"],
    {
        "identified_by_username": serializers.CharField(
            source="identified_by.username", read_only=True),
    },
)

ProblemTimelineEventSerializer = model_serializer(
    ProblemTimelineEvent,
    ["id", "problem", "event_type", "title", "description", "occurred_at",
     "source", "recorded_by", "recorded_by_username", "recorded_at"],
    ["id", "recorded_by", "recorded_at"],
    {
        "recorded_by_username": serializers.CharField(
            source="recorded_by.username", read_only=True),
    },
)

ProblemActionSerializer = model_serializer(
    ProblemAction,
    ["id", "problem", "title", "description", "action_type", "status",
     "version", "assigned_to", "assigned_to_username", "due_at",
     "completed_at", "root_cause_analysis", "validation_status",
     "verified_by", "verified_by_username", "verified_at",
     "created_by", "created_at"],
    ["id", "status", "version", "completed_at", "validation_status",
     "verified_by", "verified_at", "created_by", "created_at"],
    {
        "assigned_to_username": serializers.CharField(
            source="assigned_to.username", read_only=True),
        "verified_by_username": serializers.CharField(
            source="verified_by.username", read_only=True),
    },
)

ProblemWorkaroundSerializer = model_serializer(
    ProblemWorkaround,
    ["id", "problem", "title", "description", "workaround_type", "steps",
     "effectiveness_rating", "implemented_at", "resolved_at",
     "implemented_by", "implemented_by_username", "status", "version",
     "created_by", "created_by_username", "created_at"],
    ["id", "implemented_by", "status", "version", "created_by", "created_at"],
    {
        "effectiveness_rating": serializers.IntegerField(
            min_value=1, max_value=5, required=False),
        "implemented_by_username": serializers.CharField(
            source="implemented_by.username", read_only=True),
        "created_by_username": serializers.CharField(
            source="created_by.username", read_only=True),
    },
)

ProblemValidationSerializer = model_serializer(
    ProblemValidation,
    ["id", "problem", "title", "description", "validation_type",
     "test_plan", "test_results", "passed", "validated_by",
     "validated_by_username", "validated_at", "status", "version",
     "notes", "created_by", "created_at"],
    ["id", "passed", "validated_by", "validated_at", "status", "version",
     "created_by", "created_at"],
    {
        "validated_by_username": serializers.CharField(
            source="validated_by.username", read_only=True),
    },
)

ProblemExceptionSerializer = model_serializer(
    ProblemException,
    ["id", "problem", "title", "description", "exception_type", "reason",
     "conditions", "expires_at", "granted_at", "granted_by", "approved_by",
     "approved_by_username", "approved_at", "status", "version",
     "created_by", "created_by_username", "created_at"],
    ["id", "granted_at", "granted_by", "approved_by", "approved_at",
     "status", "version", "created_by", "created_at"],
    {
        "approved_by_username": serializers.CharField(
            source="approved_by.username", read_only=True),
        "created_by_username": serializers.CharField(
            source="created_by.username", read_only=True),
        "validate_expires_at": staticmethod(_future_only),
    },
)


class ProblemEvidenceSerializer(serializers.ModelSerializer):
    """Metadata only: never the storage path or file contents."""

    original_filename = serializers.SerializerMethodField()
    file_type = serializers.CharField(source="content_type", read_only=True)
    file_size = serializers.IntegerField(source="size", read_only=True)
    uploaded_at = serializers.DateTimeField(source="created_at", read_only=True)
    archived = serializers.BooleanField(source="is_deleted", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True)

    class Meta:
        model = ProblemEvidence
        fields = ["id", "problem", "title", "description", "evidence_type", "source",
                  "checksum", "content_type", "file_type", "size", "file_size",
                  "original_filename", "uploaded_at", "archived", "created_by",
                  "created_by_username", "created_at"]
        read_only_fields = fields

    def get_original_filename(self, obj):
        return basename(getattr(obj.file, "name", ""))
