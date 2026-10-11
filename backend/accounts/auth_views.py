"""Public auth flows: email verification + password reset (generic responses).

Password-reset request ALWAYS returns the same message whether or not the
address exists, so it never reveals account membership.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts import email_utils

GENERIC_RESET_MSG = ("If an account exists for that email, a reset link "
                     "has been sent.")


@api_view(["POST"])
@permission_classes([AllowAny])
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


@api_view(["GET"])
@permission_classes([AllowAny])
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
