"""Serializers for the Assets and Knowledge Base modules."""
from rest_framework import serializers

from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from tickets.serializers import validate_attachment_file

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
    KnowledgeBaseFeedback,
    Vendor,
)
from common.models import Notification

User = get_user_model()


# ---- Asset serializers (kept from original code) ----

class AssetAssignSerializer(serializers.Serializer):
    """Serializer for asset assignment changes.

    Validates the ``assigned_to`` employee pk (nullable to unassign) and
    optional ``note``. Not a ModelSerializer: the assign view creates the
    ``Assignment`` row directly; this only validates input.
    """
    assigned_to = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, default="", allow_blank=True)


class AssetAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetAttachment
        fields = ["id", "asset", "file", "uploaded_by", "created_at", "is_deleted"]

    def validate_file(self, f):
        return validate_attachment_file(f)


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ["id", "name", "description", "is_active"]


class AssetHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetHistory
        fields = ["id", "asset", "action", "actor", "old_values", "new_values", "timestamp"]


class AssetSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)

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
            "department",
            "vendor",
            "vendor_name",
            "purchase_date",
            "warranty_start",
            "warranty_expiry",
            "purchase_cost",
            "serial_number",
            "created_at",
        ]

    def validate_serial_number(self, value):
        """Trim and check uniqueness of a non-blank serial number.

        Blank serials are always allowed. A non-blank serial may belong to
        exactly one asset, including soft-deleted ones (they keep reserving
        their serial so a recycle-bin restore can never collide).
        """
        value = (value or "").strip()
        if not value:
            return value
        qs = Asset.all_objects.filter(serial_number=value)
        instance = getattr(self, "instance", None)
        if instance is not None:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"Serial number '{value}' is already used by another "
                f"asset. Serial numbers must be unique.")
        return value


class VendorSerializer(serializers.ModelSerializer):
    """Serializer for vendor / supplier records."""

    class Meta:
        model = Vendor
        fields = ["id", "name", "contact_person", "email", "phone",
                  "address", "notes", "is_deleted", "created_at", "updated_at"]
        read_only_fields = ["id", "is_deleted", "created_at", "updated_at"]


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = ["id", "asset", "assigned_to", "assigned_by",
                  "assigned_at", "returned_at", "note"]


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
            "is_completed",
            "created_at",
        ]
        read_only_fields = ["is_completed", "created_at"]


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


class KnowledgeBaseFeedbackSerializer(serializers.ModelSerializer):
    """Serializer for employee KB article feedback (helpful / not helpful)."""

    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = KnowledgeBaseFeedback
        fields = ["id", "article", "user", "user_email", "helpful", "comment",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "user", "user_email", "created_at", "updated_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        article = attrs.get("article")
        if self.instance is None and article:
            # One row per (article, user) — re-submitting replaces the vote.
            if KnowledgeBaseFeedback.objects.filter(
                    article=article, user=user, is_deleted=False).exists():
                raise serializers.ValidationError(
                    {"article": "You already gave feedback on this article. "
                                "Use PATCH to update it instead."})
        return attrs