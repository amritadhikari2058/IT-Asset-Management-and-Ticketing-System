from rest_framework import serializers

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
)
from tickets.serializers import validate_attachment_file


class AssetCategorySerializer(serializers.ModelSerializer):
    asset_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AssetCategory
        fields = ["id", "name", "description", "is_active",
                  "asset_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class AssetSerializer(serializers.ModelSerializer):
    """General updates must NOT include assigned_to (see assign endpoint).

    The view pops 'assigned_to' from ordinary updates to prevent silent
    assignment overwrites per spec.
    """
    category_name = serializers.CharField(source="category.name", read_only=True)
    assigned_to_email = serializers.CharField(
        source="assigned_to.email", read_only=True
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True
    )
    photo_attachment_id = serializers.IntegerField(
        read_only=True, allow_null=True
    )

    class Meta:
        model = Asset
        fields = ["id", "asset_tag", "name", "description", "category",
                  "category_name", "serial_number", "status",
                  "assigned_to", "assigned_to_email", "department",
                  "department_name", "photo_attachment_id", "location",
                  "purchase_date", "warranty_expiry", "purchase_cost",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "assigned_to", "created_at", "updated_at"]

    def validate_serial_number(self, value):
        """Optional, but unique when present - across ALL assets.

        Soft-deleted assets keep reserving their serial (restore must never
        collide), so the lookup uses all_objects. Excludes the instance
        being updated, so an unchanged serial passes ordinary edits. Input
        is trimmed so "SN-1 " and "SN-1" cannot coexist. The DB triggers
        from migration 0003 enforce the same rule for concurrent writers.
        """
        value = (value or "").strip()
        if not value:
            return value
        others = Asset.all_objects.all()
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        if others.filter(serial_number=value).exists():
            raise serializers.ValidationError(
                f"Serial number '{value}' is already used by another "
                "asset. Serial numbers must be unique.")
        return value


class AssetAssignSerializer(serializers.Serializer):
    assigned_to = serializers.IntegerField(allow_null=True, required=False)
    note = serializers.CharField(required=False, allow_blank=True)


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = ["id", "asset", "assigned_to", "assigned_by",
                  "assigned_at", "returned_at", "note"]
        read_only_fields = ["id", "assigned_at"]


class AssetHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = AssetHistory
        fields = ["id", "asset", "actor", "actor_email", "action",
                  "timestamp", "old_values", "new_values", "note"]
        read_only_fields = fields


class AssetAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetAttachment
        fields = ["id", "asset", "file", "original_filename",
                  "uploaded_by", "created_at"]
        read_only_fields = ["id", "uploaded_by", "created_at"]

    def validate_file(self, f):
        # Same policy as ticket attachments (single implementation).
        return validate_attachment_file(f)
