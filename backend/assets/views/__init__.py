"""Assets views package.

Split from the former monolithic views.py for maintainability. Public viewset
names are re-exported for stable imports.
"""
from .assets import AssetViewSet
from .assignments import AssignmentViewSet, AssetHistoryViewSet
from .attachments import AssetAttachmentViewSet
from .categories import AssetCategoryViewSet
from .disposals import DisposalViewSet
from .knowledge_base import (
    KnowledgeBaseCategoryViewSet,
    KnowledgeBaseConflict,
    KnowledgeBaseFeedbackViewSet,
    KnowledgeBaseTagViewSet,
    KnowledgeBaseViewSet,
)
from .maintenance import MaintenanceViewSet
from .asset_reports import AssetReportViewSet
from .vendors import VendorViewSet

__all__ = [
    "AssetAttachmentViewSet", "AssetCategoryViewSet", "AssetHistoryViewSet",
    "AssetReportViewSet", "AssetViewSet", "AssignmentViewSet", "DisposalViewSet",
    "KnowledgeBaseCategoryViewSet", "KnowledgeBaseConflict",
    "KnowledgeBaseFeedbackViewSet", "KnowledgeBaseTagViewSet",
    "KnowledgeBaseViewSet", "MaintenanceViewSet", "VendorViewSet",
]
