"""Public auth flows: email verification + password reset (generic responses).

Password-reset request ALWAYS returns the same message whether or not the
address exists, so it never reveals account membership.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from common.throttling import AuthRateThrottle

from accounts import email_utils

GENERIC_RESET_MSG = ("If an account exists for that email, a reset link "
                     "has been sent.")


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def password_reset_request(request):
    email = (request.data.get("email") or "").strip()
    User = get_user_model()
    try:
        user = User.objects.filter(email__iexact=email).first() if email else None
        if user:
            email_utils.send_password_reset_email(user)
    except Exception:
        pass  # generic response + graceful failure either way
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
    user.set_password(pwd)
    user.save(update_fields=["password"])
    return Response({"detail": "Password updated."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verification_request(request):
    email_utils.send_verification_email(request.user)
    return Response({"detail": "Verification email sent."},
                    status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Logged-in password change. Requires the current password and
    validates the new one with Django's configured validators. Never
    logs or audits password values — the audit row carries no details."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    from common.audit import log_action

    user = request.user
    current = request.data.get("current_password", "")
    new = request.data.get("new_password", "")
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
    refresh_token = (request.data.get("refresh") or "").strip()
    if not refresh_token:
        return Response(
            {"detail": "Provide the refresh token."},
            status=status.HTTP_400_BAD_REQUEST)
    try:
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken(refresh_token)
        token.blacklist()
    except Exception:
        # Invalid / already-blacklisted token: still return success so the
        # client can clear localStorage regardless.
        pass
    return Response({"detail": "Logged out."})
