from django.urls import path
from .views import ApprovalCenterViewSet

approval_center_view = ApprovalCenterViewSet.as_view({
    "get": "list",
})

approval_counts_view = ApprovalCenterViewSet.as_view({
    "get": "counts",
})

approval_detail_view = ApprovalCenterViewSet.as_view({
    "get": "retrieve",
})

urlpatterns = [
    path("", approval_center_view, name="approval-center"),
    path("counts/", approval_counts_view, name="approval-center-counts"),
    path("<str:approval_type>/<str:object_id>/",
         approval_detail_view, name="approval-center-detail"),
]
