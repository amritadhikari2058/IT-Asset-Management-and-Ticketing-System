from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import (
    TokenObtainPairView, TokenRefreshView,
)

from common.views import (
    recycle_bin_detail, recycle_bin_hard_delete, recycle_bin_list,
    recycle_bin_restore,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain"),
    path("api/token/refresh/", TokenRefreshView.as_view(),
         name="token_refresh"),
    path("api/accounts/", include("accounts.urls")),
    path("api/assets/", include("assets.urls")),
    path("api/tickets/", include("tickets.urls")),
    path("api/common/", include("common.urls")),
    path("api/recycle-bin/", recycle_bin_list, name="recycle-bin-list"),
    path("api/recycle-bin/<str:entity_type>/<str:pk>/",
         recycle_bin_detail, name="recycle-bin-detail"),
    path("api/recycle-bin/<str:entity_type>/<str:pk>/restore/",
         recycle_bin_restore, name="recycle-bin-restore"),
    path("api/recycle-bin/<str:entity_type>/<str:pk>/permanent/",
         recycle_bin_hard_delete, name="recycle-bin-hard-delete"),
]
