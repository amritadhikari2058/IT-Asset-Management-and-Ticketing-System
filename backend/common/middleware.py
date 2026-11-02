"""Request/response logging middleware.

Logs authentication and permission failures (401/403) without recording
passwords, tokens, or sensitive user data. Intended for production
observability — no secrets are ever written to logs.
"""
import logging

logger = logging.getLogger("common.security")


class SecurityAuditMiddleware:
    """Log 401/403 responses with minimal, non-sensitive context."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        status = getattr(response, "status_code", 0)
        if status in (401, 403):
            user = getattr(request, "user", None)
            user_id = getattr(user, "pk", None) if user and user.is_authenticated else None
            role = getattr(user, "role", None) if user and user.is_authenticated else None
            path = request.path
            method = request.method
            remote = self._client_ip(request)
            logger.warning(
                "auth_failure status=%s method=%s path=%s user_id=%s role=%s client=%s",
                status, method, path, user_id, role, remote,
            )
        return response

    @staticmethod
    def _client_ip(request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")
