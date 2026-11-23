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
        # ``original_filename`` is the user's original upload name (set by the
        # view from the uploaded file) and is read-only: clients must not be
        # able to relabel an existing attachment. It matches the ticket
        # attachment contract; blank means a legacy row with no stored name.
        fields = ["id", "asset", "file", "original_filename",
                  "uploaded_by", "created_at", "is_deleted"]
        read_only_fields = ["id", "uploaded_by", "created_at", "is_deleted",
                            "original_filename"]

    def get_fields(self):
        # asset is writable at creation (perform_create validates visibility)
        # but read-only on updates to prevent attachment reassignment.
        fields = super().get_fields()
        if self.instance is not None:
            fields["asset"].read_only = True
        return fields

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

    def validate(self, attrs):
        """Cross-field validation for warranty and purchase data.

        - Warranty expiry must be on or after warranty start.
        - Purchase cost must be non-negative when provided.
        """
        warranty_start = attrs.get("warranty_start") or self.instance.warranty_start if self.instance else None
        warranty_expiry = attrs.get("warranty_expiry") or self.instance.warranty_expiry if self.instance else None
        purchase_cost = attrs.get("purchase_cost", self.instance.purchase_cost if self.instance else None)

        if warranty_start and warranty_expiry and warranty_expiry < warranty_start:
            raise serializers.ValidationError(
                {"warranty_expiry": "Warranty expiry must be on or after the warranty start date."})

        if purchase_cost is not None and purchase_cost < 0:
            raise serializers.ValidationError(
                {"purchase_cost": "Purchase cost must be zero or more."})

        return super().validate(attrs)

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

    asset_count = serializers.IntegerField(read_only=True, default=0)
    stock_item_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Vendor
        fields = ["id", "name", "code", "contact_person", "email",
                  "phone", "website", "address", "tax_registration",
                  "notes", "is_deleted", "created_at", "updated_at",
                  "asset_count", "stock_item_count"]
        read_only_fields = ["id", "is_deleted", "created_at", "updated_at",
                            "asset_count", "stock_item_count"]

    def validate_name(self, value):
        """Normalize vendor name: trim, collapse internal spaces, uppercase."""
        value = (value or "").strip()
        # Collapse multiple internal spaces to one
        while "  " in value:
            value = value.replace("  ", " ")
        return value

    def validate_code(self, value):
        """Normalize vendor code: trim, uppercase."""
        value = (value or "").strip().upper()
        return value

    def validate_email(self, value):
        """Validate and normalize email."""
        value = (value or "").strip().lower()
        # Django's EmailField validation will run automatically
        return value

    def validate_website(self, value):
        """Ensure website has a scheme (defense-in-depth; normalization
        happens in to_internal_value before URLField validation)."""
        value = (value or "").strip()
        if value and not value.startswith(('http://', 'https://')):
            value = 'https://' + value
        return value

    def to_internal_value(self, data):
        """Normalize website URL before URLField validation so that
        scheme-less values like 'example.com' become 'https://example.com'
        instead of being rejected as invalid URLs."""
        if isinstance(data, dict):
            website = data.get("website")
            if website and not website.startswith(("http://", "https://")):
                data = dict(data)
                data["website"] = "https://" + website
        return super().to_internal_value(data)

    def validate_phone(self, value):
        """Phone: trim but don't over-restrict international formats."""
        value = (value or "").strip()
        return value

    def validate(self, attrs):
        """Cross-field validation: prevent duplicate names differing only by
        capitalization, spaces, or normalization."""
        name = (attrs.get("name") or "").strip()
        code = (attrs.get("code") or "").strip()

        # Build queryset excluding current instance (for updates)
        queryset = Vendor.objects.all()
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        # Check for duplicate names (case-insensitive)
        if name and queryset.filter(name__iexact=name).exists():
            raise serializers.ValidationError(
                {"name": "A vendor with that name already exists."})

        # Check code uniqueness
        if code and queryset.filter(code__iexact=code).exists():
            raise serializers.ValidationError(
                {"code": "A vendor with that code already exists."})

        return attrs


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


    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if (user and user.is_authenticated
                and getattr(user, "role", "") == "employee"):
            # Published content is public to employees, while governance
            # metadata (especially rejection/review comments) is not.
            for field in (
                    "submitted_at", "reviewed_by", "reviewed_by_name",
                    "reviewed_at", "review_decision", "review_comment"):
                data.pop(field, None)
        return data


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

    def validate(self, attrs):
        # New content always enters the workflow as a draft. Publication is
        # available only through the explicit approve/publish transitions.
        if self.instance is None and attrs.get("status", "draft") != "draft":
            raise serializers.ValidationError({
                "status": "New articles must start as drafts and complete "
                          "the review workflow before publication."})
        return attrs

    def create(self, validated_data):
        validated_data = self._strip_write_only(validated_data)
        validated_data.setdefault("status", "draft")
        return super().create(validated_data)

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
        article = attrs.get(
            "article", self.instance.article if self.instance else None)
        if article and article.status != "published":
            raise serializers.ValidationError({
                "article": "Feedback is only available for published articles."})
        if self.instance is None and article:
            # One row per (article, user) — re-submitting replaces the vote.
            if KnowledgeBaseFeedback.objects.filter(
                    article=article, user=user, is_deleted=False).exists():
                raise serializers.ValidationError(
                    {"article": "You already gave feedback on this article. "
                                "Use PATCH to update it instead."})
        return attrs
