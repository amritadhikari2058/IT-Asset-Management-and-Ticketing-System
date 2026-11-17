"""Custom authentication for monitoring source ingestion."""

from rest_framework import authentication
from rest_framework import exceptions
from django.utils.crypto import constant_time_compare
from django.db import transaction
from .models import MonitoringSource, MonitoringIngestionAttempt
import hashlib
import hmac
from ipaddress import ip_address, ip_network
from django.utils import timezone


class MonitoringAuthentication(authentication.BaseAuthentication):
    """Custom authentication for monitoring source ingestion using raw-body HMAC."""

    def authenticate(self, request):
        if not request.path.startswith("/api/monitoring/ingest/"):
            return None

        source_header = request.META.get("HTTP_X_MONITORING_SOURCE")
        timestamp_header = request.META.get("HTTP_X_MONITORING_TIMESTAMP")
        request_id_header = request.META.get("HTTP_X_MONITORING_REQUEST_ID")
        signature_header = request.META.get("HTTP_X_MONITORING_SIGNATURE")

        if not all([source_header, timestamp_header, request_id_header, signature_header]):
            raise exceptions.AuthenticationFailed("Missing required headers")

        if not request_id_header.strip():
            raise exceptions.AuthenticationFailed("Invalid request ID")

        MAX_REQUEST_ID_LENGTH = 128
        if len(request_id_header) > MAX_REQUEST_ID_LENGTH:
            raise exceptions.AuthenticationFailed("Invalid request ID")

        try:
            source = MonitoringSource.objects.get(code=source_header)
        except MonitoringSource.DoesNotExist:
            hmac.compare_digest(signature_header or "", "0" * 64)
            raise exceptions.AuthenticationFailed("Authentication failed")

        if not source.is_active or source.status != source.Status.ACTIVE:
            raise exceptions.AuthenticationFailed("Authentication failed")

        try:
            timestamp_value = int(timestamp_header)
        except (TypeError, ValueError):
            raise exceptions.AuthenticationFailed("Invalid timestamp")

        tolerance = source.timestamp_tolerance_seconds or 300
        now = timezone.now()
        request_time = timezone.datetime.fromtimestamp(timestamp_value, tz=timezone.utc)

        if abs((now - request_time).total_seconds()) > tolerance:
            raise exceptions.AuthenticationFailed("Invalid timestamp")

        if request_time > now + timezone.timedelta(seconds=tolerance):
            raise exceptions.AuthenticationFailed("Invalid timestamp")

        client_ip = self._get_client_ip(request)
        if not self._validate_ip_allowlist(source, client_ip):
            raise exceptions.AuthenticationFailed("IP address not allowed")

        raw_body = request.body
        canonical = (
            str(timestamp_header).encode("utf-8")
            + b"."
            + request_id_header.encode("utf-8")
            + b"."
            + raw_body
        )

        if not isinstance(signature_header, str) or len(signature_header) != 64:
            raise exceptions.AuthenticationFailed("Invalid signature format")
        try:
            int(signature_header, 16)
        except ValueError:
            raise exceptions.AuthenticationFailed("Invalid signature format")

        valid = False
        if source.secret_hash:
            try:
                expected_sig = hmac.new(
                    source.secret_hash.encode("utf-8"),
                    canonical,
                    hashlib.sha256,
                ).hexdigest()
                valid = constant_time_compare(signature_header, expected_sig)
            except Exception:
                pass

        if not valid and source.previous_secret_hash and source.previous_secret_valid_until:
            if now <= source.previous_secret_valid_until:
                try:
                    expected_sig = hmac.new(
                        source.previous_secret_hash.encode("utf-8"),
                        canonical,
                        hashlib.sha256,
                    ).hexdigest()
                    valid = constant_time_compare(signature_header, expected_sig)
                except Exception:
                    pass

        if not valid:
            raise exceptions.AuthenticationFailed("Authentication failed")

        if not self._check_replay_protection(source, request_id_header):
            raise exceptions.AuthenticationFailed("Replay request rejected")

        request._monitoring_source = source
        request._monitoring_request_id = request_id_header
        request._monitoring_timestamp = timestamp_header

        return (source, None)

    def _get_client_ip(self, request):
        return request.META.get("REMOTE_ADDR", "")

    def _validate_ip_allowlist(self, source, client_ip):
        if not client_ip:
            return False

        networks_str = source.allowed_ip_networks or ""
        if not networks_str.strip():
            return True

        try:
            ip = ip_address(client_ip)
        except ValueError:
            return False

        for cidr in networks_str.split(","):
            cidr = cidr.strip()
            if not cidr:
                continue
            try:
                network = ip_network(cidr, strict=False)
                if ip in network:
                    return True
            except ValueError:
                continue

        return False

    def _check_replay_protection(self, source, request_id):
        if not request_id:
            return False

        if len(request_id) > 128:
            return False

        try:
            with transaction.atomic():
                attempt, created = MonitoringIngestionAttempt.objects.select_for_update().get_or_create(
                    source=source,
                    request_id=request_id,
                    defaults={
                        "remote_address_hash": hashlib.sha256(
                            request_id.encode("utf-8")
                        ).hexdigest(),
                        "authentication_result": MonitoringIngestionAttempt.AuthenticationResult.SUCCESS,
                        "payload_size": 0,
                        "status": MonitoringIngestionAttempt.Status.ACCEPTED,
                    },
                )
                if not created:
                    return False
                return True
        except Exception:
            return False