"""Serializers for the Assets and Knowledge Base modules."""
from rest_framework import serializers

from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from assets.models import (
    Asset,
    AssetAssignment,
    AssetAttachment,
    AssetCategory,
    AssetHistory,
    Assignment,
    Disposal,
    Maintenance,
    MaintenanceReminder,
    KnowledgeBaseArticle,
    KnowledgeBaseCategory,
    KnowledgeBaseTag,
)
from common.models import Notification

User = get_user_model()


# ---- Asset serializers (kept from original code) ----

class AssetAssignSerializer(serializers.ModelSerializer):
    """Serializer for asset assignment changes."""

    class Meta:
        model = AssetAssignment
        fields = ["asset", "employee", "assigned_by", "note", "effective_from"]


class AssetAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetAttachment
        fields = ["id", "asset", "file", "uploaded_by", "uploaded_at", "is_deleted"]


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ["id", "name", "code", "description", "is_active"]


class AssetHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetHistory
        fields = ["id", "asset", "action", "actor", "old_values", "new_values", "timestamp"]


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = [
            "id",
            "asset_tag",
            "name",
            "description",
            "category",
            "status",
            "location",
            "purchase_date",
            "cost",
            "created_at",
        ]


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = ["id", "asset", "employee", "assigned_by", "assigned_at", "status"]


class DisposalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Disposal
        fields = [
            "id",
            "asset",
            "approval_status",
            "disposal_date",
            "disposal_method",
            "disposal_value",
            "disposal_reason",
            "completed",
            "created_at",
        ]


class MaintenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Maintenance
        fields = [
            "id",
            "asset",
            "title",
            "maintenance_type",
            "status",
            "scheduled_date",
            "start_date",
            "completion_date",
            "assigned_to",
            "vendor",
            "cost",
            "resolution_notes",
        ]


# ---- Knowledge Base serializers ----

class KnowledgeBaseTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBaseTag
        fields = ["id", "name", "slug"]


class KnowledgeBaseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBaseCategory
        fields = ["id", "name", "code", "description", "is_published"]


class KnowledgeBaseArticleSerializer(serializers.ModelSerializer):
    tags = KnowledgeBaseTagSerializer(many=True, read_only=True)
    category = KnowledgeBaseCategorySerializer(read_only=True)
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)

    class Meta:
        model = KnowledgeBaseArticle
        fields = [
            "id",
            "title",
            "slug",
            "category",
            "tags",
            "author_name",
            "status",
            "view_count",
            "created_at",
            "updated_at",
        ]


class KnowledgeBaseArticleCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating articles (includes tag/category IDs)."""

    tags = serializers.SlugRelatedField(
        many=True, slug_field="slug", queryset=KnowledgeBaseTag.objects.all(), required=False
    )
    category = serializers.SlugRelatedField(
        slug_field="code", queryset=KnowledgeBaseCategory.objects.all(), required=False
    )

    class Meta:
        model = KnowledgeBaseArticle
        fields = [
            "title",
            "slug",
            "category",
            "tags",
            "content",
            "status",
        ]


class KnowledgeBaseCategoryCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBaseCategory
        fields = ["name", "code", "description", "is_published"]


class KnowledgeBaseTagCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBaseTag
        fields = ["name", "slug"]