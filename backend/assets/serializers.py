from rest_framework import serializers

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
    Disposal, Maintenance,
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
    has_open_maintenance = serializers.SerializerMethodField(read_only=True)
    upcoming_maintenance_title = serializers.SerializerMethodField(
        read_only=True)
    upcoming_maintenance_status = serializers.SerializerMethodField(
        read_only=True)

    def get_has_open_maintenance(self, obj):
        return obj.has_open_maintenance

    def get_upcoming_maintenance_title(self, obj):
        m = obj.upcoming_maintenance
        return m.title if m else ""

    def get_upcoming_maintenance_status(self, obj):
        m = obj.upcoming_maintenance
        return m.status if m else ""

    class Meta:
        model = Asset
        fields = ["id", "asset_tag", "name", "description", "category",
                  "category_name", "serial_number", "status",
                  "assigned_to", "assigned_to_email", "department",
                  "department_name", "photo_attachment_id", "location",
                  "purchase_date", "warranty_expiry", "purchase_cost",
                  "has_open_maintenance", "upcoming_maintenance_title",
                  "upcoming_maintenance_status", "created_at", "updated_at"]
        read_only_fields = ["id", "assigned_to", "created_at", "updated_at",
                            "has_open_maintenance",
                            "upcoming_maintenance_title",
                            "upcoming_maintenance_status"]

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


class MaintenanceSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    assigned_to_email = serializers.CharField(
        source="assigned_to.email", read_only=True, allow_null=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, allow_null=True)
    is_overdue = serializers.SerializerMethodField(read_only=True)

    def get_is_overdue(self, obj):
        return obj.is_overdue

    class Meta:
        model = Maintenance
        fields = ["id", "asset", "asset_tag", "asset_name", "title",
                  "maintenance_type", "description", "status",
                  "scheduled_date", "start_date", "completion_date",
                  "assigned_to", "assigned_to_email", "vendor", "cost",
                  "resolution_notes", "is_overdue", "created_by",
                  "created_by_email", "created_at", "updated_at"]
        read_only_fields = ["id", "asset_tag", "asset_name",
                            "assigned_to_email", "created_by_email",
                            "is_overdue", "created_at", "updated_at"]

    def validate(self, attrs):
        # A completed maintenance must have a completion date.
        status = attrs.get("status")
        completion_date = attrs.get("completion_date")
        if status == "completed" and not completion_date:
            raise serializers.ValidationError(
                {"completion_date": "Set a completion date when marking "
                                    "maintenance completed."})
        if completion_date and status != "completed":
            raise serializers.ValidationError(
                {"status": "A completion date requires status 'completed'."})
        # An in-progress maintenance should have a start date.
        if status == "in_progress" and not attrs.get("start_date"):
            from django.utils import timezone
            attrs["start_date"] = timezone.now()
        return attrs


class DisposalSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    responsible_person_email = serializers.CharField(
        source="responsible_person.email", read_only=True, allow_null=True)
    approver_email = serializers.CharField(
        source="approver.email", read_only=True, allow_null=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, allow_null=True)
    is_completed = serializers.SerializerMethodField(read_only=True)

    def get_is_completed(self, obj):
        return obj.is_completed

    class Meta:
        model = Disposal
        fields = ["id", "asset", "asset_tag", "asset_name",
                  "disposal_date", "disposal_reason", "disposal_method",
                  "disposal_value", "responsible_person",
                  "responsible_person_email", "approval_status", "approver",
                  "approver_email", "approved_at", "notes",
                  "created_by", "created_by_email", "is_completed",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "asset_tag", "asset_name",
                            "responsible_person_email", "approver_email",
                            "created_by_email", "is_completed",
                            "approved_at", "created_at", "updated_at"]

    def validate(self, attrs):
        approval_status = attrs.get("approval_status")
        disposal_date = attrs.get("disposal_date")
        if disposal_date and approval_status != "approved":
            raise serializers.ValidationError(
                {"disposal_date": "A disposal date requires an approved "
                                  "disposal."})
        if approval_status in ("approved", "rejected") and not attrs.get(
                "approver"):
            raise serializers.ValidationError(
                {"approver": "An approver is required once approval is not "
                             "pending."})
        return attrs
