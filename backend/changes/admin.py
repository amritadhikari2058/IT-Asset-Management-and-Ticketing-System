"""Admin registration for Change Management models."""
from django.contrib import admin

from . import models


@admin.register(models.ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = [
        "change_number", "title", "status", "change_type", "priority",
        "risk_level", "calculated_risk_score", "requester", "change_owner",
        "created_at",
    ]
    list_filter = ["status", "change_type", "risk_level", "priority", "department"]
    search_fields = ["change_number", "title", "description"]
    readonly_fields = ["change_number", "created_at", "updated_at", "version"]
    raw_id_fields = ["requester", "change_owner", "implementation_lead", "department", "current_approver"]


@admin.register(models.ChangeTemplate)
class ChangeTemplateAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "category", "default_priority", "default_risk_level", "is_active", "is_preapproved"]
    list_filter = ["is_active", "is_preapproved", "category", "default_priority"]
    search_fields = ["code", "name"]
    readonly_fields = ["code", "created_at", "updated_at", "version"]


@admin.register(models.ChangeTask)
class ChangeTaskAdmin(admin.ModelAdmin):
    list_display = ["sequence", "title", "task_type", "status", "assigned_to", "change"]
    list_filter = ["status", "task_type", "required"]
    search_fields = ["title", "change__change_number"]
    raw_id_fields = ["change", "assigned_to"]


@admin.register(models.ChangeHistory)
class ChangeHistoryAdmin(admin.ModelAdmin):
    list_display = ["change", "event_type", "actor", "created_at"]
    list_filter = ["event_type", "created_at"]
    search_fields = ["change__change_number", "detail"]
    readonly_fields = ["created_at"]
    raw_id_fields = ["change", "task", "actor"]


@admin.register(models.ChangeAssetImpact)
class ChangeAssetImpactAdmin(admin.ModelAdmin):
    list_display = ["change", "asset", "impact_type", "validation_status"]
    list_filter = ["impact_type", "validation_status"]
    search_fields = ["change__change_number", "asset__asset_tag"]
    raw_id_fields = ["change", "asset"]


@admin.register(models.ChangeServiceImpact)
class ChangeServiceImpactAdmin(admin.ModelAdmin):
    list_display = ["change", "service_catalogue_item", "impact_level"]
    list_filter = ["impact_level"]
    search_fields = ["change__change_number", "service_catalogue_item__name"]
    raw_id_fields = ["change", "service_catalogue_item"]


@admin.register(models.ChangeDependency)
class ChangeDependencyAdmin(admin.ModelAdmin):
    list_display = ["predecessor", "successor", "dependency_type", "created_at"]
    list_filter = ["dependency_type"]
    search_fields = ["predecessor__change_number", "successor__change_number"]
    raw_id_fields = ["predecessor", "successor", "created_by"]


@admin.register(models.ChangeRiskAssessment)
class ChangeRiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ["change", "total_score", "calculated_level", "assessed_by", "assessed_at"]
    list_filter = ["calculated_level", "assessed_at"]
    search_fields = ["change__change_number"]
    raw_id_fields = ["change", "assessed_by", "overridden_by"]


@admin.register(models.ChangeApproval)
class ChangeApprovalAdmin(admin.ModelAdmin):
    list_display = ["change", "approval_level", "status", "requester", "decided_by", "created_at"]
    list_filter = ["status", "approval_level"]
    search_fields = ["change__change_number"]
    raw_id_fields = ["change", "requester", "decided_by", "requested_from"]


@admin.register(models.ChangeReviewMeeting)
class ChangeReviewMeetingAdmin(admin.ModelAdmin):
    list_display = ["title", "meeting_date", "status", "chair", "created_at"]
    list_filter = ["status", "meeting_date"]
    search_fields = ["title"]
    raw_id_fields = ["chair", "created_by"]
    filter_horizontal = ["attendees"]


@admin.register(models.ChangeReviewItem)
class ChangeReviewItemAdmin(admin.ModelAdmin):
    list_display = ["meeting", "change", "decision", "decided_by", "created_at"]
    list_filter = ["decision"]
    search_fields = ["change__change_number"]
    raw_id_fields = ["meeting", "change", "decided_by"]


