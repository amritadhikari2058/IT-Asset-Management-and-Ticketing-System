"""Shared Gate 2 API helpers: payload tokens, lookups, error translation."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import NotFound, ValidationError as DRFValidationError

from . import services
from .models import Problem


class VersionTokenSerializer(drf_serializers.Serializer):
    """Write-only optimistic-concurrency token accepted by every mutation."""

    expected_record_version = drf_serializers.IntegerField(
        required=False, write_only=True, min_value=1)


class ReasonSerializer(VersionTokenSerializer):
    reason = drf_serializers.CharField(required=False, allow_blank=True)


class RejectSerializer(VersionTokenSerializer):
    reason = drf_serializers.CharField(required=True, allow_blank=False)


def problem_or_404(pk):
    problem = Problem.objects.filter(pk=pk, is_deleted=False).first()
    if problem is None:
        raise NotFound("Problem not found.")
    return problem


def assert_version(instance, expected, label="record"):
    """409 when the caller's version is not the current server version."""
    if expected is None or not hasattr(instance, "version"):
        return
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise DRFValidationError({"expected_record_version": "Must be an integer."})
    current = instance.version
    if expected != current:
        raise services.StaleRecordError(
            f"Stale {label} version: sent {expected}, current is {current}.")


def guarded(fn, *args, **kwargs):
    """Translate model/database failures into safe 400 responses."""
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise DRFValidationError(getattr(exc, "message_dict", {"detail": str(exc)}))
    except IntegrityError:
        raise DRFValidationError({"detail": "The request conflicts with existing data."})
