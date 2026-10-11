"""Email authentication backend that respects is_active (hardening)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email", username)
        if not email or not password:
            return None
        User = get_user_model()
        try:
            user = User.objects.with_deleted().get(email__iexact=email)
        except User.DoesNotExist:
            return None
        if not user.check_password(password):
            return None
        # Block inactive AND soft-deleted users (spec: hardening gap fix).
        if not self.user_can_authenticate(user):
            return None
        if getattr(user, "is_deleted", False):
            return None
        return user