@admin.register(models.MaintenanceWindow)
class MaintenanceWindowAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "window_type", "start_at", "end_at", "status"]
    list_filter = ["window_type", "status", "blackout"]
    search_fields = ["code", "name"]
    raw_id_fields = ["created_by", "approved_by", "department", "service"]


@admin.register(models.BlackoutPeriod)
class BlackoutPeriodAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "period_type", "start_at", "end_at"]
    list_filter = ["period_type"]
    search_fields = ["code", "name"]
    raw_id_fields = ["created_by"]


@admin.register(models.ChangeSchedulingException)
class ChangeSchedulingExceptionAdmin(admin.ModelAdmin):
    list_display = ["change", "blackout_period", "maintenance_window", "status", "decided_by", "decision_timestamp"]
    list_filter = ["status"]
    search_fields = ["change__change_number", "justification"]
    raw_id_fields = ["change", "requesting_user", "decided_by"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("change", "blackout_period", "maintenance_window", "requesting_user", "decided_by")


@admin.register(models.ChangeConflict)
class ChangeConflictAdmin(admin.ModelAdmin):
    list_display = ["change", "conflicting_change", "conflict_type", "severity", "status"]
    list_filter = ["status", "conflict_type", "severity"]
    search_fields = ["change__change_number", "conflicting_change__change_number"]
    raw_id_fields = ["change", "conflicting_change", "acknowledged_by", "resolved_by"]


@admin.register(models.ChangeAttachment)
class ChangeAttachmentAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "change", "document_type", "status", "uploaded_by", "created_at"]
    list_filter = ["status", "document_type"]
    search_fields = ["original_filename", "change__change_number"]
    raw_id_fields = ["change", "task", "uploaded_by"]


@admin.register(models.ChangeStakeholder)
class ChangeStakeholderAdmin(admin.ModelAdmin):
    list_display = ["change", "user", "stakeholder_type", "notification_level", "created_at"]
    list_filter = ["stakeholder_type", "notification_level"]
    search_fields = ["change__change_number", "user__email"]
    raw_id_fields = ["change", "user", "department", "added_by"]


@admin.register(models.ChangeCommunication)
class ChangeCommunicationAdmin(admin.ModelAdmin):
    list_display = ["change", "communication_type", "audience", "status", "created_at"]
    list_filter = ["status", "communication_type", "audience"]
    search_fields = ["change__change_number", "subject"]
    raw_id_fields = ["change", "sent_by"]


@admin.register(models.ChangeImplementation)
class ChangeImplementationAdmin(admin.ModelAdmin):
    list_display = ["change", "status", "outcome", "started_by", "completed_by", "created_at"]
    list_filter = ["status", "outcome"]
    search_fields = ["change__change_number"]
    raw_id_fields = ["change", "started_by", "completed_by", "rollback_completed_by", "related_incident_ticket"]


@admin.register(models.PostImplementationReview)
class PostImplementationReviewAdmin(admin.ModelAdmin):
    list_display = ["change", "status", "outcome", "reviewer", "created_at"]
    list_filter = ["status", "outcome"]
    search_fields = ["change__change_number"]
    raw_id_fields = ["change", "reviewer", "reviewed_by", "knowledge_article"]


@admin.register(models.ChangeTicketLink)
class ChangeTicketLinkAdmin(admin.ModelAdmin):
    list_display = ["change", "ticket", "relation_type", "created_at"]
    list_filter = ["relation_type"]
    search_fields = ["change__change_number", "ticket__change_number"]
    raw_id_fields = ["change", "ticket", "created_by"]


@admin.register(models.ChangeKnowledgeLink)
class ChangeKnowledgeLinkAdmin(admin.ModelAdmin):
    list_display = ["change", "article", "relation_type", "created_at"]
    list_filter = ["relation_type"]
    search_fields = ["change__change_number", "article__title"]
    raw_id_fields = ["change", "article", "created_by"]

