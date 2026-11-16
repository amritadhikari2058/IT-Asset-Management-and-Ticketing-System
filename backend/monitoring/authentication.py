"""Custom authentication for monitoring ingestion."""

from rest_framework import authentication
from rest_framework import exceptions
from django.contrib.auth import get_user_model
from django.utils.crypto import constant_time_compare
from .models import MonitoringSource
import hashlib
import hmac
from django.utils import timezone


class MonitoringAuthentication(authentication.BaseAuthentication):
    """Custom authentication for monitoring source ingestion."""

    def authenticate(self, request):
        # Only authenticate ingestion endpoints
        if not request.path.startswith("/api/monitoring/ingest/"):
            return None

        # Get headers
        source_header = request.META.get("HTTP_X_MONITORING_SOURCE")
        timestamp_header = request.META.get("HTTP_X_MONITORING_TIMESTAMP")
        signature_header = request.META.get("HTTP_X_MONITORING_SIGNATURE")

        if not all([source_header, timestamp_header, signature_header]):
            raise exceptions.AuthenticationFailed("Missing required headers")

        # Look up source by code (don't reveal if source exists)
        try:
            source = MonitoringSource.objects.get(code=source_header)
        except MonitoringSource.DoesNotExist:
            # Use a dummy secret comparison to prevent timing attacks
            hmac.compare_digest(signature_header or "", "dummy")
            raise exceptions.AuthenticationFailed("Authentication failed")

        # Check if source is active
        if not source.is_active or source.status != source.Status.ACTIVE:
            raise exceptions.AuthenticationFailed("Authentication failed")

        # Check timestamp tolerance
        try:
            request_time = timezone.datetime.fromisoformat(timestamp_header)
        except (ValueError, AttributeError):
            raise exceptions.AuthenticationFailed("Authentication failed")

        tolerance = source.timestamp_tolerance_seconds or 300
        now = timezone.now()
        if abs((now - request_time).total_seconds()) > tolerance:
            raise exceptions.AuthenticationFailed("Authentication failed")

        # Verify HMAC signature
        body = request.body
        message = timestamp_header + "." + body.decode("utf-8", errors="replace")

        # Try current secret hash
        valid = False
        if source.secret_hash:
            # HMAC-SHA256 verification
            try:
                expected_sig = hmac.new(
                    source.secret_hash.encode(),
                    message.encode(),
                    hashlib.sha256,
                ).hexdigest()
                valid = constant_time_compare(signature_header, expected_sig)
            except Exception:
                pass

        # Try previous secret during grace period
        if not valid and source.previous_secret_hash and source.previous_secret_valid_until:
            try:
                if now <= source.previous_secret_valid_until:
                    expected_sig = hmac.new(
                        source.previous_secret_hash.encode(),
                        message.encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    valid = constant_time_compare(signature_header, expected_sig)
            except Exception:
                pass

        if not valid:
            raise exceptions.AuthenticationFailed("Authentication failed")

        # Return source as the authenticated user
        return (source, None)
