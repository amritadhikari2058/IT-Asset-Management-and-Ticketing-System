from django.db import models
from django.utils import timezone
from accounts.models import User, Department


class ServiceCatalogueItem(models.Model):
    CATEGORY_CHOICES = [
        ("hardware", "Hardware"),
        ("software", "Software"),
        ("account", "Account"),
        ("access", "Access"),
        ("network", "Network"),
        ("email", "Email & M365"),
        ("onboarding", "Onboarding"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    icon = models.CharField(max_length=60, blank=True, default="bi-gear")
    is_active = models.BooleanField(default=True, db_index=True)
    requires_approval = models.BooleanField(default=False)
    creates_ticket = models.BooleanField(default=False)
    estimated_fulfilment_hours = models.PositiveIntegerField(null=True, blank=True)
    instructions = models.TextField(blank=True, default="")
    form_fields = models.JSONField(default=list, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="service_items_deleted")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]
        indexes = [models.Index(fields=["is_active", "is_deleted"])]

    def __str__(self):
        return self.name

    def soft_delete(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])


class ServiceRequest(models.Model):
    STATUS_CHOICES = [
        ("submitted", "Submitted"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("in_progress", "In Progress"),
        ("pending_employee", "Pending Employee"),
        ("fulfilled", "Fulfilled"),
        ("cancelled", "Cancelled"),
    ]
    PRIORITY_CHOICES = [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")]

    request_number = models.CharField(max_length=30, unique=True, db_index=True)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="service_requests")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="service_requests")
    catalogue_item = models.ForeignKey(ServiceCatalogueItem, on_delete=models.PROTECT, related_name="requests")
    answers = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted", db_index=True)
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_service_requests")
    approval_required = models.BooleanField(default=False)
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_service_requests")
    approval_decision = models.CharField(max_length=20, blank=True, default="")
    approval_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    fulfilment_ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="service_requests")
    fulfilment_details = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="service_requests_deleted")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["status", "submitted_at"]),
        ]

    def __str__(self):
        return self.request_number


class ServiceRequestComment(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="service_request_comments")
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ServiceRequestHistory(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="service_request_history")
    event = models.CharField(max_length=60)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ServiceRequestAttachment(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="service_request_attachments/%Y/%m/")
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="service_request_attachments")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["uploaded_at"]
