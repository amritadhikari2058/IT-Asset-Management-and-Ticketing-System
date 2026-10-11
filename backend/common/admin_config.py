"""Admin: soft-delete aware, restore + permanent-delete (Admin-only) actions."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import Department, User
from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
)
from common.models import AuditLog, Notification
from tickets.models import (
    Ticket, TicketAttachment, TicketCategory, TicketHistory, TicketNote,
)


class SoftDeleteAdmin(admin.ModelAdmin):
    list_filter = ("is_deleted",)
    readonly_fields = ("deleted_at", "deleted_by", "deletion_reason")
    actions = ["restore_selected"]

    def get_queryset(self, request):
        return self.model.all_objects.all()

    def is_deleted_flag(self, obj):
        return obj.is_deleted
    is_deleted_flag.boolean = True
    is_deleted_flag.short_description = "Deleted"

    @admin.action(description="Restore soft-deleted")
    def restore_selected(self, request, queryset):
        for obj in queryset.filter(is_deleted=True):
            obj.restore()
        self.message_user(request, "Selected records restored.")

    def delete_model(self, request, obj):
        obj.soft_delete(by_user=request.user, reason="via admin")

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.soft_delete(by_user=request.user, reason="via admin bulk")


@admin.register(Department)
class DepartmentAdmin(SoftDeleteAdmin):
    list_display = ("name", "code", "head", "is_active", "is_deleted_flag")
    search_fields = ("name", "code")
    list_filter = ("is_active", "is_deleted")


@admin.register(User)
class UserAdmin(SoftDeleteAdmin, BaseUserAdmin):
    list_display = ("employee_id", "email", "role", "home_department",
                    "is_active", "is_deleted_flag")
    search_fields = ("employee_id", "email", "username")
    list_filter = ("role", "is_active", "is_deleted")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Company", {"fields": ("employee_id", "role", "home_department",
                                "phone", "job_title", "can_create_tickets")}),
        ("Soft deletion", {"fields": ("is_deleted", "deleted_at",
                                       "deleted_by", "deletion_reason")}),
    )


@admin.register(AssetCategory)
class AssetCategoryAdmin(SoftDeleteAdmin):
    list_display = ("name", "is_active", "is_deleted_flag")
    search_fields = ("name",)


@admin.register(Asset)
class AssetAdmin(SoftDeleteAdmin):
    list_display = ("asset_tag", "name", "category", "status", "assigned_to",
                    "is_deleted_flag")
    search_fields = ("asset_tag", "name", "serial_number")
    list_filter = ("status", "category", "is_deleted")


@admin.register(TicketCategory)
class TicketCategoryAdmin(SoftDeleteAdmin):
    list_display = ("name", "is_active", "is_deleted_flag")
    search_fields = ("name",)


@admin.register(Ticket)
class TicketAdmin(SoftDeleteAdmin):
    list_display = ("id", "title", "category", "priority", "status",
                    "requester", "assignee", "is_deleted_flag")
    search_fields = ("title", "description")
    list_filter = ("status", "priority", "category", "is_deleted")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "actor", "action", "entity_type",
                    "object_id")
    search_fields = ("entity_type", "object_id", "object_repr")
    list_filter = ("action",)
    readonly_fields = ("actor", "action", "entity_type", "object_id",
                       "object_repr", "timestamp", "reason", "details")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(AssetHistory)
admin.site.register(Assignment)
admin.site.register(AssetAttachment)
admin.site.register(TicketHistory)
admin.site.register(TicketNote)
admin.site.register(TicketAttachment)
admin.site.register(Notification)
