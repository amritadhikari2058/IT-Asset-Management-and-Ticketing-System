"""Django admin for CMDB models.

History is strictly read-only: it is an immutable audit trail written by
the application (save() raises outside object creation).
"""

from django.contrib import admin

from common.admin_config import SoftDeleteAdmin

from .models import (
    CMDBServiceProfile,
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemChangeLink,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
    ConfigurationItemTicketLink,
    ConfigurationItemType,
    ServiceConfigurationItemLink,
)


@admin.register(ConfigurationItemType)
class ConfigurationItemTypeAdmin(SoftDeleteAdmin):
    list_display = ("name", "code", "category", "is_active", "is_system",
                    "is_deleted_flag")
    list_filter = ("category", "is_active", "is_system", "is_deleted")
    search_fields = ("name", "code", "description")
    readonly_fields = ("is_system", "created_by", "created_at", "updated_at")


class ConfigurationItemHistoryInline(admin.TabularInline):
    model = ConfigurationItemHistory
    extra = 0
    can_delete = False
    fields = ("event_type", "actor", "changed_fields", "detail", "created_at")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ConfigurationItem)
class ConfigurationItemAdmin(SoftDeleteAdmin):
    list_display = ("ci_number", "name", "ci_type", "status", "criticality",
                    "environment", "owner", "is_deleted_flag")
    list_filter = ("status", "criticality", "environment", "source",
                   "is_deleted")
    search_fields = ("ci_number", "name", "hostname", "serial_number",
                     "ip_address", "source_identifier")
    readonly_fields = ("ci_number", "record_version", "source",
                       "source_identifier", "created_by", "created_at",
                       "updated_at", "last_verified_at", "verified_by")
    inlines = [ConfigurationItemHistoryInline]


@admin.register(ConfigurationItemRelationship)
class ConfigurationItemRelationshipAdmin(SoftDeleteAdmin):
    list_display = ("source_ci", "relationship_type", "target_ci", "status",
                    "confidence", "is_deleted_flag")
    list_filter = ("relationship_type", "status", "confidence", "is_deleted")
    search_fields = ("source_ci__ci_number", "target_ci__ci_number",
                     "source_ci__name", "target_ci__name", "description")
    readonly_fields = ("created_by", "created_at", "updated_at")


@admin.register(ConfigurationItemHistory)
class ConfigurationItemHistoryAdmin(admin.ModelAdmin):
    """Strictly read-only immutable audit trail."""

    list_display = ("created_at", "configuration_item", "event_type", "actor",
                    "source")
    list_filter = ("event_type", "source")
    search_fields = ("configuration_item__ci_number",
                     "configuration_item__name", "detail")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfigurationBaseline)
class ConfigurationBaselineAdmin(SoftDeleteAdmin):
    list_display = ("code", "name", "scope_type", "status", "version",
                    "approved_by", "is_deleted_flag")
    list_filter = ("status", "scope_type", "is_deleted")
    search_fields = ("code", "name")
    readonly_fields = ("code", "version", "created_by",
                       "approved_by", "approved_at", "created_at",
                       "updated_at")


@admin.register(ConfigurationDriftFinding)
class ConfigurationDriftFindingAdmin(SoftDeleteAdmin):
    list_display = ("configuration_item", "finding_type", "severity",
                    "status", "field_name", "detected_at",
                    "is_deleted_flag")
    list_filter = ("finding_type", "severity", "status", "is_deleted")
    search_fields = ("configuration_item__ci_number",
                     "configuration_item__name", "field_name", "fingerprint")
    date_hierarchy = "detected_at"
    readonly_fields = ("fingerprint", "detected_at", "resolved_at",
                       "resolved_by", "acknowledged_at", "acknowledged_by",
                       "created_at", "updated_at")


@admin.register(CMDBServiceProfile)
class CMDBServiceProfileAdmin(SoftDeleteAdmin):
    list_display = ("service", "criticality", "service_tier",
                    "service_owner", "is_deleted_flag")
    list_filter = ("criticality", "service_tier", "is_deleted")
    search_fields = ("service__name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ServiceConfigurationItemLink)
class ServiceConfigurationItemLinkAdmin(SoftDeleteAdmin):
    list_display = ("service", "configuration_item", "role",
                    "is_required", "redundancy_group", "is_deleted_flag")
    list_filter = ("role", "is_required", "is_deleted")
    search_fields = ("service__name", "configuration_item__ci_number",
                     "configuration_item__name", "redundancy_group")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ConfigurationItemTicketLink)
class ConfigurationItemTicketLinkAdmin(SoftDeleteAdmin):
    list_display = ("configuration_item", "ticket", "relation_type",
                    "is_deleted_flag")
    list_filter = ("relation_type", "is_deleted")
    search_fields = ("configuration_item__ci_number", "ticket__title")
    readonly_fields = ("created_at",)


@admin.register(ConfigurationItemChangeLink)
class ConfigurationItemChangeLinkAdmin(SoftDeleteAdmin):
    list_display = ("configuration_item", "change", "change_role",
                    "impact_type", "is_deleted_flag")
    list_filter = ("change_role", "impact_type", "is_deleted")
    search_fields = ("configuration_item__ci_number",
                     "change__change_number")
    readonly_fields = ("created_at",)
