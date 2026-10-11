from rest_framework import routers

from assets.views import (
    AssetAttachmentViewSet, AssetCategoryViewSet, AssetHistoryViewSet,
    AssetViewSet, AssignmentViewSet,
)

router = routers.DefaultRouter()
router.register("categories", AssetCategoryViewSet, basename="assetcategory")
router.register("attachments", AssetAttachmentViewSet,
                basename="assetattachment")
router.register("assignments/history", AssignmentViewSet,
                basename="assignment")
router.register("histories", AssetHistoryViewSet, basename="assethistory")
# "" MUST stay last: its detail route would otherwise shadow /histories/.
router.register("", AssetViewSet, basename="asset")

urlpatterns = router.urls
