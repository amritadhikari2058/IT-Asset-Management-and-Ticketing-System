"""PM1 admin (Gate 1). History is fully read-only; server-managed fields are
read-only on Problem to mirror the API contract."""
from django.contrib import admin

from .models import (
    Problem,
    ProblemAssetLink,
    ProblemConfigurationItemLink,
    ProblemHistory,
    ProblemNumberSequence,
    ProblemServiceLink,
    ProblemSoftwareProductLink,
    ProblemTask,
    ProblemTicketLink,
)


class ProblemHistoryInline(admin.TabularInline):
    model = ProblemHistory
    extra = 0
    can_delete = False
    fields = (
        "created_at", "actor", "event_type", "previous_status",
        "new_status", "detail",
    )
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = (
        "problem_number", "title", "status", "priority", "severity",
        "problem_type", "owner", "problem_manager", "record_version",
        "created_at",
    )
    list_filter = ("status", "problem_type", "priority", "severity", "environment")
    search_fields = ("problem_number", "title", "description")
    ordering = ("-created_at",)
    readonly_fields = (
        "problem_number", "status", "record_version", "recurrence_count",
        "linked_ticket_count", "open_ticket_count", "first_detected_at",
        "investigation_started_at", "root_cause_identified_at",
        "workaround_available_at", "known_error_at", "permanent_fix_planned_at",
        "permanent_fix_implemented_at", "validation_started_at", "resolved_at",
        "closed_at", "reopened_at", "root_cause_summary",
        "workaround_summary", "permanent_fix_summary", "resolution_summary",
        "closure_reason", "created_by", "created_at", "updated_at",
        "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
    )
    inlines = [ProblemHistoryInline]


@admin.register(ProblemTicketLink)
class ProblemTicketLinkAdmin(admin.ModelAdmin):
    list_display = (
        "problem", "ticket", "relationship_type", "relevance", "is_primary",
        "linked_at",
    )
    list_filter = ("relationship_type", "relevance")
    search_fields = ("problem__problem_number",)
    raw_id_fields = ("problem", "ticket", "linked_by")
    readonly_fields = ("linked_by", "linked_at")


@admin.register(ProblemConfigurationItemLink)
class ProblemConfigurationItemLinkAdmin(admin.ModelAdmin):
    list_display = ("problem", "configuration_item", "impact_type", "role", "confidence")
    raw_id_fields = ("problem", "configuration_item", "created_by")
    readonly_fields = ("created_by", "created_at")


@admin.register(ProblemServiceLink)
class ProblemServiceLinkAdmin(admin.ModelAdmin):
    list_display = ("problem", "service", "impact_type", "role", "confidence")
    raw_id_fields = ("problem", "service", "created_by")
    readonly_fields = ("created_by", "created_at")


@admin.register(ProblemAssetLink)
class ProblemAssetLinkAdmin(admin.ModelAdmin):
    list_display = ("problem", "asset", "impact_type", "role", "confidence")
    raw_id_fields = ("problem", "asset", "created_by")
    readonly_fields = ("created_by", "created_at")


@admin.register(ProblemSoftwareProductLink)
class ProblemSoftwareProductLinkAdmin(admin.ModelAdmin):
    list_display = (
        "problem", "software_product", "impact_type", "role", "confidence",
    )
    raw_id_fields = ("problem", "software_product", "created_by")
    readonly_fields = ("created_by", "created_at")


@admin.register(ProblemTask)
class ProblemTaskAdmin(admin.ModelAdmin):
    list_display = (
        "problem", "sequence", "title", "task_type", "status",
        "assigned_to", "due_at", "required", "blocks_resolution",
    )
    list_filter = ("status", "task_type", "required", "blocks_resolution")
    search_fields = ("title", "problem__problem_number")
    raw_id_fields = ("problem", "assigned_to", "completed_by", "created_by")
    readonly_fields = (
        "status", "sequence", "version", "started_at", "completed_at",
        "completed_by", "created_by", "created_at", "updated_at",
    )


@admin.register(ProblemHistory)
class ProblemHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "problem", "event_type", "actor", "previous_status", "new_status",
        "created_at",
    )
    list_filter = ("event_type",)
    search_fields = ("problem__problem_number", "detail")
    ordering = ("-created_at",)
    readonly_fields = (
        "problem", "task", "actor", "event_type", "previous_status",
        "new_status", "detail", "changed_fields", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProblemNumberSequence)
class ProblemNumberSequenceAdmin(admin.ModelAdmin):
    list_display = ("prefix", "last_value")
    readonly_fields = ("prefix", "last_value")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
