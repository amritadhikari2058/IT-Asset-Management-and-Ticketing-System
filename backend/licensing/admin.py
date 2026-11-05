"""Django Admin registration for Software Licensing models."""

from django.contrib import admin

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


@admin.register(SoftwareProduct)
class SoftwareProductAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "publisher", "category", "approved_status", "is_active"]
    list_filter = ["approved_status", "category", "platform", "is_active"]
    search_fields = ["name", "code", "publisher"]


@admin.register(LicenseAgreement)
class LicenseAgreementAdmin(admin.ModelAdmin):
    list_display = [
        "agreement_number",
        "software_product",
        "agreement_type",
        "license_model",
        "status",
        "quantity_purchased",
        "quantity_allocated",
        "quantity_available",
        "expiry_date",
    ]
    list_filter = ["status", "agreement_type", "license_model"]
    search_fields = ["agreement_number", "software_product__name", "contract_reference"]
    readonly_fields = ["agreement_number", "quantity_allocated", "quantity_reserved", "quantity_available"]


@admin.register(LicenseSecret)
class LicenseSecretAdmin(admin.ModelAdmin):
    list_display = ["label", "agreement", "secret_type", "status", "last_four", "last_viewed_at"]
    list_filter = ["secret_type", "status"]
    search_fields = ["label", "agreement__agreement_number"]
    readonly_fields = ["encrypted_value", "value_fingerprint", "last_four", "last_viewed_at", "last_viewed_by"]


@admin.register(LicenseAllocation)
class LicenseAllocationAdmin(admin.ModelAdmin):
    list_display = ["allocation_reference", "agreement", "allocation_type", "assigned_user", "assigned_asset", "status"]
    list_filter = ["allocation_type", "status"]
    search_fields = ["allocation_reference", "assigned_user__email", "assigned_asset__asset_tag"]


@admin.register(SoftwareInstallation)
class SoftwareInstallationAdmin(admin.ModelAdmin):
    list_display = ["software_product", "asset", "status", "compliance_status", "installed_version"]
    list_filter = ["status", "compliance_status"]
    search_fields = ["software_product__name", "asset__asset_tag"]


@admin.register(LicenseRenewal)
class LicenseRenewalAdmin(admin.ModelAdmin):
    list_display = ["agreement", "status", "proposed_expiry_date", "proposed_total_cost", "currency"]
    list_filter = ["status"]
    search_fields = ["agreement__agreement_number"]


@admin.register(LicenseComplianceFinding)
class LicenseComplianceFindingAdmin(admin.ModelAdmin):
    list_display = ["title", "finding_type", "severity", "status", "detected_at"]
    list_filter = ["finding_type", "severity", "status"]
    search_fields = ["title", "software_product__name"]


@admin.register(LicenseDocument)
class LicenseDocumentAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "agreement", "document_type", "status", "created_at"]
    list_filter = ["document_type", "status"]
    search_fields = ["original_filename", "agreement__agreement_number"]


@admin.register(LicenseHistory)
class LicenseHistoryAdmin(admin.ModelAdmin):
    list_display = ["event_type", "agreement", "actor", "created_at"]
    list_filter = ["event_type"]
    search_fields = ["agreement__agreement_number"]
    readonly_fields = ["agreement", "allocation", "installation", "actor", "event_type", "previous_status", "new_status", "detail", "created_at"]
