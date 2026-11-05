from django.contrib import admin

from lifecycle.models import (
    LifecycleAssetResolution, LifecycleCase, LifecycleTask,
    LifecycleTaskEvidence, LifecycleTemplate, LifecycleTemplateItem,
)


@admin.register(LifecycleTemplate)
class LifecycleTemplateAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "case_type", "is_active", "version"]
    list_filter = ["case_type", "is_active", "department"]
    search_fields = ["code", "name"]


@admin.register(LifecycleTemplateItem)
class LifecycleTemplateItemAdmin(admin.ModelAdmin):
    list_display = ["template", "sequence", "title", "category", "responsibility", "required"]
    list_filter = ["template", "category", "responsibility", "required", "requires_evidence"]
    search_fields = ["title"]


@admin.register(LifecycleCase)
class LifecycleCaseAdmin(admin.ModelAdmin):
    list_display = ["case_number", "case_type", "employee", "status", "priority", "assigned_coordinator"]
    list_filter = ["case_type", "status", "priority", "department"]
    search_fields = ["case_number", "employee__employee_id", "employee__email"]


@admin.register(LifecycleTask)
class LifecycleTaskAdmin(admin.ModelAdmin):
    list_display = ["case", "sequence", "title", "status", "responsibility", "assigned_to"]
    list_filter = ["status", "category", "responsibility", "automation_status"]
    search_fields = ["title", "case__case_number"]


@admin.register(LifecycleAssetResolution)
class LifecycleAssetResolutionAdmin(admin.ModelAdmin):
    list_display = ["case", "asset", "status", "resolution", "resolved_at"]
    list_filter = ["status", "resolution"]


@admin.register(LifecycleTaskEvidence)
class LifecycleTaskEvidenceAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "case", "task", "uploaded_by", "created_at"]
    list_filter = ["is_deleted"]
