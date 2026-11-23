"""Public auth flows: email verification + password reset + password change.

Password-reset request ALWAYS returns the same message whether or not the
address exists, so it never reveals account membership. Reset, verification
confirmation, and password-change endpoints are account-scoped: they use a
short per-account cooldown so a single account cannot be spammed even when
the caller rotates IP addresses or anonymous identities.

All auth-side-effect calls are best-effort: if email delivery fails, the
caller still gets the correct generic response and account state is not left
partially mutated.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from common.throttling import AuthRateThrottle, account_action_cooldown

from accounts import email_utils

GENERIC_RESET_MSG = ("If an account exists for that email, a reset link "
                     "has been sent.")

# Per-account cooldown windows (seconds). Short enough to stop automation,
# short enough that a legitimate user who mis-clicks a reset link a few times
# is not locked out for long.
_PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS = 60
_PASSWORD_RESET_CONFIRM_COOLDOWN_SECONDS = 60
_VERIFICATION_REQUEST_COOLDOWN_SECONDS = 60
_CHANGE_PASSWORD_COOLDOWN_SECONDS = 60


def _reset_cooldown_key(email):
    return f"password_reset:{email.lower().strip()}"


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def password_reset_request(request):
    email = (request.data.get("email") or "").strip()
    User = get_user_model()

    # Account-scoped cooldown: one reset-email per address per window.
    # Checked BEFORE any side effects so response timing is identical for
    # existing and non-existing addresses inside the cooldown.
    if account_action_cooldown(
        _reset_cooldown_key(email), _PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS
    ):
        return Response({"detail": GENERIC_RESET_MSG})

    try:
        user = User.objects.filter(email__iexact=email).first() if email else None
        if user:
            email_utils.send_password_reset_email(user)
    except Exception:
        # Email delivery failing must not reveal whether the address exists.
        pass
    return Response({"detail": GENERIC_RESET_MSG})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def password_reset_confirm(request):
    uid, token, pwd = (request.data.get("uid"), request.data.get("token"),
                       request.data.get("new_password", ""))
    User = get_user_model()
    if not uid or not token or len(pwd) < 8:
        return Response({"detail": "Invalid request."}, status=400)

    pk = email_utils.decode_uid(uid)
    user = User.objects.filter(pk=pk).first() if pk else None
    if not user or not email_utils.check_token(user, token):
        return Response({"detail": "Invalid or expired link."}, status=400)

    # One successful reset per cooldown: prevents automated token-reuse
    # attempts on a freshly reset account.
    if account_action_cooldown(
        _reset_cooldown_key(user.email),
        _PASSWORD_RESET_CONFIRM_COOLDOWN_SECONDS,
    ):
        return Response({"detail": "Invalid or expired link."}, status=400)

    user.set_password(pwd)
    user.save(update_fields=["password"])
    return Response({"detail": "Password updated."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthRateThrottle])
def verification_request(request):
    # One verification email per account per window: stops an attacker with a
    # compromised session from flooding the victim's inbox.
    if account_action_cooldown(
        f"verification:{request.user.pk}",
        _VERIFICATION_REQUEST_COOLDOWN_SECONDS,
    ):
        return Response({"detail": "A verification email was recently sent."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    email_utils.send_verification_email(request.user)
    return Response({"detail": "Verification email sent."},
                    status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthRateThrottle])
def change_password(request):
    """Logged-in password change. Requires the current password and
    validates the new one with Django's configured validators. Never
    logs or audits password values — the audit row carries no details.
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    from common.audit import log_action

    user = request.user
    current = request.data.get("current_password", "")
    new = request.data.get("new_password", "")

    # Rate-limit password-change attempts per account (not just per session),
    # so a stolen session cannot brute-force the current password.
    if account_action_cooldown(
        f"change_password:{user.pk}",
        _CHANGE_PASSWORD_COOLDOWN_SECONDS,
    ):
        return Response({"detail": "Too many password-change attempts."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)

    if not current or not user.check_password(current):
        return Response({"detail": "Current password is incorrect."},
                        status=400)
    try:
        validate_password(new, user)
    except DjangoValidationError as exc:
        return Response({"new_password": list(exc.messages)}, status=400)
    user.set_password(new)
    user.save(update_fields=["password"])
    log_action(actor=user, action="update", instance=user)
    return Response({"detail": "Password updated."})


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def verification_confirm(request):
    uid, token = request.query_params.get("uid"), request.query_params.get("token")
    User = get_user_model()
    pk = email_utils.decode_uid(uid) if uid else None
    user = User.objects.filter(pk=pk).first() if pk else None
    if not user or not token or not email_utils.check_token(user, token):
        return Response({"detail": "Invalid or expired link."}, status=400)
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    return Response({"detail": "Email verified."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthRateThrottle])
def logout(request):
    """Invalidate the caller's refresh token so existing sessions can no
    longer refresh access tokens.

    The refresh token is read from the request body (``refresh``). It is
    blacklisted via rest_framework_simplejwt.token_blacklist so it can
    never be used again. Access tokens are short-lived and expire on their
    own; clients should also clear localStorage on logout.
    """
    # Prefer the body refresh (legacy), but also accept the refresh token
    # from the ``JWT_REFRESH_COOKIE_NAME`` cookie when the body omits it
    # (cookie-based client). In cookie mode the frontend cannot read or
    # delete the httpOnly token itself, so the backend is the only place that
    # can invalidate it.
    from django.conf import settings as django_settings
    refresh_token = (request.data.get("refresh") or "").strip()
    if not refresh_token:
        refresh_token = (request.COOKIES.get(
            getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "") or "").strip()
        )
    if not refresh_token:
        return Response(
            {"detail": "Provide the refresh token (body or cookie)."},
            status=status.HTTP_400_BAD_REQUEST)
    try:
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken(refresh_token)
        token.blacklist()
    except Exception:
        # Invalid / already-blacklisted token: still return success so the
        # client can clear its session regardless.
        pass
    # In cookie mode, clear the refresh cookie so the browser drops it.
    if getattr(django_settings, "JWT_REFRESH_COOKIE_ENABLED", False):
        response = Response({"detail": "Logged out."})
        response.delete_cookie(
            getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", ""),
            path="/",
        )
        return response
    return Response({"detail": "Logged out."})
