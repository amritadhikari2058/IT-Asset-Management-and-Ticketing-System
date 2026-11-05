"""Serializers for Software Products, Agreements, Allocations, and Secrets.

Enforces field-level data separation:
- Employee serializers expose safe catalog and personal allocation fields only.
- Financial details, internal notes, vendor contracts, and secret metadata are restricted.
- LicenseSecret write-only plaintext input with zero plaintext leakage in representations.
- Action serializers validate state transitions and prevent arbitrary status PATCHing.
"""

from decimal import Decimal
from rest_framework import serializers

from accounts.models import User, Department
from assets.models import Asset, Vendor
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    LicenseDocument,
    LicenseHistory,
    LicenseRenewal,
    LicenseSecret,
    SoftwareInstallation,
    SoftwareProduct,
)
from licensing.security import (
    compute_secret_fingerprint,
    encrypt_secret,
    extract_last_four,
    is_encryption_available,
)


# ==============================================================================
# SOFTWARE PRODUCT SERIALIZERS
# ==============================================================================

class SoftwareProductSerializer(serializers.ModelSerializer):
    """Full SoftwareProduct serializer for IT Staff."""

    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)

    class Meta:
        model = SoftwareProduct
        fields = [
            "id",
            "name",
            "code",
            "publisher",
            "vendor",
            "vendor_name",
            "product_family",
            "edition",
            "version",
            "category",
            "description",
            "website",
            "platform",
            "license_required",
            "license_model",
            "approved_status",
            "risk_level",
            "support_status",
            "support_end_date",
            "end_of_life_date",
            "is_active",
            "notes",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["created_by"] = user
        return super().create(validated_data)


class EmployeeSoftwareProductSerializer(serializers.ModelSerializer):
    """Safe, read-only product serializer for regular employees.

    Financial data, internal notes, and administrative fields are omitted.
    """

    class Meta:
        model = SoftwareProduct
        fields = [
            "id",
            "name",
            "publisher",
            "edition",
            "version",
            "category",
            "description",
            "website",
            "platform",
            "approved_status",
            "support_status",
            "support_end_date",
        ]
        read_only_fields = fields


# ==============================================================================
# LICENSE AGREEMENT SERIALIZERS
# ==============================================================================

class LicenseAgreementSerializer(serializers.ModelSerializer):
    """Full LicenseAgreement serializer for IT Staff."""

    product_name = serializers.CharField(source="software_product.name", read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    owner_email = serializers.CharField(source="owner.email", read_only=True)
    contract_manager_email = serializers.CharField(source="contract_manager.email", read_only=True)
    is_unlimited = serializers.BooleanField(read_only=True)
    utilization_percent = serializers.FloatField(read_only=True)

    class Meta:
        model = LicenseAgreement
        fields = [
            "id",
            "agreement_number",
            "software_product",
            "product_name",
            "vendor",
            "vendor_name",
            "procurement_purchase_order",
            "procurement_purchase_order_line",
            "agreement_type",
            "license_model",
            "status",
            "purchase_date",
            "start_date",
            "expiry_date",
            "renewal_date",
            "grace_period_days",
            "auto_renew",
            "renewal_notice_days",
            "currency",
            "unit_cost",
            "total_cost",
            "quantity_purchased",
            "quantity_reserved",
            "quantity_allocated",
            "quantity_available",
            "is_unlimited",
            "utilization_percent",
            "concurrent_limit",
            "maintenance_included",
            "support_included",
            "support_expiry_date",
            "contract_reference",
            "invoice_reference",
            "external_subscription_id",
            "billing_frequency",
            "department",
            "department_name",
            "cost_center",
            "owner",
            "owner_email",
            "contract_manager",
            "contract_manager_email",
            "terms_summary",
            "internal_notes",
            "created_by",
            "created_at",
            "updated_at",
            "version",
        ]
        read_only_fields = [
            "id",
            "agreement_number",
            "status",
            "quantity_reserved",
            "quantity_allocated",
            "quantity_available",
            "is_unlimited",
            "utilization_percent",
            "created_by",
            "created_at",
            "updated_at",
            "version",
        ]

    def create(self, validated_data):
        from licensing.services import generate_agreement_number
        validated_data["agreement_number"] = generate_agreement_number()
        validated_data["created_by"] = self.context["request"].user
        agreement = super().create(validated_data)
        agreement.recalculate_counters(save=True)
        return agreement


class AgreementActionSerializer(serializers.Serializer):
    """Input serializer for agreement lifecycle transition actions."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")
    revoke_allocations = serializers.BooleanField(required=False, default=False)


# ==============================================================================
# LICENSE SECRET SERIALIZERS
# ==============================================================================

class LicenseSecretSerializer(serializers.ModelSerializer):
    """Metadata-only serializer for LicenseSecret.

    Plaintext is NEVER returned in response. Plaintext accepted via write_only field.
    """

    plaintext_value = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
        help_text="Plaintext secret value. Immediately encrypted and never stored or returned.",
    )
    last_viewed_by_email = serializers.CharField(source="last_viewed_by.email", read_only=True)
    rotated_by_email = serializers.CharField(source="rotated_by.email", read_only=True)

    class Meta:
        model = LicenseSecret
        fields = [
            "id",
            "agreement",
            "secret_type",
            "label",
            "value_fingerprint",
            "last_four",
            "status",
            "plaintext_value",
            "created_at",
            "updated_at",
            "last_viewed_at",
            "last_viewed_by_email",
            "rotated_at",
            "rotated_by_email",
        ]
        read_only_fields = [
            "id",
            "value_fingerprint",
            "last_four",
            "status",
            "created_at",
            "updated_at",
            "last_viewed_at",
            "last_viewed_by_email",
            "rotated_at",
            "rotated_by_email",
        ]

    def validate_plaintext_value(self, value):
        ready, reason = is_encryption_available()
        if not ready:
            raise serializers.ValidationError(
                f"Secret storage is currently unavailable: {reason} "
                "Configure LICENSE_SECRET_ENCRYPTION_KEY to enable secret operations."
            )
        if len(value) > 4096:
            raise serializers.ValidationError("Secret length exceeds maximum allowed 4096 characters.")
        return value

    def create(self, validated_data):
        plaintext = validated_data.pop("plaintext_value")
        encrypted = encrypt_secret(plaintext)
        fingerprint = compute_secret_fingerprint(plaintext)
        last_four = extract_last_four(plaintext)
        user = self.context["request"].user

        secret = LicenseSecret.objects.create(
            encrypted_value=encrypted,
            value_fingerprint=fingerprint,
            last_four=last_four,
            created_by=user,
            **validated_data,
        )
        return secret


class LicenseSecretRotateSerializer(serializers.Serializer):
    """Input serializer for secret rotation."""

    new_plaintext_value = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )
    new_label = serializers.CharField(required=False, allow_blank=True, default="")


class LicenseSecretRevealResponseSerializer(serializers.Serializer):
    """Single-use response serializer for protected secret revelation."""

    id = serializers.IntegerField()
    secret_type = serializers.CharField()
    label = serializers.CharField()
    revealed_value = serializers.CharField()


# ==============================================================================
# LICENSE ALLOCATION SERIALIZERS
# ==============================================================================

class LicenseAllocationSerializer(serializers.ModelSerializer):
    """Full LicenseAllocation serializer for IT Staff."""

    agreement_number = serializers.CharField(source="agreement.agreement_number", read_only=True)
    product_name = serializers.CharField(source="agreement.software_product.name", read_only=True)
    user_email = serializers.CharField(source="assigned_user.email", read_only=True)
    asset_tag = serializers.CharField(source="assigned_asset.asset_tag", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    assigned_by_email = serializers.CharField(source="assigned_by.email", read_only=True)

    class Meta:
        model = LicenseAllocation
        fields = [
            "id",
            "agreement",
            "agreement_number",
            "product_name",
            "allocation_type",
            "assigned_user",
            "user_email",
            "assigned_asset",
            "asset_tag",
            "department",
            "department_name",
            "allocation_reference",
            "status",
            "assigned_at",
            "assigned_by",
            "assigned_by_email",
            "activated_at",
            "last_verified_at",
            "revoked_at",
            "revocation_reason",
            "expected_release_date",
            "notes",
            "service_request",
            "created_at",
            "updated_at",
            "version",
        ]
        read_only_fields = [
            "id",
            "agreement_number",
            "product_name",
            "allocation_reference",
            "status",
            "assigned_at",
            "assigned_by",
            "activated_at",
            "revoked_at",
            "revocation_reason",
            "created_at",
            "updated_at",
            "version",
        ]


class EmployeeLicenseAllocationSerializer(serializers.ModelSerializer):
    """Safe allocation serializer for employee My-Software views."""

    product_name = serializers.CharField(source="agreement.software_product.name", read_only=True)
    publisher = serializers.CharField(source="agreement.software_product.publisher", read_only=True)
    edition = serializers.CharField(source="agreement.software_product.edition", read_only=True)
    version = serializers.CharField(source="agreement.software_product.version", read_only=True)
    asset_tag = serializers.CharField(source="assigned_asset.asset_tag", read_only=True)

    class Meta:
        model = LicenseAllocation
        fields = [
            "id",
            "allocation_reference",
            "product_name",
            "publisher",
            "edition",
            "version",
            "allocation_type",
            "status",
            "assigned_at",
            "expected_release_date",
            "asset_tag",
            "last_verified_at",
        ]
        read_only_fields = fields


class AllocateUserSerializer(serializers.Serializer):
    """Input serializer for allocating a license seat to an employee."""

    assigned_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_deleted=False))
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    expected_release_date = serializers.DateTimeField(required=False, allow_null=True)
    allow_duplicate = serializers.BooleanField(required=False, default=False)


class AllocateDeviceSerializer(serializers.Serializer):
    """Input serializer for allocating a license seat to a device."""

    assigned_asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.filter(is_deleted=False))
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    expected_release_date = serializers.DateTimeField(required=False, allow_null=True)
    allow_duplicate = serializers.BooleanField(required=False, default=False)


class ReserveConcurrentSerializer(serializers.Serializer):
    """Input serializer for reserving a concurrent license seat."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")
    expected_release_date = serializers.DateTimeField(required=False, allow_null=True)


class BulkAllocateItemSerializer(serializers.Serializer):
    allocation_type = serializers.ChoiceField(choices=["user", "device", "department"])
    assigned_user_id = serializers.IntegerField(required=False)
    assigned_asset_id = serializers.IntegerField(required=False)
    department_id = serializers.IntegerField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    allow_duplicate = serializers.BooleanField(required=False, default=False)


class BulkAllocateSerializer(serializers.Serializer):
    allocations = BulkAllocateItemSerializer(many=True)


class BulkRevokeSerializer(serializers.Serializer):
    allocation_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    reason = serializers.CharField(required=True)


class AllocationActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


# ==============================================================================
# SOFTWARE INSTALLATION SERIALIZERS
# ==============================================================================

class SoftwareInstallationSerializer(serializers.ModelSerializer):
    """Full SoftwareInstallation serializer."""

    product_name = serializers.CharField(source="software_product.name", read_only=True)
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    installed_by_email = serializers.CharField(source="installed_by.email", read_only=True)

    class Meta:
        model = SoftwareInstallation
        fields = [
            "id",
            "software_product",
            "product_name",
            "asset",
            "asset_tag",
            "allocation",
            "installed_version",
            "install_date",
            "installed_by",
            "installed_by_email",
            "detected_at",
            "last_seen_at",
            "status",
            "source",
            "is_authorized",
            "compliance_status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "detected_at",
            "created_at",
            "updated_at",
        ]


# ==============================================================================
# RENEWAL SERIALIZERS
# ==============================================================================

class LicenseRenewalSerializer(serializers.ModelSerializer):
    """Full LicenseRenewal serializer."""

    agreement_number = serializers.CharField(source="agreement.agreement_number", read_only=True)
    product_name = serializers.CharField(source="agreement.software_product.name", read_only=True)
    requested_by_email = serializers.CharField(source="requested_by.email", read_only=True)
    reviewed_by_email = serializers.CharField(source="reviewed_by.email", read_only=True)

    class Meta:
        model = LicenseRenewal
        fields = [
            "id",
            "agreement",
            "agreement_number",
            "product_name",
            "previous_start_date",
            "previous_expiry_date",
            "proposed_start_date",
            "proposed_expiry_date",
            "proposed_quantity",
            "proposed_unit_cost",
            "proposed_total_cost",
            "currency",
            "status",
            "reason",
            "requested_by",
            "requested_by_email",
            "reviewed_by",
            "reviewed_by_email",
            "requested_at",
            "reviewed_at",
            "review_reason",
            "procurement_purchase_request",
            "procurement_purchase_order",
            "created_at",
            "updated_at",
            "version",
        ]
        read_only_fields = [
            "id",
            "previous_start_date",
            "previous_expiry_date",
            "status",
            "requested_by",
            "reviewed_by",
            "requested_at",
            "reviewed_at",
            "review_reason",
            "created_at",
            "updated_at",
            "version",
        ]


class RenewalActionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    review_reason = serializers.CharField(required=False, allow_blank=True, default="")


LicenseRenewalActionSerializer = RenewalActionSerializer


# ==============================================================================
# COMPLIANCE FINDING SERIALIZERS
# ==============================================================================

class LicenseComplianceFindingSerializer(serializers.ModelSerializer):
    """Full Compliance Finding serializer."""

    product_name = serializers.CharField(source="software_product.name", read_only=True)
    agreement_number = serializers.CharField(source="agreement.agreement_number", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    resolved_by_email = serializers.CharField(source="resolved_by.email", read_only=True)

    class Meta:
        model = LicenseComplianceFinding
        fields = [
            "id",
            "finding_type",
            "severity",
            "software_product",
            "product_name",
            "agreement",
            "agreement_number",
            "allocation",
            "installation",
            "asset",
            "asset_tag",
            "user",
            "user_email",
            "status",
            "title",
            "description",
            "detected_at",
            "resolved_at",
            "resolved_by",
            "resolved_by_email",
            "resolution_note",
            "fingerprint",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "finding_type",
            "detected_at",
            "resolved_at",
            "resolved_by",
            "fingerprint",
            "created_at",
            "updated_at",
        ]


class ComplianceResolveSerializer(serializers.Serializer):
    resolution_note = serializers.CharField(required=True)
    is_false_positive = serializers.BooleanField(required=False, default=False)


# ==============================================================================
# DOCUMENT & HISTORY SERIALIZERS
# ==============================================================================

class LicenseDocumentSerializer(serializers.ModelSerializer):
    """Metadata serializer for License Documents."""

    uploaded_by_email = serializers.CharField(source="uploaded_by.email", read_only=True)

    class Meta:
        model = LicenseDocument
        fields = [
            "id",
            "agreement",
            "document_type",
            "uploaded_by",
            "uploaded_by_email",
            "original_filename",
            "file",
            "content_type",
            "size",
            "description",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_by",
            "original_filename",
            "content_type",
            "size",
            "created_at",
        ]


class LicenseHistorySerializer(serializers.ModelSerializer):
    """Read-only immutable history serializer."""

    actor_email = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = LicenseHistory
        fields = [
            "id",
            "agreement",
            "allocation",
            "installation",
            "actor",
            "actor_email",
            "event_type",
            "previous_status",
            "new_status",
            "detail",
            "created_at",
        ]
        read_only_fields = fields
