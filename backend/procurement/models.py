from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User, Department
from assets.models import Vendor, Asset
from common.models import SoftDeleteModel
from inventory.models import StockItem
from services.models import ServiceRequest


class ProcurementSetting(models.Model):
    """Configurable procurement approval thresholds."""

    approval_threshold = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=100000.00,
        help_text="Amount in local currency above which System Admin approval is required (in addition to IT Manager).",
    )
    currency = models.CharField(max_length=10, default="NPR")
    organization_name = models.CharField(max_length=200, default="IT Service Desk")
    delivery_address = models.TextField(blank=True, default="")
    po_terms = models.TextField(blank=True, default="")
    authorized_signatory_name = models.CharField(max_length=200, blank=True, default="")
    authorized_signatory_title = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="procurement_settings_updated"
    )

    class Meta:
        verbose_name = "Procurement Setting"
        verbose_name_plural = "Procurement Settings"

    def __str__(self):
        return f"Procurement Settings (threshold {self.currency} {self.approval_threshold})"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={})
        return obj


class PurchaseRequest(SoftDeleteModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("returned_for_correction", "Returned for Correction"),
        ("po_generated", "PO Generated"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
    ]

    pr_number = models.CharField(max_length=30, unique=True, db_index=True)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="purchase_requests")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_requests")
    reason = models.TextField()
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft", db_index=True)
    estimated_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    requires_system_admin_approval = models.BooleanField(default=False)
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_purchase_requests")
    approval_decision = models.CharField(max_length=20, blank=True, default="")
    approval_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["requester", "status"]),
        ]
        permissions = [
            ("approve_pr", "Can approve purchase requests"),
            ("reject_pr", "Can reject purchase requests"),
        ]

    def __str__(self):
        return self.pr_number

    def save(self, *args, **kwargs):
        if not self.pr_number:
            today = timezone.now().strftime("%Y%m%d")
            count = PurchaseRequest.objects.count() + 1
            self.pr_number = f"PR-{timezone.now().year}-{count:05d}"
        super().save(*args, **kwargs)


class PurchaseRequestItem(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    suggested_vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.SET_NULL)
    estimated_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estimated_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.purchase_request.pr_number} - {self.item_name} x{self.quantity}"


class PurchaseQuotation(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="quotations")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    quoted_amount = models.DecimalField(max_digits=14, decimal_places=2)
    delivery_days = models.PositiveIntegerField(null=True, blank=True)
    warranty = models.CharField(max_length=200, blank=True, default="")
    terms = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_selected = models.BooleanField(default=False)
    selected_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="selected_quotations")
    selected_at = models.DateTimeField(null=True, blank=True)
    selection_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-quoted_amount"]

    def __str__(self):
        return f"{self.purchase_request.pr_number} - {self.vendor.name} ({self.quoted_amount})"


class PurchaseOrder(SoftDeleteModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("sent_to_vendor", "Sent to Vendor"),
        ("partially_received", "Partially Received"),
        ("received", "Received"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
    ]

    po_number = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_orders")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_purchase_orders")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft", db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    shipping = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="NPR")
    delivery_address = models.TextField(blank=True, default="")
    terms = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    requires_system_admin_approval = models.BooleanField(default=False)
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_purchase_orders")
    approval_decision = models.CharField(max_length=20, blank=True, default="")
    approval_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["vendor", "status"]),
        ]
        permissions = [
            ("approve_po", "Can approve purchase orders"),
            ("reject_po", "Can reject purchase orders"),
            ("generate_po_pdf", "Can generate purchase order PDF"),
            ("receive_goods", "Can receive goods"),
        ]

    def __str__(self):
        return self.po_number

    def save(self, *args, **kwargs):
        if not self.po_number:
            count = PurchaseOrder.objects.count() + 1
            self.po_number = f"PO-{timezone.now().year}-{count:05d}"
        # Calculate total
        self.total = (self.subtotal or 0) + (self.tax or 0) + (self.shipping or 0) - (self.discount or 0)
        super().save(*args, **kwargs)


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    received_qty = models.PositiveIntegerField(default=0)
    rejected_qty = models.PositiveIntegerField(default=0)
    damaged_qty = models.PositiveIntegerField(default=0)
    is_serialized = models.BooleanField(default=False)
    stock_item = models.ForeignKey(StockItem, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        self.total = (self.quantity * self.unit_price) + (self.tax or 0) - (self.discount or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.purchase_order.po_number} - {self.item_name} x{self.quantity}"


class GoodsReceipt(SoftDeleteModel):
    gr_number = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="goods_receipts")
    delivery_note_number = models.CharField(max_length=120, blank=True, default="")
    invoice_number = models.CharField(max_length=120, blank=True, default="")
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="goods_receipts")
    received_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]
        permissions = [
            ("create_gr", "Can create goods receipts"),
        ]

    def save(self, *args, **kwargs):
        if not self.gr_number:
            count = GoodsReceipt.objects.count() + 1
            self.gr_number = f"GR-{timezone.now().year}-{count:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.gr_number


class GoodsReceiptItem(models.Model):
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="items")
    purchase_order_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.PROTECT)
    quantity_received = models.PositiveIntegerField(default=0)
    quantity_rejected = models.PositiveIntegerField(default=0)
    quantity_damaged = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.goods_receipt.gr_number} - {self.purchase_order_item.item_name}"


class ProcurementHistory(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("returned", "Returned for Correction"),
        ("po_generated", "PO Generated"),
        ("sent", "Sent to Vendor"),
        ("received", "Goods Received"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="history")
    purchase_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
