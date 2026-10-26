from django.urls import path
from rest_framework import routers

from accounts.auth_views import (
    change_password, password_reset_confirm, password_reset_request,
    verification_confirm, verification_request,
)
from accounts.views import DepartmentViewSet, UserViewSet, current_user

router = routers.DefaultRouter()
router.register("departments", DepartmentViewSet, basename="department")
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("me/", current_user, name="current-user"),
    path("change-password/", change_password, name="change-password"),
] + router.urls + [
    path("password-reset/request/", password_reset_request,
         name="password-reset-request"),
    path("password-reset/confirm/", password_reset_confirm,
         name="password-reset-confirm"),
    path("verify-email/request/", verification_request,
         name="verify-email-request"),
    path("verify-email/confirm/", verification_confirm,
         name="verify-email-confirm"),
]
