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
    KnowledgeBaseArticleRevision,
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
    category_name = serializers.CharField(
        source="category.name", read_only=True, default=None)
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.get_full_name", read_only=True, default=None)

    class Meta:
        model = KnowledgeBaseArticle
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "content",
            "category",
            "category_name",
            "tags",
            "author",
            "author_name",
            "status",
            "version",
            "revision_number",
            "submitted_at",
            "reviewed_by",
            "reviewed_by_name",
            "reviewed_at",
            "review_decision",
            "review_comment",
            "view_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class KnowledgeBaseArticleCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating articles (includes tag/category IDs).

    ``version`` is the client's optimistic-concurrency token and
    ``change_note`` is stored on the resulting revision; both are handled by
    the view and never written directly to the article row.
    """

    tags = serializers.SlugRelatedField(
        many=True, slug_field="slug", queryset=KnowledgeBaseTag.objects.all(), required=False
    )
    category = serializers.SlugRelatedField(
        slug_field="code", queryset=KnowledgeBaseCategory.objects.all(),
        required=False, allow_null=True,
    )
    version = serializers.IntegerField(
        required=False, min_value=1, write_only=True)
    change_note = serializers.CharField(
        required=False, allow_blank=True, max_length=500, write_only=True)

    class Meta:
        model = KnowledgeBaseArticle
        fields = [
            "title",
            "slug",
            "summary",
            "category",
            "tags",
            "content",
            "status",
            "version",
            "change_note",
        ]

    def _strip_write_only(self, validated_data):
        validated_data.pop("version", None)
        validated_data.pop("change_note", None)
        return validated_data

    def create(self, validated_data):
        return super().create(self._strip_write_only(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._strip_write_only(validated_data))


class KnowledgeBaseArticleRevisionSerializer(serializers.ModelSerializer):
    """Read-only immutable revision snapshot."""

    editor_name = serializers.CharField(read_only=True)
    author_name = serializers.CharField(
        source="author.get_full_name", read_only=True, default=None)
    category_name = serializers.CharField(read_only=True)
    is_current = serializers.BooleanField(read_only=True)
    is_current_published = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeBaseArticleRevision
        fields = [
            "id",
            "article",
            "revision_number",
            "title",
            "slug",
            "summary",
            "content",
            "category",
            "category_name",
            "tags",
            "status",
            "author",
            "author_name",
            "editor",
            "editor_name",
            "change_note",
            "restored_from_revision",
            "is_current",
            "is_current_published",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_current_published(self, obj):
        article = obj.article
        return bool(obj.is_current and article.status == "published")


class KnowledgeBaseSubmitReviewSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False, min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class KnowledgeBaseReviewDecisionSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False, min_value=1)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class KnowledgeBaseRejectSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False, min_value=1)
    comment = serializers.CharField(required=True, allow_blank=False, max_length=2000)


class KnowledgeBaseRestoreSerializer(serializers.Serializer):
    revision_number = serializers.IntegerField(min_value=1)
    version = serializers.IntegerField(required=False, min_value=1)


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